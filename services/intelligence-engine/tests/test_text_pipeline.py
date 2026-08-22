"""Text pipeline tests: BOM, newlines, NFC, controls, mojibake, whitespace,
truncation, offset mapping, audit and reversibility.

Every case asserts both the equivalence audit and exact reconstruction of the
original text from the public result (runs + edit records).
"""

from __future__ import annotations

from typing import cast

import pytest
from intelligence_engine.normalize import (
    NormalizationAuditError,
    NormalizedText,
    Operation,
    Reason,
    UnrecoverableTextError,
    audit_faithful_normalization,
    audit_normalization,
    detect_suspected_mojibake,
    is_fully_recoverable_mojibake,
    normalize_text,
    restore_original,
)


def _checked(
    original: str,
    *,
    strip_html: bool = False,
    max_length: int | None = None,
    recover_mojibake: bool = True,
) -> NormalizedText:
    result = normalize_text(
        original,
        strip_html=strip_html,
        max_length=max_length,
        recover_mojibake=recover_mojibake,
    )
    audit_normalization(original, result)
    assert restore_original(result, len(original)) == original
    return result


def test_plain_text_is_stable() -> None:
    result = _checked("plain text stays")
    assert result.text == "plain text stays"
    assert result.edits == ()


def test_utf8_bom_is_removed_and_recorded() -> None:
    result = _checked("\ufeffhello")
    assert result.text == "hello"
    assert len(result.edits) == 1
    edit = result.edits[0]
    assert edit.operation == Operation.REMOVE_BOM
    assert (edit.original_start, edit.original_end) == (0, 1)
    assert edit.original_fragment == "\ufeff"
    assert edit.reason == Reason.UTF8_BOM_PREFIX


def test_crlf_and_cr_become_lf() -> None:
    result = _checked("a\r\nb\rc\nd")
    assert result.text == "a\nb\nc\nd"
    ops = [(e.original_start, e.original_end, e.replacement_fragment) for e in result.edits]
    assert (1, 3, "\n") in ops
    assert (4, 5, "\n") in ops


def test_lf_char_maps_back_to_full_crlf_span() -> None:
    result = _checked("a\r\nb")
    # normalized 'a\nb': the LF at position 1 came from original [1, 3)
    assert result.original_range(1, 2) == (1, 3)


def test_nfc_composition_is_recorded() -> None:
    result = _checked("e\u0301tude")
    assert result.text == "étude"
    edit = result.edits[0]
    assert edit.operation == Operation.UNICODE_NFC
    assert edit.original_fragment == "e\u0301"
    assert edit.replacement_fragment == "é"
    assert result.original_range(0, 1) == (0, 2)


def test_nfc_hangul_jamo_composition() -> None:
    result = _checked("\u1100\u1161")
    assert result.text == "가"


def test_already_composed_text_has_no_nfc_edits() -> None:
    result = _checked("é가中")
    assert result.text == "é가中"
    assert result.edits == ()


def test_control_characters_are_removed_with_evidence() -> None:
    result = _checked("a\x00b\x7f\u000bc")
    assert result.text == "abc"
    frags = [e.original_fragment for e in result.edits]
    assert "\x00" in frags
    assert "\x7f" in frags
    assert "\u000b" in frags
    assert all(e.operation == Operation.REMOVE_CONTROL for e in result.edits)


def test_tab_and_newline_are_preserved() -> None:
    result = _checked("a\tb\nc")
    assert result.text == "a\tb\nc"


def test_zero_width_joiner_is_preserved_for_emoji() -> None:
    family = "👨‍👩‍👧"
    result = _checked(f"a{family}b")
    assert family in result.text


def test_zero_width_space_is_removed() -> None:
    result = _checked("a\u200bb")
    assert result.text == "ab"


def test_whitespace_runs_collapse() -> None:
    result = _checked("a    b")
    assert result.text == "a b"
    assert result.edits[0].operation == Operation.WHITESPACE_COLLAPSE
    assert result.edits[0].original_fragment == "    "
    assert result.edits[0].replacement_fragment == " "


def test_spaces_adjacent_to_newlines_are_removed() -> None:
    result = _checked("a \n b")
    assert result.text == "a\nb"


def test_newline_runs_collapse_to_paragraph_boundary() -> None:
    result = _checked("a\n\n\n\nb")
    assert result.text == "a\n\nb"


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    result = _checked("  \n a b \n\t ")
    assert result.text == "a b"


def test_multi_byte_cjk_and_emoji_offsets_are_exact() -> None:
    original = "中文👨‍👩‍👧tail"
    result = _checked(original)
    tail_start = result.text.index("tail")
    assert result.original_range(tail_start, tail_start + 4) == (7, 11)


def test_mojibake_is_recovered_deterministically() -> None:
    mojibake = "中文新闻".encode().decode("latin-1")
    result = _checked(mojibake)
    assert result.text == "中文新闻"
    edit = result.edits[0]
    assert edit.operation == Operation.MOJIBAKE_RECOVER
    assert edit.original_fragment == mojibake
    assert edit.replacement_fragment == "中文新闻"
    assert (edit.original_start, edit.original_end) == (0, len(mojibake))


def test_mojibake_with_newline_is_recovered() -> None:
    mojibake = "标题\n".encode().decode("latin-1")
    # the trailing newline is trimmed by the whitespace policy
    result = _checked(mojibake)
    assert result.text == "标题"


def test_replacement_char_is_unrecoverable() -> None:
    with pytest.raises(UnrecoverableTextError):
        normalize_text("broken \ufffd text")


def test_mojibake_recovery_can_be_disabled() -> None:
    mojibake = "中文".encode().decode("latin-1")
    result = _checked(mojibake, recover_mojibake=False)
    # unrecovered mojibake is left alone (C1/Cf characters are still removed
    # by the control policy, but no recovery is attempted)
    assert "中文" not in result.text
    assert all(e.operation != Operation.MOJIBAKE_RECOVER for e in result.edits)


def test_partial_mojibake_is_left_untouched() -> None:
    # mixed genuine text + mojibake cannot round-trip as a whole -> untouched
    mixed = "genuine é " + "中文".encode().decode("latin-1")
    result = _checked(mixed)
    assert "中文" not in result.text
    assert all(e.operation != Operation.MOJIBAKE_RECOVER for e in result.edits)


def test_truncation_at_exact_limit_is_noop() -> None:
    result = _checked("x" * 10, max_length=10)
    assert result.text == "x" * 10
    assert all(e.operation != Operation.TRUNCATE for e in result.edits)


def test_truncation_one_over_limit() -> None:
    result = _checked("x" * 11, max_length=10)
    assert result.text == "x" * 10
    truncate_edits = [e for e in result.edits if e.operation == Operation.TRUNCATE]
    assert len(truncate_edits) == 1
    edit = truncate_edits[0]
    assert edit.original_fragment == "x"
    assert (edit.original_start, edit.original_end) == (10, 11)


def test_truncation_far_over_limit_records_full_tail() -> None:
    result = _checked("x" * 1000, max_length=10)
    assert result.text == "x" * 10
    edit = next(e for e in result.edits if e.operation == Operation.TRUNCATE)
    assert edit.original_fragment == "x" * 990
    assert (edit.original_start, edit.original_end) == (10, 1000)


def test_normalization_is_idempotent() -> None:
    once = normalize_text("  a\r\n \u200bb&nbsp;  c  ")
    twice = normalize_text(once.text)
    assert twice.text == once.text
    assert twice.edits == ()


def test_same_input_same_result() -> None:
    original = "a\r\n b \x00 中文"
    assert normalize_text(original) == normalize_text(original)


def test_empty_string_normalizes_to_empty() -> None:
    result = _checked("")
    assert result.text == ""
    assert result.edits == ()


def test_audit_detects_tampered_text() -> None:
    result = normalize_text("a\r\nb")
    tampered = type(result)(
        text="X\nb",
        runs=result.runs,
        edits=result.edits,
    )
    with pytest.raises(NormalizationAuditError):
        audit_normalization("a\r\nb", tampered)


def test_non_string_input_rejected() -> None:
    with pytest.raises(TypeError):
        normalize_text(cast(str, b"bytes not allowed"))


# --- P3-N02 fix: BOM + mojibake cross-stage offset fidelity (Critical #1) ---


def test_bom_then_recoverable_mojibake_offsets() -> None:
    original = "\ufeff" + "中文".encode().decode("latin-1")
    result = _checked(original)
    assert result.text == "中文"
    # BOM must still map to original position 0; recovered characters must map
    # into the original latin-1 bytes that followed the BOM, never to offset 0.
    assert restore_original(result, len(original)) == original


def test_bom_mojibake_crlf_offsets() -> None:
    original = "\ufeff" + "标题\r\n正文".encode().decode("latin-1")
    result = _checked(original)
    assert result.text == "标题\n正文"
    assert restore_original(result, len(original)) == original


def test_bom_cjk_and_emoji_offsets() -> None:
    original = "\ufeff" + "中文🚀".encode().decode("latin-1")
    result = _checked(original)
    assert result.text == "中文🚀"
    assert restore_original(result, len(original)) == original


def test_bom_mojibake_original_range_points_at_real_positions() -> None:
    original = "\ufeff" + "中文".encode().decode("latin-1")
    result = _checked(original)
    # every normalized position must map back into a non-BOM original span
    # (the BOM occupied original offset 0 and was removed).
    for position in range(len(result.text)):
        os, oe = result.original_range(position, position + 1)
        assert 1 <= os < oe <= len(original)


def test_bom_mojibake_runs_cover_all_original_positions() -> None:
    original = "\ufeff" + "中文新闻".encode().decode("latin-1")
    result = _checked(original)
    covered: set[int] = set()
    for edit in result.edits:
        covered.update(range(edit.original_start, edit.original_end))
    for run in result.runs:
        if run.normalized_end - run.normalized_start == run.original_end - run.original_start:
            covered.update(range(run.original_start, run.original_end))
    assert covered == set(range(len(original)))


# --- P3-N02 fix: audit must detect tampering of transformed characters (Critical #2) ---


def test_audit_detects_tampered_nfc_character() -> None:
    original = "e\u0301"  # e + combining acute -> é
    result = normalize_text(original)
    assert result.text == "\u00e9"
    tampered = type(result)(text="z", runs=result.runs, edits=result.edits)
    with pytest.raises(NormalizationAuditError):
        audit_normalization(original, tampered)


def test_audit_detects_tampered_crlf_newline() -> None:
    original = "a\r\nb"
    result = normalize_text(original)
    assert result.text == "a\nb"
    tampered = type(result)(text="aXb", runs=result.runs, edits=result.edits)
    with pytest.raises(NormalizationAuditError):
        audit_normalization(original, tampered)


def test_audit_detects_tampered_mojibake_character() -> None:
    original = "中文".encode().decode("latin-1")
    result = normalize_text(original)
    assert result.text == "中文"
    tampered = type(result)(text="日文", runs=result.runs, edits=result.edits)
    with pytest.raises(NormalizationAuditError):
        audit_normalization(original, tampered)


def test_audit_detects_tampered_collapsed_space() -> None:
    original = "a   b"
    result = normalize_text(original)
    assert result.text == "a b"
    tampered = type(result)(text="a_b", runs=result.runs, edits=result.edits)
    with pytest.raises(NormalizationAuditError):
        audit_normalization(original, tampered)


# --- P3-N02 round-2 fix: audit must survive self-consistent text+run tampering ---
# The trusted root is an INDEPENDENT REPLAY from the original + trusted policy,
# not any field of the untrusted result. An attacker who rewrites both
# ``text`` and the matching ``run.normalized_fragment`` (and any digest) keeps
# the result internally consistent, so only a replay-based audit catches it.


def _forge(original: str, forged_text: str, **params: object) -> NormalizedText:
    """Return a self-consistent forgery of ``normalize_text(original)``.

    ``forged_text`` must have the same length as the genuine normalized text.
    Every run's ``normalized_fragment`` is rewritten to match ``forged_text``
    so the internal ``text[span] == fragment`` check passes; original spans and
    edits are preserved. This models an attacker with full write access to the
    result object.
    """
    genuine = normalize_text(
        original,
        strip_html=cast(bool, params.get("strip_html", False)),
        max_length=cast("int | None", params.get("max_length")),
        recover_mojibake=cast(bool, params.get("recover_mojibake", True)),
    )
    assert len(forged_text) == len(genuine.text)
    forged_runs = tuple(
        type(run)(
            run.normalized_start,
            run.normalized_end,
            run.original_start,
            run.original_end,
            forged_text[run.normalized_start : run.normalized_end],
        )
        for run in genuine.runs
    )
    return type(genuine)(text=forged_text, runs=forged_runs, edits=genuine.edits)


def test_replay_audit_detects_self_consistent_nfc_tamper() -> None:
    original = "e\u0301"  # -> é
    forged = _forge(original, "X")
    audit_normalization(original, forged)  # legacy structural audit is fooled
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged)


def test_replay_audit_detects_self_consistent_entity_tamper() -> None:
    original = "A&amp;B"
    forged = _forge(original, "A#B", strip_html=True)
    audit_normalization(original, forged)
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged, strip_html=True)


def test_replay_audit_detects_self_consistent_crlf_tamper() -> None:
    original = "a\r\nb"
    forged = _forge(original, "aXb")
    audit_normalization(original, forged)
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged)


def test_replay_audit_detects_self_consistent_mojibake_tamper() -> None:
    original = "中文".encode().decode("latin-1")
    forged = _forge(original, "日文")
    audit_normalization(original, forged)
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged)


def test_replay_audit_detects_self_consistent_collapsed_space_tamper() -> None:
    original = "a   b"
    forged = _forge(original, "a_b")
    audit_normalization(original, forged)
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged)


def test_replay_audit_detects_structural_edit_tamper() -> None:
    original = "a\x00b"
    genuine = normalize_text(original)
    # forge a plausible-but-false edit replacement while keeping text intact
    forged_edits = tuple(
        type(edit)(
            operation=edit.operation,
            original_start=edit.original_start,
            original_end=edit.original_end,
            normalized_start=edit.normalized_start,
            normalized_end=edit.normalized_end,
            original_fragment=edit.original_fragment,
            replacement_fragment="TAMPERED",
            reason=edit.reason,
            normalization_version=edit.normalization_version,
        )
        for edit in genuine.edits
    )
    forged = type(genuine)(text=genuine.text, runs=genuine.runs, edits=forged_edits)
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, forged)


def test_replay_audit_detects_policy_mismatch() -> None:
    original = "<b>hi</b>"
    genuine = normalize_text(original, strip_html=True)
    # audited under the wrong policy (strip_html=False) -> replay differs
    with pytest.raises(NormalizationAuditError):
        audit_faithful_normalization(original, genuine, strip_html=False)


def test_replay_audit_passes_for_genuine_result() -> None:
    cases: list[tuple[str, bool]] = [
        ("e\u0301", False),
        ("A&amp;B", True),
        ("a\r\nb", False),
        ("中文".encode().decode("latin-1"), False),
        ("a   b", False),
        ("\ufeff中文".encode().decode("latin-1"), False),  # BOM + mojibake cross-stage
    ]
    for original, strip_html in cases:
        genuine = normalize_text(original, strip_html=strip_html)
        audit_faithful_normalization(original, genuine, strip_html=strip_html)
        assert restore_original(genuine, len(original)) == original


# --- P3-N02 fix: mojibake evidence detection (Important #4) ---


def test_detect_flags_pure_mojibake() -> None:
    assert detect_suspected_mojibake("中文".encode().decode("latin-1")) is True


def test_detect_flags_mixed_mojibake() -> None:
    assert detect_suspected_mojibake("报道：" + "中文".encode().decode("latin-1")) is True


def test_detect_does_not_flag_plain_cjk() -> None:
    assert detect_suspected_mojibake("正常中文内容") is False


def test_detect_does_not_flag_plain_ascii() -> None:
    assert detect_suspected_mojibake("plain english text 12345") is False


def test_detect_does_not_flag_french_accents() -> None:
    for text in ("café", "déjà vu", "résumé", "naïve", "Zoë"):
        assert detect_suspected_mojibake(text) is False, text


def test_detect_does_not_flag_emoji() -> None:
    assert detect_suspected_mojibake("launch 🚀 today") is False


def test_fully_recoverable_detection() -> None:
    assert is_fully_recoverable_mojibake("中文新闻".encode().decode("latin-1")) is True
    assert is_fully_recoverable_mojibake("正常中文") is False
    assert is_fully_recoverable_mojibake("café") is False


# --- P3-N02 round-2 fix: detect common partial mojibake like cafÃ© (Important #3) ---


def test_detect_flags_partial_bmp_mojibake_cafe() -> None:
    # "café" UTF-8 bytes decoded as latin-1 -> "cafÃ©"; the é is < U+0100 so the
    # old >0xFF filter missed it. It must now be detected.
    assert "café".encode().decode("latin-1") == "cafÃ©"
    assert detect_suspected_mojibake("cafÃ©") is True


def test_detect_flags_partial_mojibake_in_context() -> None:
    assert detect_suspected_mojibake("中文 cafÃ©") is True
    assert detect_suspected_mojibake("prefix cafÃ© suffix") is True


def test_detect_does_not_flag_genuine_bmp_accents() -> None:
    # genuine accented text must not be mistaken for mojibake
    for text in ("café", "résumé", "français", "中文 café", "naïve", "Zoë", "déjà"):
        assert detect_suspected_mojibake(text) is False, text


def test_detect_does_not_flag_single_accent() -> None:
    for text in ("é", "à", "ü", "ñ", "ç"):
        assert detect_suspected_mojibake(text) is False, text
