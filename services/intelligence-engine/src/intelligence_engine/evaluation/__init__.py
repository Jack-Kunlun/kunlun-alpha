"""Reproducible offline evaluation boundaries."""

from intelligence_engine.evaluation.events import (
    EVENT_EVALUATION_VERSION,
    EvaluationDataset,
    EvaluationError,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationReport,
    EvaluationSample,
    LabeledEvent,
    LabeledEvidenceSpan,
    PredictionSet,
    SampleEvaluation,
    SamplePrediction,
    evaluate_predictions,
    load_evaluation_dataset,
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
