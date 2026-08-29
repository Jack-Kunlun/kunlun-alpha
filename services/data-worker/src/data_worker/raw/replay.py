"""Deterministic replay helpers for immutable raw captures."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from ashare_contracts.market_data_bar import Bar
from market_core.providers.tushare import (
    TushareBarCapture,
    validate_tushare_capture_profile,
)

from data_worker.providers.akshare import (
    AKShareBarCapture,
    validate_akshare_capture_profile,
)
from data_worker.raw.manifest import (
    MARKET_CAPTURE_SCHEMA_VERSION,
    MARKET_CAPTURE_VERSION,
    RawObjectManifest,
)
from data_worker.raw.storage import RawStorage


class MarketBarParser(Protocol):
    """Provider parser boundary used when replaying a persisted capture."""

    def parse_bars(self, capture: object) -> list[Bar]: ...


def _market_route_value(manifest: RawObjectManifest, field_name: str) -> str:
    value = getattr(manifest, field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"market capture metadata is incomplete: {field_name}")
    return value


def _validate_market_versions(manifest: RawObjectManifest) -> None:
    if manifest.schema_version != MARKET_CAPTURE_SCHEMA_VERSION:
        raise ValueError("unsupported market capture schema version")
    if manifest.capture_version != MARKET_CAPTURE_VERSION:
        raise ValueError("unsupported market capture version")


def _capture_from_manifest(
    manifest: RawObjectManifest,
    body: bytes,
) -> AKShareBarCapture | TushareBarCapture:
    """Rebuild the provider-specific capture envelope from manifest metadata."""

    if not manifest.is_market_capture:
        raise ValueError("manifest does not contain a market capture route")
    _validate_market_versions(manifest)
    api_name = _market_route_value(manifest, "api_name")
    unified_code = _market_route_value(manifest, "unified_code")
    interval = _market_route_value(manifest, "interval")
    start_date = _market_route_value(manifest, "requested_start")
    end_date = _market_route_value(manifest, "requested_end")
    source_version = _market_route_value(manifest, "source_version")
    if manifest.source in {"akshare-eastmoney", "akshare-tencent", "akshare-sina"}:
        capture = AKShareBarCapture(
            body=body,
            api_name=api_name,
            request=manifest.request,
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=manifest.received_at,
            source=manifest.source,
            source_version=source_version,
            content_type=manifest.content_type,
        )
        return validate_akshare_capture_profile(capture)
    if manifest.source == "tushare-pro":
        capture = TushareBarCapture(
            body=body,
            api_name=api_name,
            request=manifest.request,
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=manifest.received_at,
            source=manifest.source,
            source_version=source_version,
            content_type=manifest.content_type,
        )
        return validate_tushare_capture_profile(capture)
    raise ValueError(f"unknown source for market capture: {manifest.source}")


def replay_market_capture(
    storage: RawStorage,
    manifest: RawObjectManifest,
    provider: MarketBarParser,
) -> list[Bar]:
    """Replay one market capture from its verified raw bytes.

    The in-memory provider capture is intentionally not accepted.  The
    provider-specific envelope is rebuilt solely from the manifest and the
    checksum/size-verified object bytes, making replay safe after restart.
    """

    if not manifest.is_market_capture:
        raise ValueError("manifest does not contain a market capture route")
    _validate_market_versions(manifest)
    capture = load_market_capture(storage, manifest)
    return provider.parse_bars(capture)


def load_market_capture(
    storage: RawStorage,
    manifest: RawObjectManifest,
) -> AKShareBarCapture | TushareBarCapture:
    """Rebuild a provider capture solely from verified persisted evidence."""

    if not manifest.is_market_capture:
        raise ValueError("manifest does not contain a market capture route")
    _validate_market_versions(manifest)
    body = storage.get(
        manifest.object_id,
        checksum=manifest.checksum,
        size=manifest.size,
    )
    return _capture_from_manifest(manifest, body)


def replay(
    storage: RawStorage,
    source: str,
    date: str,
    handler: Callable[[RawObjectManifest, bytes], None],
) -> int:
    """Replay every capture in deterministic ingest-time/capture order.

    The manifest is passed for every capture, even when multiple captures
    point to one shared content object.  Integrity is checked against the
    manifest's checksum and byte size before the handler is invoked.
    """

    manifests = storage.list(source, date)
    for manifest in manifests:
        content = storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
        handler(manifest, content)
    return len(manifests)


def decode_json(content: bytes) -> object:
    """Decode a JSON payload without binary-float ingress.

    JSON numbers containing a decimal point or exponent become ``Decimal``;
    integer values remain Python integers.  The original bytes remain the
    immutable source of truth in the raw object store.
    """

    return json.loads(content.decode("utf-8"), parse_float=Decimal)


def replay_json(
    storage: RawStorage,
    source: str,
    date: str,
    handler: Callable[[RawObjectManifest, object], None],
) -> int:
    """Replay JSON captures using :func:`decode_json` for each response."""

    manifests = storage.list(source, date)
    for manifest in manifests:
        content = storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
        handler(manifest, decode_json(content))
    return len(manifests)
