"""Versioned, point-in-time offline evaluation for MarketEvent extraction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from event_core.models import MarketEvent, MarketEventType

EVENT_EVALUATION_VERSION = "event-eval-v1"
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_INSTRUMENT = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)")


class EvaluationError(ValueError):
    """Invalid dataset, prediction set, or point-in-time evaluation input."""


def _text(value: object, field_name: str, maximum: int = 256) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be non-empty and at most {maximum} characters")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: object, field_name: str) -> datetime:
    text = _text(value, field_name, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError(f"{field_name} must be ISO-8601") from error
    return _aware(parsed, field_name)


def _bps(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be a strict integer")
    if not 0 <= value <= 10_000:
        raise ValueError(f"{field_name} must be between 0 and 10000")
    return value


def _ratio(numerator: int, denominator: int, *, empty: int = 0) -> int:
    if denominator == 0:
        return empty
    return (numerator * 10_000 + denominator // 2) // denominator


def _f1(precision: int, recall: int) -> int:
    if precision + recall == 0:
        return 0
    return (2 * precision * recall + (precision + recall) // 2) // (precision + recall)


@dataclass(frozen=True, slots=True)
class LabeledEvidenceSpan:
    start_offset: int
    end_offset: int
    excerpt: str

    def __post_init__(self) -> None:
        if type(self.start_offset) is not int or type(self.end_offset) is not int:
            raise TypeError("label evidence offsets must be strict integers")
        if self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError("label evidence must be a non-empty half-open span")
        excerpt = _text(self.excerpt, "excerpt", 50_000)
        if len(excerpt) != self.end_offset - self.start_offset:
            raise ValueError("label evidence span length must equal excerpt length")


@dataclass(frozen=True, slots=True)
class LabeledEvent:
    label_id: str
    event_type: MarketEventType
    instrument_ids: tuple[str, ...]
    sector_ids: tuple[str, ...]
    evidence_spans: tuple[LabeledEvidenceSpan, ...]

    def __post_init__(self) -> None:
        _text(self.label_id, "label_id")
        if type(self.event_type) is not MarketEventType:
            raise TypeError("event_type must be a MarketEventType")
        for values, name in (
            (self.instrument_ids, "instrument_ids"),
            (self.sector_ids, "sector_ids"),
        ):
            if (
                type(values) is not tuple
                or values != tuple(sorted(values))
                or len(set(values)) != len(values)
            ):
                raise ValueError(f"{name} must be a sorted unique tuple")
        if any(_INSTRUMENT.fullmatch(value) is None for value in self.instrument_ids):
            raise ValueError("labels require canonical instrument IDs")
        if type(self.evidence_spans) is not tuple or not self.evidence_spans:
            raise ValueError("labeled event requires evidence spans")
        if any(type(span) is not LabeledEvidenceSpan for span in self.evidence_spans):
            raise TypeError("evidence_spans contains an invalid type")


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    sample_id: str
    content_version_id: str
    source_text: str
    label_available_time: datetime
    labels: tuple[LabeledEvent, ...]

    def __post_init__(self) -> None:
        _text(self.sample_id, "sample_id")
        version_id = _text(self.content_version_id, "content_version_id")
        if _HEX_64.fullmatch(version_id) is None:
            raise ValueError("content_version_id must be a SHA-256 digest")
        source = _text(self.source_text, "source_text", 2_000_000)
        available = _aware(self.label_available_time, "label_available_time")
        if type(self.labels) is not tuple:
            raise TypeError("labels must be a tuple")
        if len({label.label_id for label in self.labels}) != len(self.labels):
            raise ValueError("label IDs must be unique per sample")
        for label in self.labels:
            if type(label) is not LabeledEvent:
                raise TypeError("labels contains an invalid type")
            for span in label.evidence_spans:
                if (
                    span.end_offset > len(source)
                    or source[span.start_offset : span.end_offset] != span.excerpt
                ):
                    raise ValueError("label evidence must match the exact source text")
        object.__setattr__(self, "label_available_time", available)


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    version: str
    created_at: datetime
    samples: tuple[EvaluationSample, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.version, "version")
        created = _aware(self.created_at, "created_at")
        if type(self.samples) is not tuple or not self.samples:
            raise ValueError("evaluation dataset must contain samples")
        if self.samples != tuple(sorted(self.samples, key=lambda item: item.sample_id)):
            raise ValueError("dataset samples must be sorted by sample_id")
        if len({sample.sample_id for sample in self.samples}) != len(self.samples):
            raise ValueError("dataset sample IDs must be unique")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(
            self,
            "fingerprint",
            _digest(
                _canonical(
                    {
                        "createdAt": created.isoformat(),
                        "samples": [
                            {
                                "contentVersionId": sample.content_version_id,
                                "labelAvailableTime": sample.label_available_time.isoformat(),
                                "labels": [
                                    {
                                        "eventType": label.event_type.value,
                                        "evidence": [
                                            [span.start_offset, span.end_offset, span.excerpt]
                                            for span in label.evidence_spans
                                        ],
                                        "instrumentIds": list(label.instrument_ids),
                                        "labelId": label.label_id,
                                        "sectorIds": list(label.sector_ids),
                                    }
                                    for label in sample.labels
                                ],
                                "sampleId": sample.sample_id,
                                "sourceText": sample.source_text,
                            }
                            for sample in self.samples
                        ],
                        "version": self.version,
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SamplePrediction:
    sample_id: str
    content_version_id: str
    events: tuple[MarketEvent, ...]

    def __post_init__(self) -> None:
        _text(self.sample_id, "sample_id")
        if _HEX_64.fullmatch(self.content_version_id) is None:
            raise ValueError("content_version_id must be a SHA-256 digest")
        if type(self.events) is not tuple or any(
            type(event) is not MarketEvent for event in self.events
        ):
            raise TypeError("events must be a tuple of MarketEvent")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("prediction events must not contain duplicates")


@dataclass(frozen=True, slots=True)
class PredictionSet:
    prediction_set_id: str
    model_version: str
    prompt_version: str
    configuration_fingerprint: str
    pipeline_version: str
    produced_at: datetime
    predictions: tuple[SamplePrediction, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.prediction_set_id, "prediction_set_id"),
            (self.model_version, "model_version"),
            (self.prompt_version, "prompt_version"),
            (self.pipeline_version, "pipeline_version"),
        ):
            _text(value, name)
        if _HEX_64.fullmatch(self.configuration_fingerprint) is None:
            raise ValueError("configuration_fingerprint must be a SHA-256 digest")
        produced = _aware(self.produced_at, "produced_at")
        if type(self.predictions) is not tuple:
            raise TypeError("predictions must be a tuple")
        if self.predictions != tuple(sorted(self.predictions, key=lambda item: item.sample_id)):
            raise ValueError("predictions must be sorted by sample_id")
        if len({item.sample_id for item in self.predictions}) != len(self.predictions):
            raise ValueError("sample predictions must be unique")
        for item in self.predictions:
            for event in item.events:
                provenance = event.model_provenance
                if (
                    provenance.model_version != self.model_version
                    or provenance.prompt_version != self.prompt_version
                    or provenance.configuration_fingerprint != self.configuration_fingerprint
                ):
                    raise ValueError("prediction provenance does not match prediction-set identity")
                if event.available_time > produced:
                    raise ValueError("prediction event cannot be available after produced_at")
        object.__setattr__(self, "produced_at", produced)
        object.__setattr__(
            self,
            "fingerprint",
            _digest(
                _canonical(
                    {
                        "configurationFingerprint": self.configuration_fingerprint,
                        "modelVersion": self.model_version,
                        "pipelineVersion": self.pipeline_version,
                        "predictionSetId": self.prediction_set_id,
                        "predictions": [
                            [
                                item.sample_id,
                                item.content_version_id,
                                [event.event_id for event in item.events],
                            ]
                            for item in self.predictions
                        ],
                        "producedAt": produced.isoformat(),
                        "promptVersion": self.prompt_version,
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    version: str = EVENT_EVALUATION_VERSION
    match_threshold_bps: int = 7_500
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.version != EVENT_EVALUATION_VERSION:
            raise ValueError(f"version must be {EVENT_EVALUATION_VERSION!r}")
        threshold = _bps(self.match_threshold_bps, "match_threshold_bps")
        object.__setattr__(self, "fingerprint", _digest(f"{self.version}:{threshold}"))


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    event_precision_bps: int
    event_recall_bps: int
    event_f1_bps: int
    event_type_accuracy_bps: int
    instrument_f1_bps: int
    evidence_exact_bps: int
    provenance_complete_bps: int
    sample_exact_accuracy_bps: int

    def __post_init__(self) -> None:
        for name in (
            "event_precision_bps",
            "event_recall_bps",
            "event_f1_bps",
            "event_type_accuracy_bps",
            "instrument_f1_bps",
            "evidence_exact_bps",
            "provenance_complete_bps",
            "sample_exact_accuracy_bps",
        ):
            _bps(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class SampleEvaluation:
    sample_id: str
    true_positive_count: int
    false_positive_event_ids: tuple[str, ...]
    false_negative_label_ids: tuple[str, ...]
    matched_pairs: tuple[tuple[str, str, int], ...]
    exact: bool


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_version: str
    dataset_fingerprint: str
    prediction_set_fingerprint: str
    evaluation_cutoff: datetime
    policy_fingerprint: str
    evaluated_sample_count: int
    excluded_future_label_count: int
    label_event_count: int
    predicted_event_count: int
    matched_event_count: int
    metrics: EvaluationMetrics
    samples: tuple[SampleEvaluation, ...]
    report_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = _aware(self.evaluation_cutoff, "evaluation_cutoff")
        object.__setattr__(self, "evaluation_cutoff", cutoff)
        object.__setattr__(
            self,
            "report_id",
            _digest(
                _canonical(
                    {
                        "cutoff": cutoff.isoformat(),
                        "dataset": self.dataset_fingerprint,
                        "metrics": {
                            "eventF1Bps": self.metrics.event_f1_bps,
                            "eventPrecisionBps": self.metrics.event_precision_bps,
                            "eventRecallBps": self.metrics.event_recall_bps,
                            "eventTypeAccuracyBps": self.metrics.event_type_accuracy_bps,
                            "evidenceExactBps": self.metrics.evidence_exact_bps,
                            "instrumentF1Bps": self.metrics.instrument_f1_bps,
                            "provenanceCompleteBps": self.metrics.provenance_complete_bps,
                            "sampleExactAccuracyBps": self.metrics.sample_exact_accuracy_bps,
                        },
                        "policy": self.policy_fingerprint,
                        "predictionSet": self.prediction_set_fingerprint,
                        "samples": [
                            {
                                "exact": sample.exact,
                                "falseNegativeLabelIds": list(sample.false_negative_label_ids),
                                "falsePositiveEventIds": list(sample.false_positive_event_ids),
                                "matchedPairs": [list(pair) for pair in sample.matched_pairs],
                                "sampleId": sample.sample_id,
                                "truePositiveCount": sample.true_positive_count,
                            }
                            for sample in self.samples
                        ],
                    }
                )
            ),
        )


def _jaccard[T](left: set[T], right: set[T]) -> int:
    if not left and not right:
        return 10_000
    return _ratio(len(left & right), len(left | right))


def _match_score(label: LabeledEvent, prediction: MarketEvent) -> int:
    label_evidence = {
        (span.start_offset, span.end_offset, span.excerpt) for span in label.evidence_spans
    }
    predicted_evidence = {
        (span.start_offset, span.end_offset, span.excerpt) for span in prediction.evidence
    }
    return (
        (3_000 if label.event_type is prediction.event_type else 0)
        + _jaccard(set(label.instrument_ids), set(prediction.instrument_ids)) * 3_000 // 10_000
        + _jaccard(set(label.sector_ids), set(prediction.sector_ids)) * 1_000 // 10_000
        + _jaccard(label_evidence, predicted_evidence) * 3_000 // 10_000
    )


def evaluate_predictions(
    dataset: EvaluationDataset,
    prediction_set: PredictionSet,
    *,
    evaluation_cutoff: datetime,
    policy: EvaluationPolicy | None = None,
) -> EvaluationReport:
    """Evaluate one immutable prediction set without future-label leakage."""
    if type(dataset) is not EvaluationDataset or type(prediction_set) is not PredictionSet:
        raise TypeError("dataset and prediction_set must use evaluation domain types")
    cutoff = _aware(evaluation_cutoff, "evaluation_cutoff")
    if prediction_set.produced_at > cutoff:
        raise EvaluationError("prediction set was produced after evaluation cutoff")
    active_policy = policy or EvaluationPolicy()
    sample_by_id = {sample.sample_id: sample for sample in dataset.samples}
    prediction_by_id = {item.sample_id: item for item in prediction_set.predictions}
    unknown = set(prediction_by_id) - set(sample_by_id)
    if unknown:
        raise EvaluationError("prediction set contains unknown sample IDs")
    for sample_id, prediction in prediction_by_id.items():
        if prediction.content_version_id != sample_by_id[sample_id].content_version_id:
            raise EvaluationError("prediction content version does not match dataset")

    eligible = [sample for sample in dataset.samples if sample.label_available_time <= cutoff]
    excluded = len(dataset.samples) - len(eligible)
    sample_results: list[SampleEvaluation] = []
    label_count = predicted_count = matched_count = 0
    type_correct = evidence_exact = provenance_complete = exact_samples = 0
    instrument_tp = instrument_predicted = instrument_labeled = 0
    for sample in eligible:
        labels = list(sample.labels)
        predictions = list(
            prediction_by_id.get(
                sample.sample_id, SamplePrediction(sample.sample_id, sample.content_version_id, ())
            ).events
        )
        label_count += len(labels)
        predicted_count += len(predictions)
        provenance_complete += sum(
            1
            for event in predictions
            if event.model_provenance.configuration_fingerprint
            and event.model_provenance.model_version
            and event.model_provenance.prompt_version
        )
        candidates = sorted(
            (
                (_match_score(label, prediction), label_index, prediction_index)
                for label_index, label in enumerate(labels)
                for prediction_index, prediction in enumerate(predictions)
            ),
            key=lambda item: (-item[0], labels[item[1]].label_id, predictions[item[2]].event_id),
        )
        used_labels: set[int] = set()
        used_predictions: set[int] = set()
        pairs: list[tuple[str, str, int]] = []
        for score, label_index, prediction_index in candidates:
            if score < active_policy.match_threshold_bps:
                break
            if label_index in used_labels or prediction_index in used_predictions:
                continue
            used_labels.add(label_index)
            used_predictions.add(prediction_index)
            label = labels[label_index]
            prediction = predictions[prediction_index]
            pairs.append((label.label_id, prediction.event_id, score))
            type_correct += int(label.event_type is prediction.event_type)
            label_evidence = {
                (span.start_offset, span.end_offset, span.excerpt) for span in label.evidence_spans
            }
            prediction_evidence = {
                (span.start_offset, span.end_offset, span.excerpt) for span in prediction.evidence
            }
            evidence_exact += int(label_evidence == prediction_evidence)
            instrument_tp += len(set(label.instrument_ids) & set(prediction.instrument_ids))
            instrument_predicted += len(prediction.instrument_ids)
            instrument_labeled += len(label.instrument_ids)
        for index, label in enumerate(labels):
            if index not in used_labels:
                instrument_labeled += len(label.instrument_ids)
        for index, prediction in enumerate(predictions):
            if index not in used_predictions:
                instrument_predicted += len(prediction.instrument_ids)
        matched_count += len(pairs)
        false_positive = tuple(
            sorted(
                prediction.event_id
                for index, prediction in enumerate(predictions)
                if index not in used_predictions
            )
        )
        false_negative = tuple(
            sorted(label.label_id for index, label in enumerate(labels) if index not in used_labels)
        )
        exact = not false_positive and not false_negative
        exact_samples += int(exact)
        sample_results.append(
            SampleEvaluation(
                sample_id=sample.sample_id,
                true_positive_count=len(pairs),
                false_positive_event_ids=false_positive,
                false_negative_label_ids=false_negative,
                matched_pairs=tuple(sorted(pairs)),
                exact=exact,
            )
        )

    empty_event_task = label_count == 0 and predicted_count == 0
    precision = _ratio(matched_count, predicted_count, empty=10_000 if empty_event_task else 0)
    recall = _ratio(matched_count, label_count, empty=10_000 if empty_event_task else 0)
    instrument_precision = _ratio(
        instrument_tp,
        instrument_predicted,
        empty=10_000 if instrument_labeled == 0 else 0,
    )
    instrument_recall = _ratio(
        instrument_tp,
        instrument_labeled,
        empty=10_000 if instrument_predicted == 0 else 0,
    )
    metrics = EvaluationMetrics(
        event_precision_bps=precision,
        event_recall_bps=recall,
        event_f1_bps=_f1(precision, recall),
        event_type_accuracy_bps=_ratio(
            type_correct, matched_count, empty=10_000 if empty_event_task else 0
        ),
        instrument_f1_bps=_f1(instrument_precision, instrument_recall),
        evidence_exact_bps=_ratio(
            evidence_exact, matched_count, empty=10_000 if empty_event_task else 0
        ),
        provenance_complete_bps=_ratio(provenance_complete, predicted_count, empty=10_000),
        sample_exact_accuracy_bps=_ratio(exact_samples, len(eligible), empty=10_000),
    )
    return EvaluationReport(
        dataset_version=dataset.version,
        dataset_fingerprint=dataset.fingerprint,
        prediction_set_fingerprint=prediction_set.fingerprint,
        evaluation_cutoff=cutoff,
        policy_fingerprint=active_policy.fingerprint,
        evaluated_sample_count=len(eligible),
        excluded_future_label_count=excluded,
        label_event_count=label_count,
        predicted_event_count=predicted_count,
        matched_event_count=matched_count,
        metrics=metrics,
        samples=tuple(sample_results),
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise EvaluationError(f"{name} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise EvaluationError(f"{name} must be an array")
    return cast(list[object], value)


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    """Load a strict, sanitized JSONL fixture into a content-addressed dataset."""
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise EvaluationError("dataset file is empty")
    samples: list[EvaluationSample] = []
    versions: set[str] = set()
    created_times: set[datetime] = set()
    for line in rows:
        try:
            row = _mapping(cast(object, json.loads(line)), "sample")
        except json.JSONDecodeError as error:
            raise EvaluationError("dataset contains invalid JSON") from error
        required = {
            "contentVersionId",
            "datasetCreatedAt",
            "datasetVersion",
            "labelAvailableTime",
            "labels",
            "sampleId",
            "sourceText",
        }
        if set(row) != required:
            raise EvaluationError("dataset sample fields are invalid")
        versions.add(_text(row["datasetVersion"], "datasetVersion"))
        created_times.add(_parse_time(row["datasetCreatedAt"], "datasetCreatedAt"))
        labels: list[LabeledEvent] = []
        for raw_label in _list(row["labels"], "labels"):
            label = _mapping(raw_label, "label")
            if set(label) != {
                "eventType",
                "evidenceSpans",
                "instrumentIds",
                "labelId",
                "sectorIds",
            }:
                raise EvaluationError("label fields are invalid")
            spans: list[LabeledEvidenceSpan] = []
            for raw_span in _list(label["evidenceSpans"], "evidenceSpans"):
                span = _mapping(raw_span, "evidenceSpan")
                if set(span) != {"endOffset", "excerpt", "startOffset"}:
                    raise EvaluationError("evidence span fields are invalid")
                spans.append(
                    LabeledEvidenceSpan(
                        cast(int, span["startOffset"]),
                        cast(int, span["endOffset"]),
                        cast(str, span["excerpt"]),
                    )
                )
            labels.append(
                LabeledEvent(
                    label_id=cast(str, label["labelId"]),
                    event_type=MarketEventType(cast(str, label["eventType"])),
                    instrument_ids=tuple(sorted(cast(list[str], label["instrumentIds"]))),
                    sector_ids=tuple(sorted(cast(list[str], label["sectorIds"]))),
                    evidence_spans=tuple(spans),
                )
            )
        samples.append(
            EvaluationSample(
                sample_id=cast(str, row["sampleId"]),
                content_version_id=cast(str, row["contentVersionId"]),
                source_text=cast(str, row["sourceText"]),
                label_available_time=_parse_time(row["labelAvailableTime"], "labelAvailableTime"),
                labels=tuple(labels),
            )
        )
    if len(versions) != 1 or len(created_times) != 1:
        raise EvaluationError("dataset version and creation time must be consistent")
    return EvaluationDataset(
        version=next(iter(versions)),
        created_at=next(iter(created_times)),
        samples=tuple(sorted(samples, key=lambda item: item.sample_id)),
    )


__all__ = [
    "EVENT_EVALUATION_VERSION",
    "EvaluationDataset",
    "EvaluationError",
    "EvaluationMetrics",
    "EvaluationPolicy",
    "EvaluationReport",
    "EvaluationSample",
    "LabeledEvent",
    "LabeledEvidenceSpan",
    "PredictionSet",
    "SampleEvaluation",
    "SamplePrediction",
    "evaluate_predictions",
    "load_evaluation_dataset",
]
