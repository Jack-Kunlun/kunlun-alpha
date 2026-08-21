"""RawContent contract tests (P3-N01).

A unified, immutable, versioned raw content contract for news, announcements,
research, interactive and social content. Covers deterministic fingerprinting,
duplicate-URL traceability, repost provenance, non-overwriting updates,
deletion that preserves evidence, time-zone / time-order validation, and
fail-closed rejection of empty source / evidence / license and invalid content
types.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from event_core.content import (
    FINGERPRINT_ALGORITHM_VERSION,
    ContentSource,
    ContentType,
    LicenseMetadata,
    RawContent,
    content_fingerprint,
    mark_deleted,
    updated_content,
)


def _source(source_id: str = "cninfo", evidence_id: str = "evt-001") -> ContentSource:
    return ContentSource(source_id=source_id, source_version="v1", evidence_id=evidence_id)


def _license() -> LicenseMetadata:
    return LicenseMetadata(
        license_id="COMMERCIAL", usage_restriction="internal-only", authorized=True
    )


def _content(
    *,
    url: str = "https://example.com/news/1",
    title: str = "标题",
    body: str = "正文",
    publish_time: datetime = datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
    ingest_time: datetime = datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
    content_type: ContentType = "NEWS",
    source: ContentSource | None = None,
    license: LicenseMetadata | None = None,
    original_source: ContentSource | None = None,
    deleted: bool = False,
    deleted_at: datetime | None = None,
) -> RawContent:
    return RawContent(
        content_type=content_type,
        source=source or _source(),
        url=url,
        title=title,
        body=body,
        publish_time=publish_time,
        ingest_time=ingest_time,
        license=license or _license(),
        original_source=original_source,
        deleted=deleted,
        deleted_at=deleted_at,
    )


# --- deterministic fingerprint ----------------------------------------------


def test_content_fingerprint_is_deterministic() -> None:
    a = content_fingerprint("标题", "正文")
    b = content_fingerprint("标题", "正文")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 64  # sha256 hex


def test_content_fingerprint_differs_for_different_content() -> None:
    assert content_fingerprint("标题A", "正文") != content_fingerprint("标题B", "正文")
    assert content_fingerprint("标题", "正文A") != content_fingerprint("标题", "正文B")


def test_raw_content_carries_fingerprint_and_algorithm_version() -> None:
    c = _content()
    assert c.fingerprint == content_fingerprint("标题", "正文")
    assert c.fingerprint_algorithm_version == FINGERPRINT_ALGORITHM_VERSION


# --- duplicate URL ----------------------------------------------------------


def test_duplicate_url_is_stable_and_traceable() -> None:
    url = "https://example.com/news/1"
    first = _content(url=url, ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC))
    second = _content(url=url, ingest_time=datetime(2026, 8, 21, 2, 5, tzinfo=UTC))

    # Same URL, same content -> same fingerprint; each ingest is an independent,
    # immutable record distinguished by its ingest_time.
    assert first.url == second.url == url
    assert first.fingerprint == second.fingerprint
    assert first.ingest_time != second.ingest_time


# --- repost provenance ------------------------------------------------------


def test_repost_preserves_current_and_original_source() -> None:
    original = _source(source_id="xinhua", evidence_id="evt-orig")
    repost = _content(
        url="https://repost.example.com/news/1",
        source=_source(source_id="repost-site", evidence_id="evt-repost"),
        original_source=original,
    )
    assert repost.source.source_id == "repost-site"
    assert repost.original_source is not None
    assert repost.original_source.source_id == "xinhua"
    assert repost.original_source.evidence_id == "evt-orig"


# --- update does not overwrite ----------------------------------------------


def test_update_does_not_overwrite_old_version() -> None:
    old = _content(title="旧标题", body="旧正文")
    new = updated_content(
        old,
        title="新标题",
        body="新正文",
        publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )

    # The old version is unchanged (immutable) and the new version links back.
    assert old.title == "旧标题"
    assert old.fingerprint == content_fingerprint("旧标题", "旧正文")
    assert new.title == "新标题"
    assert new.previous_fingerprint == old.fingerprint
    assert new.fingerprint != old.fingerprint


# --- deletion preserves evidence --------------------------------------------


def test_deletion_preserves_source_license_and_evidence() -> None:
    original = _content(
        source=_source(source_id="cninfo", evidence_id="evt-keep"),
        license=_license(),
    )
    deleted = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))

    assert deleted.deleted is True
    assert deleted.deleted_at is not None
    # Source, license and evidence survive deletion — nothing is physically erased.
    assert deleted.source == original.source
    assert deleted.license == original.license
    assert deleted.fingerprint == original.fingerprint
    assert deleted.url == original.url
    # The original record is unchanged.
    assert original.deleted is False


# --- time-zone and time-order invariants ------------------------------------


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _content(publish_time=datetime(2026, 8, 21, 1, 0))  # naive


def test_publish_time_after_ingest_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="publish_time"):
        _content(
            publish_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        )


def test_non_utc_aware_datetime_is_accepted() -> None:
    east8 = timezone(timedelta(hours=8))
    c = _content(
        publish_time=datetime(2026, 8, 21, 9, 0, tzinfo=east8),  # 01:00 UTC
        ingest_time=datetime(2026, 8, 21, 9, 5, tzinfo=east8),
    )
    assert c.publish_time == datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


# --- fail-closed on empty / invalid provenance ------------------------------


def test_empty_source_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="source"):
        _content(source=ContentSource(source_id="", source_version="v1", evidence_id="evt-001"))


def test_empty_evidence_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence"):
        _content(source=ContentSource(source_id="cninfo", source_version="v1", evidence_id=""))


def test_empty_license_is_rejected() -> None:
    with pytest.raises(ValueError, match="license"):
        _content(license=LicenseMetadata(license_id="", usage_restriction="internal-only"))


def test_empty_usage_restriction_is_rejected() -> None:
    with pytest.raises(ValueError, match="usage"):
        _content(license=LicenseMetadata(license_id="COMMERCIAL", usage_restriction=""))


def test_invalid_content_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="content_type"):
        _content(content_type="BLOG")  # type: ignore[arg-type]


def test_empty_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="url"):
        _content(url="")


# --- deletion state constraints ---------------------------------------------


def test_deleted_requires_deleted_at() -> None:
    with pytest.raises(ValueError, match="deleted"):
        RawContent(
            content_type="NEWS",
            source=_source(),
            url="https://example.com/news/1",
            title="标题",
            body="正文",
            publish_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
            license=_license(),
            deleted=True,
            deleted_at=None,
        )


def test_non_deleted_rejects_deleted_at() -> None:
    with pytest.raises(ValueError, match="deleted"):
        _content(deleted=False, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
