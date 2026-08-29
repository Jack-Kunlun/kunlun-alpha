"""Raw-first collection and versioned persistence for real market bars."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from ashare_contracts.market_data_bar import Bar as ProviderBar
from ashare_contracts.providers import Cursor
from data_worker.normalize import process_bars
from data_worker.normalize.rejection import RejectedRecord
from data_worker.providers.models import (
    SINA_OVERFETCH_OUTSIDE_REQUEST,
    BarExclusion,
    ProviderParseResult,
)
from data_worker.raw import (
    MARKET_CAPTURE_SCHEMA_VERSION,
    MARKET_CAPTURE_VERSION,
    RawObjectManifest,
    RawStorage,
    load_market_capture,
)
from market_core.providers import ProviderDataError
from market_core.storage import StoredBar
from market_core.validation import QualityEvent

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RawBarCapture(Protocol):
    """Provider-owned raw capture metadata consumed generically by the collector."""

    @property
    def body(self) -> bytes: ...

    @property
    def api_name(self) -> str: ...

    @property
    def request(self) -> str: ...

    @property
    def unified_code(self) -> str: ...

    @property
    def interval(self) -> str: ...

    @property
    def start_date(self) -> str: ...

    @property
    def end_date(self) -> str: ...

    @property
    def received_at(self) -> datetime: ...

    @property
    def source(self) -> str: ...

    @property
    def source_version(self) -> str: ...

    @property
    def content_type(self) -> str: ...


class RawBarProvider(Protocol):
    """Provider boundary required by the collector."""

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: Cursor | None = None,
    ) -> RawBarCapture: ...

    def parse_bars(self, capture: RawBarCapture) -> list[ProviderBar]: ...


class BarWriter(Protocol):
    """Versioned Bar persistence boundary."""

    def write_bars(self, bars: Iterable[StoredBar]) -> int: ...


class QualitySink(Protocol):
    """Durable rejection-evidence boundary required before writing Bars."""

    def record(
        self,
        manifest: RawObjectManifest,
        *,
        status: str,
        reason_code: str,
        reason_detail: str,
        rejected_records: Sequence[RejectedRecord],
        quality_events: Sequence[QualityEvent],
        filtered_records: Sequence[Mapping[str, object]],
        recorded_at: datetime | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class MarketDataCollectionResult:
    """Evidence and persistence counts for one provider request."""

    raw_capture_id: str
    received_bars: int
    written_bars: int


def _capture_id(run_id: str, ordinal: int, capture: RawBarCapture) -> str:
    if not run_id.strip():
        raise ValueError("run_id must be non-empty")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("capture_ordinal must be a non-negative integer")
    identity = (
        f"{run_id}|{ordinal}|{capture.api_name}|{capture.unified_code}|"
        f"{capture.interval}|{capture.start_date}|{capture.end_date}"
    )
    return f"market-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


def _replacement_version(value: datetime) -> int:
    elapsed = value.astimezone(UTC) - _EPOCH
    return elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds


def _normalize_provider_bar(bar: ProviderBar) -> dict[str, object]:
    raw = bar.model_dump(mode="json", by_alias=True)
    return cast(dict[str, object], raw)


def _provider_parse_rejection(capture: RawBarCapture) -> RejectedRecord:
    """Return bounded capture metadata without echoing request or error text."""

    return RejectedRecord(
        record={
            "apiName": capture.api_name,
            "unifiedCode": capture.unified_code,
            "interval": capture.interval,
            "requestedStart": capture.start_date,
            "requestedEnd": capture.end_date,
        },
        reason="provider_parse_error",
    )


class MarketDataCollector:
    """Persist immutable raw evidence before parsing and writing normalized Bars."""

    def __init__(
        self,
        provider: RawBarProvider,
        raw_storage: RawStorage,
        writer: BarWriter,
        *,
        quality_sink: QualitySink,
        clock: Clock = _utc_now,
    ) -> None:
        self._provider = provider
        self._raw_storage = raw_storage
        self._writer = writer
        self._quality_sink = quality_sink
        self._clock = clock

    def _record_quality(
        self,
        manifest: RawObjectManifest,
        *,
        status: str = "REJECTED",
        reason_code: str,
        reason_detail: str,
        rejected_records: Sequence[RejectedRecord],
        quality_events: Sequence[QualityEvent],
        filtered_records: Sequence[BarExclusion] = (),
    ) -> None:
        self._quality_sink.record(
            manifest,
            status=status,
            reason_code=reason_code,
            reason_detail=reason_detail,
            rejected_records=rejected_records,
            quality_events=quality_events,
            filtered_records=[item.to_quality_record() for item in filtered_records],
            recorded_at=self._clock(),
        )

    def _parse_provider_bars(self, capture: RawBarCapture) -> ProviderParseResult:
        """Parse bars while accepting legacy providers without exclusions."""

        parser = getattr(self._provider, "parse_bars_with_evidence", None)
        if parser is None:
            return ProviderParseResult(
                bars=self._provider.parse_bars(capture),
                exclusions=[],
            )
        if not callable(parser):
            raise ProviderDataError("provider evidenced parser is invalid")
        parse_with_evidence = cast(
            Callable[[RawBarCapture], object],
            parser,
        )
        result = parse_with_evidence(capture)
        if not isinstance(result, ProviderParseResult):
            raise ProviderDataError("provider evidenced parser returned an invalid result")
        return result

    def collect(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        *,
        run_id: str,
        capture_ordinal: int,
        processing_time: datetime | None = None,
    ) -> MarketDataCollectionResult:
        persisted_manifest = self._raw_storage.find_capture(
            market_run_id=run_id,
            capture_ordinal=capture_ordinal,
        )
        if persisted_manifest is not None:
            if (
                persisted_manifest.unified_code != unified_code
                or persisted_manifest.interval != interval
                or persisted_manifest.requested_start != start_date
                or persisted_manifest.requested_end != end_date
            ):
                raise ProviderDataError("persisted market capture does not match request")
            manifest = persisted_manifest
            capture = load_market_capture(self._raw_storage, manifest)
        else:
            capture = self._provider.fetch_raw_bars(
                unified_code,
                interval,
                start_date,
                end_date,
            )
            manifest = self._raw_storage.put(
                capture.source,
                capture.received_at.astimezone(_SHANGHAI).date().isoformat(),
                capture.request,
                capture.body,
                capture.content_type,
                capture_id=_capture_id(run_id, capture_ordinal, capture),
                ingest_time=capture.received_at,
                available_time=capture.received_at,
                schema_version=MARKET_CAPTURE_SCHEMA_VERSION,
                capture_version=MARKET_CAPTURE_VERSION,
                api_name=capture.api_name,
                unified_code=capture.unified_code,
                interval=capture.interval,
                requested_start=capture.start_date,
                requested_end=capture.end_date,
                source_version=capture.source_version,
                market_run_id=run_id,
                capture_ordinal=capture_ordinal,
            )

        try:
            parse_result = self._parse_provider_bars(capture)
            provider_bars = parse_result.bars
            exclusions = parse_result.exclusions
        except ProviderDataError as error:
            self._record_quality(
                manifest,
                reason_code="PROVIDER_PARSE_ERROR",
                reason_detail="provider parse failed",
                rejected_records=[_provider_parse_rejection(capture)],
                quality_events=[],
            )
            raise ProviderDataError(
                f"provider parse failed for captureId {manifest.capture_id}"
            ) from error
        except Exception as error:
            self._record_quality(
                manifest,
                reason_code="PROVIDER_PARSE_ERROR",
                reason_detail="provider parse failed",
                rejected_records=[_provider_parse_rejection(capture)],
                quality_events=[],
            )
            raise ProviderDataError(
                f"provider parse failed for captureId {manifest.capture_id}"
            ) from error

        provider_records = [_normalize_provider_bar(bar) for bar in provider_bars]
        try:
            pipeline = process_bars(provider_records)
        except Exception as error:
            self._record_quality(
                manifest,
                reason_code="BAR_QUALITY_REJECTED",
                reason_detail="bar normalization failed",
                rejected_records=[],
                quality_events=[],
                filtered_records=exclusions,
            )
            raise ProviderDataError(
                f"bar normalization failed for captureId {manifest.capture_id}"
            ) from error

        rejected_records = pipeline.rejection_zone.records()
        if rejected_records or pipeline.events:
            self._record_quality(
                manifest,
                reason_code="BAR_QUALITY_REJECTED",
                reason_detail="bar quality validation rejected this capture",
                rejected_records=rejected_records,
                quality_events=pipeline.events,
                filtered_records=exclusions,
            )
            raise ProviderDataError(
                f"market-data quality rejection for captureId {manifest.capture_id}"
            )
        if exclusions:
            self._record_quality(
                manifest,
                status="FILTERED",
                reason_code=SINA_OVERFETCH_OUTSIDE_REQUEST,
                reason_detail="Sina minute payload included rows outside the requested window",
                rejected_records=[],
                quality_events=[],
                filtered_records=exclusions,
            )
        normalized = pipeline.accepted

        assert manifest.available_time is not None
        replacement_version = _replacement_version(manifest.available_time)
        processing_time = self._clock() if processing_time is None else processing_time
        if processing_time.tzinfo is None or processing_time.utcoffset() is None:
            raise RuntimeError("market-data processing clock must be timezone-aware")
        processing_time = max(processing_time.astimezone(UTC), manifest.available_time)
        stored = [
            StoredBar(
                bar=bar,
                data_version="bar-v1",
                source=capture.source,
                source_version=capture.source_version,
                raw_capture_id=manifest.capture_id,
                ingest_time=manifest.ingest_time,
                available_time=manifest.available_time,
                processing_time=processing_time,
                replacement_version=replacement_version,
            )
            for bar in normalized
        ]
        written = self._writer.write_bars(stored)
        return MarketDataCollectionResult(
            raw_capture_id=manifest.capture_id,
            received_bars=len(provider_bars),
            written_bars=written,
        )


__all__ = [
    "BarWriter",
    "MarketDataCollectionResult",
    "MarketDataCollector",
    "MARKET_CAPTURE_SCHEMA_VERSION",
    "MARKET_CAPTURE_VERSION",
    "RawBarCapture",
    "RawBarProvider",
    "QualitySink",
]
