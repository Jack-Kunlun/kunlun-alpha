"""Entity extraction (P3-N04): candidate entity detection.

Pure, deterministic, offline. Callers inject the lexicon and decision time;
no production company list is hard-coded here (see :mod:`event_core.entities.
dictionary` for the generic builtin).
"""

from event_core.entities.dictionary import (
    BUILTIN_LEXICON_SOURCE,
    DictionaryEntry,
    EntityLexicon,
    builtin_lexicon,
    lexicon_fingerprint,
)
from event_core.entities.extractor import OriginalRun, extract_entities
from event_core.entities.models import (
    ENTITY_EXTRACTION_VERSION,
    EntityCandidate,
    EntityMention,
    EntityPolicyVersionError,
    EntityType,
    ExtractionPolicy,
    ExtractionReason,
    ExtractionResult,
    build_evidence,
    compute_mention_id,
    is_eligible,
    normalize_surface,
    utc_now,
)

__all__ = [
    "BUILTIN_LEXICON_SOURCE",
    "ENTITY_EXTRACTION_VERSION",
    "DictionaryEntry",
    "EntityCandidate",
    "EntityLexicon",
    "EntityMention",
    "EntityPolicyVersionError",
    "EntityType",
    "ExtractionPolicy",
    "ExtractionReason",
    "ExtractionResult",
    "OriginalRun",
    "build_evidence",
    "builtin_lexicon",
    "compute_mention_id",
    "extract_entities",
    "is_eligible",
    "lexicon_fingerprint",
    "normalize_surface",
    "utc_now",
]
