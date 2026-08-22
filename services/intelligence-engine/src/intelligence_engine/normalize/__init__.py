"""Content normalization package (P3-N02).

Public API is re-exported here. Offsets are zero-based, half-open ``[start,
end)`` character intervals over Python ``str`` code points; ``original_*``
offsets refer to the immutable RawContent text, ``normalized_*`` offsets to
the final normalized text.
"""

from __future__ import annotations

from intelligence_engine.normalize.metadata import (
    AttachmentInput,
    AttachmentStatus,
    AuthorInput,
    NormalizedAttachment,
    NormalizedAuthor,
    NormalizedAuthors,
    NormalizedTimes,
    has_usable_attachment,
    normalize_attachments,
    normalize_authors,
    normalize_times,
)
from intelligence_engine.normalize.model import (
    NORMALIZATION_VERSION,
    EditRecord,
    EmptyBodyReason,
    NormalizationAuditError,
    NormalizationPolicy,
    NormalizationStatus,
    NormalizedText,
    Operation,
    QualityReviewReason,
    Reason,
    RejectionReason,
    SpanRun,
    UnrecoverableTextError,
    UnsupportedNormalizationVersionError,
    audit_normalization,
    restore_original,
)
from intelligence_engine.normalize.service import (
    NormalizedContent,
    audit_faithful_content,
    normalize,
)
from intelligence_engine.normalize.text_pipeline import (
    audit_faithful_normalization,
    detect_suspected_mojibake,
    is_confidently_recoverable_mojibake,
    is_fully_recoverable_mojibake,
    normalize_text,
)

__all__ = [
    "NORMALIZATION_VERSION",
    "AttachmentInput",
    "AttachmentStatus",
    "AuthorInput",
    "EditRecord",
    "EmptyBodyReason",
    "NormalizationAuditError",
    "NormalizationPolicy",
    "NormalizationStatus",
    "NormalizedAttachment",
    "NormalizedAuthors",
    "NormalizedAuthor",
    "NormalizedContent",
    "NormalizedText",
    "NormalizedTimes",
    "Operation",
    "QualityReviewReason",
    "Reason",
    "RejectionReason",
    "SpanRun",
    "UnrecoverableTextError",
    "UnsupportedNormalizationVersionError",
    "audit_faithful_content",
    "audit_faithful_normalization",
    "audit_normalization",
    "detect_suspected_mojibake",
    "has_usable_attachment",
    "is_confidently_recoverable_mojibake",
    "is_fully_recoverable_mojibake",
    "normalize",
    "normalize_attachments",
    "normalize_authors",
    "normalize_text",
    "normalize_times",
    "restore_original",
]
