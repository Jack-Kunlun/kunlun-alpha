"""P5-N13 reproducible regression boundaries."""

from .artifact import (
    RegressionCanonicalizationError,
    RegressionIntegrityError,
    RegressionRunArtifact,
    RegressionValidationError,
    compute_artifact_sha256,
    parse_artifact_bytes,
)
from .baseline import BASELINE_SCHEMA_VERSION, BacktestRegressionBaseline, load_baseline
from .canonical import canonical_bytes, canonical_json, canonical_sha256, canonicalize
from .diff import DIFF_CATEGORIES, RegressionComparison, RegressionDiff, compare_artifacts
from .repository import (
    ArtifactConflictError,
    ArtifactCorruptionError,
    ArtifactRepositoryError,
    FileRunArtifactRepository,
    InMemoryRunArtifactRepository,
)
from .smoke import run_smoke_chain

__all__ = [
    "ArtifactConflictError",
    "ArtifactCorruptionError",
    "ArtifactRepositoryError",
    "BASELINE_SCHEMA_VERSION",
    "BacktestRegressionBaseline",
    "DIFF_CATEGORIES",
    "FileRunArtifactRepository",
    "InMemoryRunArtifactRepository",
    "RegressionCanonicalizationError",
    "RegressionComparison",
    "RegressionDiff",
    "RegressionIntegrityError",
    "RegressionRunArtifact",
    "RegressionValidationError",
    "canonical_bytes",
    "canonical_json",
    "canonical_sha256",
    "canonicalize",
    "compare_artifacts",
    "compute_artifact_sha256",
    "load_baseline",
    "parse_artifact_bytes",
    "run_smoke_chain",
]
