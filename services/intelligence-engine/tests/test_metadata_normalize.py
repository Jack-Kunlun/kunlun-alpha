"""Metadata normalization tests: times, authors, attachments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from intelligence_engine.normalize import (
    AttachmentInput,
    AttachmentStatus,
    AuthorInput,
    NormalizedAuthors,
    has_usable_attachment,
    normalize_attachments,
    normalize_authors,
    normalize_times,
)

_CST = timezone(timedelta(hours=8))


def _aware(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


class TestTimes:
    def test_times_are_normalized_to_utc(self) -> None:
        publish = datetime(2026, 8, 1, 9, 30, tzinfo=_CST)
        ingest = datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
        available = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
        times = normalize_times(publish, ingest, available)
        assert times.publish_time == datetime(2026, 8, 1, 1, 30, tzinfo=UTC)
        assert times.ingest_time.tzinfo is UTC
        assert times.available_time.tzinfo is UTC

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            normalize_times(datetime(2026, 8, 1), _aware(2026, 8, 2), _aware(2026, 8, 3))

    def test_non_datetime_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            normalize_times(cast(datetime, "2026-08-01"), _aware(2026, 8, 2), _aware(2026, 8, 3))

    def test_ordering_is_enforced(self) -> None:
        with pytest.raises(ValueError, match="publish_time"):
            normalize_times(_aware(2026, 8, 3), _aware(2026, 8, 2), _aware(2026, 8, 1))

    def test_equal_instants_in_different_zones_are_identical(self) -> None:
        cst = datetime(2026, 8, 1, 16, 0, tzinfo=_CST)
        utc = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
        a = normalize_times(cst, cst, cst)
        b = normalize_times(utc, utc, utc)
        assert a == b


class TestAuthors:
    def test_plain_authors_pass_through(self) -> None:
        result = normalize_authors(["张三", "李四"], separators=(",", ";"))
        assert result.normalized[0].normalized_name == "张三"
        assert result.normalized[1].normalized_name == "李四"

    def test_original_author_text_is_preserved(self) -> None:
        result = normalize_authors(["  王五  "], separators=(",", ";"))
        assert result.original_authors == ("  王五  ",)
        assert result.normalized[0].original_name == "  王五  "
        assert result.normalized[0].normalized_name == "王五"

    def test_internal_whitespace_is_collapsed(self) -> None:
        result = normalize_authors(["John   Smith"], separators=(",", ";"))
        assert result.normalized[0].normalized_name == "John Smith"

    def test_separators_are_split(self) -> None:
        result = normalize_authors(["张三, 李四；王五"], separators=(",", "；"))
        names = [a.normalized_name for a in result.normalized]
        assert names == ["张三", "李四", "王五"]

    def test_duplicates_are_removed_in_stable_order(self) -> None:
        result = normalize_authors(["张三", " 李四 ", "张三", "李四"], separators=(",", ";"))
        names = [a.normalized_name for a in result.normalized]
        assert names == ["张三", "李四"]

    def test_author_input_objects_are_accepted(self) -> None:
        result = normalize_authors([AuthorInput(name="赵六")], separators=(",", ";"))
        assert result.normalized[0].normalized_name == "赵六"

    def test_empty_and_blank_authors_are_dropped(self) -> None:
        result = normalize_authors(["", "   ", None], separators=(",", ";"))
        assert result.normalized == ()

    def test_no_identity_guessing(self) -> None:
        # the result carries names only: no org/person classification fields
        result = normalize_authors(["中信证券"], separators=(",", ";"))
        author = result.normalized[0]
        assert not hasattr(author, "is_organization")
        assert not hasattr(author, "person_id")

    def test_result_is_deterministic(self) -> None:
        a = normalize_authors(["a, b", " a"], separators=(",", ";"))
        b = normalize_authors(["a, b", " a"], separators=(",", ";"))
        assert a == b

    def test_empty_authors(self) -> None:
        assert normalize_authors([], separators=(",", ";")) == NormalizedAuthors((), ())


class TestAttachments:
    def test_attachment_metadata_is_preserved(self) -> None:
        att = AttachmentInput(
            uri="https://example.com/a.pdf",
            filename="a.pdf",
            mime_type="application/pdf",
            position=42,
        )
        (normalized,) = normalize_attachments([att])
        assert normalized.original_uri == "https://example.com/a.pdf"
        assert normalized.original_filename == "a.pdf"
        assert normalized.declared_mime_type == "application/pdf"
        assert normalized.original_position == 42
        assert normalized.status == AttachmentStatus.OK

    def test_attachment_metadata_is_deterministic_and_normalized(self) -> None:
        att = AttachmentInput(
            uri="  https://example.com/a.pdf  ",
            filename="  A.PDF  ",
            mime_type="  Application/PDF  ",
        )
        (normalized,) = normalize_attachments([att])
        assert normalized.normalized_uri == "https://example.com/a.pdf"
        assert normalized.normalized_filename == "A.PDF"
        assert normalized.normalized_mime_type == "application/pdf"
        (again,) = normalize_attachments([att])
        assert again == normalized
        assert normalized.attachment_id == again.attachment_id

    def test_duplicate_attachments_are_flagged(self) -> None:
        first = AttachmentInput(
            uri="https://example.com/a.pdf", filename="a.pdf", mime_type="application/pdf"
        )
        second = AttachmentInput(
            uri="https://example.com/a.pdf ", filename="b.pdf", mime_type="application/pdf"
        )
        results = normalize_attachments([first, second])
        assert results[0].status == AttachmentStatus.OK
        assert results[1].status == AttachmentStatus.DUPLICATE

    def test_empty_uri_is_invalid(self) -> None:
        (normalized,) = normalize_attachments([AttachmentInput(uri="   ")])
        assert normalized.status == AttachmentStatus.INVALID_URI

    def test_missing_metadata_is_flagged(self) -> None:
        (normalized,) = normalize_attachments([AttachmentInput(uri="https://example.com/a.pdf")])
        assert normalized.status == AttachmentStatus.MISSING_METADATA

    def test_unsupported_scheme_is_flagged(self) -> None:
        (normalized,) = normalize_attachments(
            [AttachmentInput(uri="mailto:x@example.com", filename="x", mime_type="text/plain")]
        )
        assert normalized.status == AttachmentStatus.UNSUPPORTED_SCHEME

    def test_relative_uri_is_ok(self) -> None:
        (normalized,) = normalize_attachments(
            [
                AttachmentInput(
                    uri="files/report.pdf", filename="report.pdf", mime_type="application/pdf"
                )
            ]
        )
        assert normalized.status == AttachmentStatus.OK

    def test_attachment_uri_must_be_string(self) -> None:
        with pytest.raises(TypeError):
            normalize_attachments([AttachmentInput(uri=cast(str, 123))])

    def test_no_download_or_parsing_side_effects(self) -> None:
        # normalization is pure metadata work: same input, same output, no I/O
        att = AttachmentInput(
            uri="https://example.com/x.bin", filename="x.bin", mime_type="application/octet-stream"
        )
        assert normalize_attachments([att]) == normalize_attachments([att])


class TestUsableAttachment:
    def _ok(self) -> AttachmentInput:
        return AttachmentInput(
            uri="https://example.com/a.pdf", filename="a.pdf", mime_type="application/pdf"
        )

    def test_ok_attachment_is_usable(self) -> None:
        assert has_usable_attachment(normalize_attachments([self._ok()])) is True

    def test_invalid_uri_is_not_usable(self) -> None:
        assert has_usable_attachment(normalize_attachments([AttachmentInput(uri="   ")])) is False

    def test_missing_metadata_is_not_usable(self) -> None:
        result = normalize_attachments([AttachmentInput(uri="https://example.com/a.pdf")])
        assert has_usable_attachment(result) is False

    def test_unsupported_scheme_is_not_usable(self) -> None:
        result = normalize_attachments(
            [AttachmentInput(uri="mailto:x@example.com", filename="x", mime_type="text/plain")]
        )
        assert has_usable_attachment(result) is False

    def test_only_duplicates_are_not_usable(self) -> None:
        result = normalize_attachments(
            [
                AttachmentInput(uri="https://example.com/a.pdf"),  # missing metadata
                AttachmentInput(uri="https://example.com/a.pdf"),  # duplicate
            ]
        )
        assert has_usable_attachment(result) is False

    def test_invalid_plus_ok_is_usable(self) -> None:
        result = normalize_attachments([AttachmentInput(uri="   "), self._ok()])
        assert has_usable_attachment(result) is True

    def test_empty_sequence_is_not_usable(self) -> None:
        assert has_usable_attachment(()) is False
