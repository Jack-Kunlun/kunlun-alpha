"""Public feature registry API."""

from .registry import (
    DuplicateFeatureNameError,
    FeatureDependencyCycleError,
    FeatureRegistry,
    FeatureRegistryError,
    FeatureRemovalError,
    FeatureVersionConflictError,
    MissingFeatureDependencyError,
    RegistryLineageConflictError,
    SemanticVersionRequiredError,
)
from .spec import (
    FEATURE_SPEC_SCHEMA_VERSION,
    AvailabilityPolicy,
    FeatureDependency,
    FeatureEntity,
    FeatureFrequency,
    FeatureSpec,
    FeatureSpecValidationError,
    FeatureValueType,
    SourceContract,
)

__all__ = [
    "FEATURE_SPEC_SCHEMA_VERSION",
    "AvailabilityPolicy",
    "DuplicateFeatureNameError",
    "FeatureDependency",
    "FeatureDependencyCycleError",
    "FeatureEntity",
    "FeatureFrequency",
    "FeatureRegistry",
    "FeatureRegistryError",
    "FeatureRemovalError",
    "FeatureSpec",
    "FeatureSpecValidationError",
    "FeatureValueType",
    "FeatureVersionConflictError",
    "MissingFeatureDependencyError",
    "RegistryLineageConflictError",
    "SemanticVersionRequiredError",
    "SourceContract",
]
