"""Offline event extraction evaluation acceptance tests (P3-N09)."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from event_core.models import (
    MARKET_EVENT_SCHEMA_VERSION,
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
)
from intelligence_engine.evaluation import (
    EvaluationDataset,
    EvaluationError,
    EvaluationSample,
    LabeledEvent,
    LabeledEvidenceSpan,
    PredictionSet,
    SamplePrediction,
    evaluate_predictions,
    load_evaluation_dataset,
)

CREATED = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)
CONFIG = hashlib.sha256(b"configuration").hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def labeled_sample(*, available: datetime = CREATED, no_event: bool = False) -> EvaluationSample:
    text = "公司发布重大事项公告"
    labels = (
        ()
        if no_event
        else (
            LabeledEvent(
                label_id="label-1",
                event_type=MarketEventType.CORPORATE,
                instrument_ids=("600519.SH",),
                sector_ids=("sector-food",),
                evidence_spans=(LabeledEvidenceSpan(0, len(text), text),),
            ),
        )
    )
    return EvaluationSample(
        sample_id="sample-empty" if no_event else "sample-1",
        content_version_id=digest("empty" if no_event else "content"),
        source_text=text,
        label_available_time=available,
        labels=labels,
    )


def predicted_event(*, evidence: str = "公司发布重大事项公告") -> MarketEvent:
    available = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    return MarketEvent(
        event_type=MarketEventType.CORPORATE,
        headline="某公司发布重大事项公告",
        summary="公司公告披露一项可追溯的重大事项。",
        occur_time=available,
        publish_time=available,
        available_time=available,
        instrument_ids=("600519.SH",),
        sector_ids=("sector-food",),
        evidence=(
            EventEvidence(
                evidence_id=digest("evidence" + evidence),
                content_record_id="record-1",
                content_version_id=digest("content"),
                source_id="cninfo",
                source_version="v1",
                available_time=available,
                start_offset=0,
                end_offset=len(evidence),
                excerpt=evidence,
            ),
        ),
        model_provenance=ModelProvenance(
            producer_type=ProducerType.MODEL,
            provider="provider-a",
            model_id="event-extractor",
            model_version="model-v1",
            prompt_version="prompt-v1",
            output_schema_version=MARKET_EVENT_SCHEMA_VERSION,
            configuration_fingerprint=CONFIG,
            extraction_run_id="run-1",
            processing_time=available,
        ),
        confidence_bps=9000,
    )


def dataset(*samples: EvaluationSample) -> EvaluationDataset:
    return EvaluationDataset(
        version="event-extraction-eval-v1",
        created_at=CREATED,
        samples=tuple(sorted(samples, key=lambda item: item.sample_id)),
    )


def predictions(*items: SamplePrediction, produced_at: datetime = CUTOFF) -> PredictionSet:
    return PredictionSet(
        prediction_set_id="prediction-set-1",
        model_version="model-v1",
        prompt_version="prompt-v1",
        configuration_fingerprint=CONFIG,
        pipeline_version="event-extraction-pipeline-v1",
        produced_at=produced_at,
        predictions=tuple(sorted(items, key=lambda item: item.sample_id)),
    )


def test_perfect_prediction_is_reproducible_and_scores_full_marks() -> None:
    sample = labeled_sample()
    prediction = SamplePrediction(sample.sample_id, sample.content_version_id, (predicted_event(),))
    first = evaluate_predictions(dataset(sample), predictions(prediction), evaluation_cutoff=CUTOFF)
    second = evaluate_predictions(
        dataset(sample), predictions(prediction), evaluation_cutoff=CUTOFF
    )
    assert first == second
    assert first.report_id == second.report_id
    assert first.metrics.event_precision_bps == 10_000
    assert first.metrics.event_recall_bps == 10_000
    assert first.metrics.event_f1_bps == 10_000
    assert first.metrics.evidence_exact_bps == 10_000


def test_false_positive_and_false_negative_are_preserved_per_sample() -> None:
    positive = labeled_sample()
    empty = labeled_sample(no_event=True)
    false_positive = SamplePrediction(
        empty.sample_id, empty.content_version_id, (predicted_event(),)
    )
    report = evaluate_predictions(
        dataset(positive, empty),
        predictions(false_positive),
        evaluation_cutoff=CUTOFF,
    )
    assert report.matched_event_count == 0
    assert report.predicted_event_count == 1
    assert report.label_event_count == 1
    assert report.metrics.event_f1_bps == 0
    assert any(item.false_negative_label_ids for item in report.samples)
    assert any(item.false_positive_event_ids for item in report.samples)


def test_future_labels_are_excluded_and_counted() -> None:
    current = labeled_sample()
    future = dataclasses.replace(
        labeled_sample(no_event=True),
        label_available_time=CUTOFF + timedelta(seconds=1),
    )
    report = evaluate_predictions(
        dataset(current, future),
        predictions(),
        evaluation_cutoff=CUTOFF,
    )
    assert report.evaluated_sample_count == 1
    assert report.excluded_future_label_count == 1


def test_prediction_created_after_cutoff_is_rejected() -> None:
    with pytest.raises(EvaluationError, match="after evaluation cutoff"):
        evaluate_predictions(
            dataset(labeled_sample()),
            predictions(produced_at=CUTOFF + timedelta(seconds=1)),
            evaluation_cutoff=CUTOFF,
        )


def test_prediction_must_bind_exact_dataset_content_version() -> None:
    sample = labeled_sample()
    wrong = SamplePrediction(sample.sample_id, digest("wrong"), ())
    with pytest.raises(EvaluationError, match="content version"):
        evaluate_predictions(dataset(sample), predictions(wrong), evaluation_cutoff=CUTOFF)


def test_evidence_mismatch_lowers_match_and_remains_a_regression() -> None:
    sample = labeled_sample()
    mismatch = predicted_event(evidence="不同的伪造证据")
    prediction = SamplePrediction(sample.sample_id, sample.content_version_id, (mismatch,))
    report = evaluate_predictions(
        dataset(sample), predictions(prediction), evaluation_cutoff=CUTOFF
    )
    assert report.metrics.evidence_exact_bps == 0
    assert report.samples[0].false_positive_event_ids
    assert report.samples[0].false_negative_label_ids


def test_sanitized_jsonl_fixture_has_stable_dataset_identity() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "research" / "event-intelligence" / "fixtures" / "event-extraction-eval-v1.jsonl"
    first = load_evaluation_dataset(path)
    second = load_evaluation_dataset(path)
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert len(first.samples) == 3
    assert all("真实" not in sample.source_text for sample in first.samples)


def test_dataset_rejects_evidence_that_does_not_match_source() -> None:
    sample = labeled_sample()
    bad_label = dataclasses.replace(
        sample.labels[0],
        evidence_spans=(LabeledEvidenceSpan(0, 4, "错误证据"),),
    )
    with pytest.raises(ValueError, match="exact source"):
        dataclasses.replace(sample, labels=(bad_label,))
