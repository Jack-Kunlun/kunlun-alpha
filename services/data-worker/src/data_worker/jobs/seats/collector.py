"""P4-N03 collection job: raw first, deterministic normalization second."""

from __future__ import annotations

import hashlib

from data_worker.jobs.seats.models import (
    NormalizedSeatTrade,
    RawSeatListRecord,
    RejectedSeatRecord,
    RevisionConflictError,
    SeatBatchResult,
    SeatCollectionRequest,
    SeatFetchRequest,
    SeatProviderBatch,
)
from data_worker.jobs.seats.provider import SeatListProvider
from data_worker.jobs.seats.repository import SeatRepository
from seat_core import Alias, Currency, SeatProfile, Trade
from seat_core.normalize import (
    TradeNormalizationError,
    normalize_instrument_id,
    normalize_trade_amounts,
)
from seat_core.resolution import (
    AliasResolutionRequest,
    ResolutionPolicy,
    ResolutionResult,
    ResolutionStatus,
    resolve_alias,
)


def _trade_id(record: RawSeatListRecord, seat_id: str, instrument_id: str) -> str:
    material = "\0".join(
        ("seat-trade-v1", record.raw_record_id, record.revision_id, seat_id, instrument_id)
    ).encode("utf-8")
    return f"seat-trade-{hashlib.sha256(material).hexdigest()}"


def _candidate_evidence_ids(result: ResolutionResult) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                evidence.evidence_id
                for candidate in result.candidates
                for evidence in candidate.evidence
            }
        )
    )


def _rejected(
    record: RawSeatListRecord,
    *,
    reason: str,
    detail: str,
    result: ResolutionResult | None = None,
) -> RejectedSeatRecord:
    if result is None:
        return RejectedSeatRecord(
            raw_record_id=record.raw_record_id,
            revision_id=record.revision_id,
            reason=reason,
            detail=detail,
            resolution_status=None,
            candidate_seat_ids=(),
            candidate_evidence_ids=(),
        )
    return RejectedSeatRecord(
        raw_record_id=record.raw_record_id,
        revision_id=record.revision_id,
        reason=reason,
        detail=detail,
        resolution_status=result.status,
        candidate_seat_ids=tuple(candidate.seat_id for candidate in result.candidates),
        candidate_evidence_ids=_candidate_evidence_ids(result),
    )


def _normalize_record(
    record: RawSeatListRecord,
    *,
    request: SeatFetchRequest,
    profiles: tuple[SeatProfile, ...],
    aliases: tuple[Alias, ...],
    policy: ResolutionPolicy,
) -> NormalizedSeatTrade | RejectedSeatRecord:
    try:
        instrument_id = normalize_instrument_id(record.raw_instrument_id)
        buy_amount, sell_amount, net_amount = normalize_trade_amounts(
            record.buy_amount,
            record.sell_amount,
            record.vendor_net_amount,
        )
    except TradeNormalizationError as exc:
        return _rejected(record, reason=exc.reason, detail=str(exc))

    resolution_request = AliasResolutionRequest(
        request_id=f"seat-resolution:{record.raw_record_id}",
        raw_name=record.raw_seat_name,
        decision_time=request.decision_time,
        source=record.source,
        source_version=record.source_version,
        evidence_id=record.evidence_id,
        seat_kind_hint=record.seat_kind_hint,
    )
    resolution = resolve_alias(
        resolution_request,
        profiles=profiles,
        aliases=aliases,
        policy=policy,
    )
    if resolution.status is not ResolutionStatus.AUTO or resolution.selected_seat_id is None:
        reason = (
            "seat_resolution_review"
            if resolution.status is ResolutionStatus.REVIEW
            else "seat_resolution_reject"
        )
        return _rejected(
            record,
            reason=reason,
            detail=f"seat resolution status: {resolution.status.value}",
            result=resolution,
        )

    selected_candidate = next(
        candidate
        for candidate in resolution.candidates
        if candidate.seat_id == resolution.selected_seat_id
    )
    trade = Trade(
        trade_id=_trade_id(record, resolution.selected_seat_id, instrument_id),
        revision_id=record.revision_id,
        previous_revision_id=record.previous_revision_id,
        seat_id=resolution.selected_seat_id,
        raw_seat_name=record.raw_seat_name,
        instrument_id=instrument_id,
        trade_date=record.trade_date,
        currency=Currency.CNY,
        buy_amount=buy_amount,
        sell_amount=sell_amount,
        net_amount=net_amount,
        source=record.source,
        source_version=record.source_version,
        raw_record_id=record.raw_record_id,
        evidence_id=record.evidence_id,
        available_time=record.available_time,
    )
    return NormalizedSeatTrade(
        trade=trade,
        listing_reason=record.listing_reason,
        provider_evidence_id=record.evidence_id,
        seat_evidence_ids=tuple(item.evidence_id for item in selected_candidate.evidence),
        resolution_status=resolution.status,
        resolution_fingerprint=resolution.resolution_fingerprint,
    )


class SeatCollectionJob:
    """Collect one provider batch and commit only after complete normalization."""

    def __init__(
        self,
        provider: SeatListProvider,
        repository: SeatRepository,
        profiles: tuple[SeatProfile, ...],
        aliases: tuple[Alias, ...],
        policy: ResolutionPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._profiles = profiles
        self._aliases = aliases
        self._policy = policy or ResolutionPolicy()

    def run(self, request: SeatCollectionRequest | SeatFetchRequest) -> SeatBatchResult:
        provider_batch = self._provider.fetch(request)
        self._validate_batch(request, provider_batch)
        try:
            revision_rejections = self._repository.revision_rejections(
                provider_batch.records,
                route_key=request.checkpoint_route,
            )
        except RevisionConflictError:
            # The atomic repository commit owns the authoritative conflict check.
            revision_rejections = {}
        normalized: list[NormalizedSeatTrade] = []
        rejected: list[RejectedSeatRecord] = []
        for record in provider_batch.records:
            revision_reason = revision_rejections.get(record.raw_record_id)
            if revision_reason is not None:
                rejected.append(
                    _rejected(
                        record,
                        reason=revision_reason,
                        detail=f"revision chain rejected: {revision_reason}",
                    )
                )
                continue
            if record.available_time > request.decision_time:
                rejected.append(
                    _rejected(
                        record,
                        reason="raw_not_available_at_decision_time",
                        detail="raw record is not available at decision_time",
                    )
                )
                continue
            outcome = _normalize_record(
                record,
                request=request,
                profiles=self._profiles,
                aliases=self._aliases,
                policy=self._policy,
            )
            if isinstance(outcome, NormalizedSeatTrade):
                normalized.append(outcome)
            else:
                rejected.append(outcome)
        result = SeatBatchResult(
            batch_id=provider_batch.batch_id,
            route_key=request.checkpoint_route,
            request_fingerprint=request.request_fingerprint,
            batch_fingerprint=provider_batch.batch_fingerprint,
            raw_records=tuple(sorted(provider_batch.records, key=lambda item: item.raw_record_id)),
            normalized_trades=tuple(sorted(normalized, key=lambda item: item.trade.trade_id)),
            rejected_records=tuple(
                sorted(rejected, key=lambda item: (item.raw_record_id, item.reason))
            ),
            checkpoint_token=provider_batch.checkpoint_token,
            expected_previous_checkpoint=request.expected_previous_checkpoint,
        )
        return self._repository.commit(result)

    @staticmethod
    def _validate_batch(
        request: SeatCollectionRequest | SeatFetchRequest, batch: SeatProviderBatch
    ) -> None:
        if batch.batch_id != request.batch_id:
            raise ValueError("provider batch_id does not match request")
        if batch.source != request.source or batch.source_version != request.source_version:
            raise ValueError("provider batch source provenance does not match request")
        for record in batch.records:
            if record.trade_date != request.trade_date:
                raise ValueError("provider record trade_date does not match request")


__all__ = ["SeatCollectionJob"]
