"""HTML normalization tests: entities, tags, invisible content, offsets.

All cases run the full equivalence audit and exact original reconstruction.
"""

from __future__ import annotations

from intelligence_engine.normalize import (
    NormalizedText,
    Operation,
    Reason,
    audit_normalization,
    normalize_text,
    restore_original,
)


def _checked(original: str) -> NormalizedText:
    result = normalize_text(original, strip_html=True)
    audit_normalization(original, result)
    assert restore_original(result, len(original)) == original
    return result


def test_simple_html_yields_plain_text() -> None:
    result = _checked("<p>Hello <b>world</b></p>")
    assert result.text == "Hello world"


def test_entities_are_decoded() -> None:
    result = _checked("A &amp; B &lt;x&gt;")
    assert result.text == "A & B <x>"


def test_entity_expansion_changes_length_and_maps_span() -> None:
    result = _checked("x&quot;y")
    assert result.text == 'x"y'
    edit = result.edits[0]
    assert edit.operation == Operation.HTML_ENTITY
    assert edit.reason == Reason.HTML_ENTITY_DECODED
    assert (edit.original_start, edit.original_end) == (1, 7)
    assert edit.original_fragment == "&quot;"
    assert edit.replacement_fragment == '"'
    # the single normalized '"' traces back to the full original entity span
    assert result.original_range(1, 2) == (1, 7)


def test_numeric_charrefs_are_decoded() -> None:
    result = _checked("&#65;&#x42;")
    assert result.text == "AB"


def test_unknown_entity_is_kept_verbatim() -> None:
    result = _checked("a &zzznotreal; b")
    assert "&zzznotreal;" in result.text
    assert all(e.operation != Operation.HTML_ENTITY for e in result.edits)


def test_script_and_style_content_is_excluded() -> None:
    result = _checked("<p>a</p><script>var x=1;</script><style>.c{color:red}</style><p>b</p>")
    assert result.text == "a\n\nb"
    invisible = [e for e in result.edits if e.operation == Operation.HTML_INVISIBLE_STRIP]
    frags = {e.original_fragment for e in invisible}
    assert "var x=1;" in frags
    assert ".c{color:red}" in frags


def test_script_content_offset_is_recorded() -> None:
    original = "aa<script>secret</script>bb"
    result = _checked(original)
    edit = next(e for e in result.edits if e.operation == Operation.HTML_INVISIBLE_STRIP)
    assert edit.original_fragment == "secret"
    assert original[edit.original_start : edit.original_end] == "secret"


def test_comments_are_removed_with_evidence() -> None:
    result = _checked("a<!-- hidden note -->b")
    assert result.text == "ab"
    comment = [e for e in result.edits if e.reason == Reason.HTML_COMMENT_REMOVED]
    assert len(comment) == 1


def test_br_becomes_single_newline() -> None:
    result = _checked("a<br>b")
    assert result.text == "a\nb"


def test_paragraphs_keep_blank_line_boundary() -> None:
    result = _checked("<p>one</p><p>two</p>")
    assert result.text == "one\n\ntwo"


def test_full_document_only_body_text_survives() -> None:
    result = _checked(
        "<html><head><title>T</title><style>s</style></head><body><p>Body</p></body></html>"
    )
    assert result.text == "Body"


def test_html_only_invisible_content_normalizes_to_empty() -> None:
    result = _checked("<script>x</script>")
    assert result.text == ""


def test_deleted_tag_keeps_offset_evidence_for_following_text() -> None:
    original = "<b>bold</b>tail"
    result = _checked(original)
    tail_start = result.text.index("tail")
    # 'tail' sits at original offset 11..15 regardless of the removed tags
    assert result.original_range(tail_start, tail_start + 4) == (11, 15)


def test_tag_removal_edits_record_original_tag_text() -> None:
    original = "x<i>y</i>z"
    result = _checked(original)
    tag_edits = [e for e in result.edits if e.operation == Operation.HTML_TAG_STRIP]
    frags = {e.original_fragment for e in tag_edits}
    assert "<i>" in frags
    assert "</i>" in frags


def test_nested_tags_keep_working_offsets() -> None:
    original = "<div><p>a &amp; b</p></div>"
    result = _checked(original)
    assert result.text == "a & b"
    entity = next(e for e in result.edits if e.operation == Operation.HTML_ENTITY)
    assert original[entity.original_start : entity.original_end] == "&amp;"


def test_attribute_values_do_not_leak_into_text() -> None:
    result = _checked('<a href="http://evil.example/x" title="t">link</a>')
    assert result.text == "link"
    assert "http" not in result.text


def test_html_result_is_idempotent() -> None:
    once = normalize_text("<p>a &amp; b</p>", strip_html=True)
    twice = normalize_text(once.text)
    assert twice.text == once.text
    assert twice.edits == ()
