"""Model-level tests: edit records, span runs, policy validation, audit/restore.

Offset semantics: all offsets are zero-based, half-open [start, end) character
intervals over Python ``str`` code points of the *original* RawContent text
(for ``original_*`` fields) or of the *final* normalized text (for
``normalized_*`` fields).
"""

from __future__ import annotations

import dataclasses

import pytest
from intelligence_engine.normalize import (
    NORMALIZATION_VERSION,
    EditRecord,
    NormalizationAuditError,
    NormalizationPolicy,
    NormalizedText,
    Operation,
    Reason,
    SpanRun,
    UnsupportedNormalizationVersionError,
    audit_normalization,
    restore_original,
)


def _record() -> EditRecord:
    return EditRecord(
        operation=Operation.REMOVE_CONTROL,
        original_start=0,
        original_end=1,
        normalized_start=0,
        normalized_end=0,
        original_fragment="\x00",
        replacement_fragment="",
        reason=Reason.CONTROL_CHARACTER_REMOVED,
        normalization_version=NORMALIZATION_VERSION,
    )


def test_edit_record_rejects_inverted_original_span() -> None:
    with pytest.raises(ValueError, match="original_start"):
        dataclasses.replace(_record(), original_start=5, original_end=2, original_fragment="abc")


def test_edit_record_rejects_negative_span() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        dataclasses.replace(_record(), normalized_start=-1, normalized_end=0)


def test_edit_record_rejects_fragment_length_mismatch() -> None:
    with pytest.raises(ValueError, match="original_fragment"):
        dataclasses.replace(_record(), original_start=0, original_end=3, original_fragment="ab")


def test_edit_record_accepts_zero_width_normalized_span() -> None:
    record = dataclasses.replace(_record(), normalized_start=4, normalized_end=4)
    assert record.normalized_start == record.normalized_end


def test_edit_record_rejects_inverted_normalized_span() -> None:
    with pytest.raises(ValueError, match="normalized_start"):
        dataclasses.replace(_record(), normalized_start=7, normalized_end=3)


def test_policy_rejects_unsupported_version() -> None:
    with pytest.raises(UnsupportedNormalizationVersionError):
        NormalizationPolicy(version="normalize-v999")


def test_policy_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="max_body_length"):
        NormalizationPolicy(max_body_length=0)
    with pytest.raises(ValueError, match="max_title_length"):
        NormalizationPolicy(max_title_length=-1)


def test_policy_default_version_is_current() -> None:
    assert NormalizationPolicy().version == NORMALIZATION_VERSION


def test_normalized_text_original_range_identity() -> None:
    text = NormalizedText(
        text="ab",
        runs=(
            SpanRun(0, 1, 0, 1, "a"),
            SpanRun(1, 2, 1, 2, "b"),
        ),
        edits=(),
    )
    assert text.original_range(0, 1) == (0, 1)
    assert text.original_range(0, 2) == (0, 2)


def test_normalized_text_original_range_empty_is_anchor() -> None:
    text = NormalizedText(
        text="",
        runs=(),
        edits=(),
    )
    assert text.original_range(0, 0) == (0, 0)


def test_restore_original_and_audit_on_handcrafted_example() -> None:
    # original "abc\x00d" -> normalized "abcd" with \x00 deleted at (3, 4)
    normalized = NormalizedText(
        text="abcd",
        runs=(
            SpanRun(0, 1, 0, 1, "a"),
            SpanRun(1, 2, 1, 2, "b"),
            SpanRun(2, 3, 2, 3, "c"),
            SpanRun(3, 4, 4, 5, "d"),
        ),
        edits=(
            dataclasses.replace(
                _record(),
                original_start=3,
                original_end=4,
                normalized_start=3,
                normalized_end=3,
            ),
        ),
    )
    original = "abc\x00d"
    assert restore_original(normalized, len(original)) == original
    audit_normalization(original, normalized)


def test_audit_detects_lost_content() -> None:
    # run for original index 1 is missing entirely -> content silently lost
    normalized = NormalizedText(
        text="ac",
        runs=(
            SpanRun(0, 1, 0, 1, "a"),
            SpanRun(1, 2, 2, 3, "c"),
        ),
        edits=(),
    )
    with pytest.raises(NormalizationAuditError, match="uncovered"):
        audit_normalization("abc", normalized)


def test_audit_detects_wrong_fragment() -> None:
    normalized = NormalizedText(
        text="ab",
        runs=(SpanRun(0, 1, 0, 1, "a"), SpanRun(1, 2, 1, 2, "b")),
        edits=(dataclasses.replace(_record(), original_fragment="X"),),
    )
    with pytest.raises(NormalizationAuditError, match="fragment"):
        audit_normalization("ab\x00", normalized)


def test_audit_detects_non_monotonic_runs() -> None:
    normalized = NormalizedText(
        text="ab",
        runs=(
            SpanRun(0, 1, 1, 2, "a"),
            SpanRun(1, 2, 0, 1, "b"),
        ),
        edits=(),
    )
    with pytest.raises(NormalizationAuditError, match="monotonic"):
        audit_normalization("ab", normalized)


def test_audit_detects_bad_run_coverage() -> None:
    # normalized position 1 is not covered by any run (gap between 0-1 and 2-3)
    normalized = NormalizedText(
        text="ab",
        runs=(
            SpanRun(0, 1, 0, 1, "a"),
            SpanRun(2, 3, 1, 2, "b"),
        ),
        edits=(),
    )
    with pytest.raises(NormalizationAuditError, match="cover"):
        audit_normalization("ab", normalized)


def test_audit_detects_text_run_lineage_mismatch() -> None:
    # text says "aX" but the run lineage authoritatively says the second
    # character is "b": a tampered transformed character must be rejected.
    normalized = NormalizedText(
        text="aX",
        runs=(
            SpanRun(0, 1, 0, 1, "a"),
            SpanRun(1, 2, 1, 2, "b"),
        ),
        edits=(),
    )
    with pytest.raises(NormalizationAuditError, match="lineage"):
        audit_normalization("ab", normalized)


def test_span_run_rejects_fragment_length_mismatch() -> None:
    with pytest.raises(ValueError, match="normalized_fragment"):
        SpanRun(0, 2, 0, 2, "x")


# --- P3-N02 fix: policy identity must be uniquely traceable (Important #3) ---


def test_policy_fingerprint_is_stable_and_hex_sha256() -> None:
    policy = NormalizationPolicy()
    fingerprint = policy.fingerprint()
    assert fingerprint == policy.fingerprint()
    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)


def test_policy_fingerprint_changes_with_strip_html() -> None:
    base = NormalizationPolicy()
    changed = NormalizationPolicy(strip_html=True)
    assert base.fingerprint() != changed.fingerprint()


def test_policy_fingerprint_changes_with_max_body_length() -> None:
    base = NormalizationPolicy()
    changed = NormalizationPolicy(max_body_length=123)
    assert base.fingerprint() != changed.fingerprint()


def test_policy_fingerprint_changes_with_max_title_length() -> None:
    base = NormalizationPolicy()
    changed = NormalizationPolicy(max_title_length=42)
    assert base.fingerprint() != changed.fingerprint()


def test_policy_fingerprint_changes_with_recover_mojibake() -> None:
    base = NormalizationPolicy()
    changed = NormalizationPolicy(recover_mojibake=False)
    assert base.fingerprint() != changed.fingerprint()


def test_policy_fingerprint_changes_with_author_separators() -> None:
    base = NormalizationPolicy()
    changed = NormalizationPolicy(author_separators=(",",))
    assert base.fingerprint() != changed.fingerprint()


def test_different_policies_never_share_identity() -> None:
    seen: set[str] = set()
    for policy in (
        NormalizationPolicy(),
        NormalizationPolicy(strip_html=True),
        NormalizationPolicy(recover_mojibake=False),
        NormalizationPolicy(max_body_length=50),
        NormalizationPolicy(max_title_length=50),
        NormalizationPolicy(author_separators=(";",)),
    ):
        seen.add(policy.fingerprint())
    assert len(seen) == 6
