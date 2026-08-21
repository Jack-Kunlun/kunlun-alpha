"""RawContent domain tests (P3-N01).

Covers the point-in-time ``available_time`` invariant, fail-closed
authorization, deterministic fingerprinting, duplicate-URL traceability, repost
provenance, version / deletion audit chains and rejection of empty or invalid
provenance.
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


def _license(authorized: bool = True) -> LicenseMetadata:
    return LicenseMetadata(
        license_id="COMMERCIAL", usage_restriction="internal-only", authorized=authorized
    )


def _content(
    *,
    url: str = "https://example.com/news/1",
    title: str = "标题",
    body: str = "正文",
    publish_time: datetime = datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
    ingest_time: datetime = datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
    available_time: datetime | None = None,
    content_type: ContentType = "NEWS",
    source: ContentSource | None = None,
    license: LicenseMetadata | None = None,
    original_source: ContentSource | None = None,
    record_id: str = "rec-1",
    previous_version_id: str | None = None,
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
        available_time=available_time or ingest_time,
        license=license or _license(),
        record_id=record_id,
        original_source=original_source,
        previous_version_id=previous_version_id,
        deleted=deleted,
        deleted_at=deleted_at,
    )


# --- deterministic fingerprint ----------------------------------------------


def test_content_fingerprint_is_deterministic() -> None:
    a = content_fingerprint("标题", "正文")
    b = content_fingerprint("标题", "正文")
    assert a == b
    assert len(a) == 64
    assert a == a.lower()
    assert all(c in "0123456789abcdef" for c in a)


def test_content_fingerprint_differs_for_different_content() -> None:
    assert content_fingerprint("标题A", "正文") != content_fingerprint("标题B", "正文")
    assert content_fingerprint("标题", "正文A") != content_fingerprint("标题", "正文B")


def test_raw_content_carries_fingerprint_and_algorithm_version() -> None:
    c = _content()
    assert c.fingerprint == content_fingerprint("标题", "正文")
    assert c.fingerprint_algorithm_version == FINGERPRINT_ALGORITHM_VERSION
    assert c.fingerprint_algorithm_version == "sha256-v1"


# --- available_time invariant (C1) ------------------------------------------


def test_naive_available_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _content(available_time=datetime(2026, 8, 21, 1, 5))  # naive


def test_ingest_after_available_is_rejected() -> None:
    with pytest.raises(ValueError, match="ingest_time"):
        _content(
            ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
            available_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        )


def test_publish_after_ingest_is_rejected() -> None:
    with pytest.raises(ValueError, match="publish_time"):
        _content(
            publish_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        )


def test_not_available_before_available_time() -> None:
    c = _content(available_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC))
    before = datetime(2026, 8, 21, 1, 59, tzinfo=UTC)
    assert c.available_at(before) is False
    # inclusive boundary
    assert c.available_at(datetime(2026, 8, 21, 2, 0, tzinfo=UTC)) is True


def test_ingest_equals_available_passes() -> None:
    c = _content(
        ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
    )
    assert c.ingest_time == c.available_time


# --- authorization fail-closed (C2) -----------------------------------------


def test_missing_authorized_is_rejected() -> None:
    with pytest.raises(TypeError):
        LicenseMetadata(license_id="COMMERCIAL", usage_restriction="internal-only")  # type: ignore[call-arg]


def test_non_bool_authorized_is_rejected() -> None:
    with pytest.raises(TypeError):
        LicenseMetadata(
            license_id="COMMERCIAL",
            usage_restriction="internal-only",
            authorized=1,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        LicenseMetadata(
            license_id="COMMERCIAL",
            usage_restriction="internal-only",
            authorized="true",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        LicenseMetadata(
            license_id="COMMERCIAL",
            usage_restriction="internal-only",
            authorized=None,  # type: ignore[arg-type]
        )


def test_unauthorized_content_can_be_saved() -> None:
    c = _content(license=_license(authorized=False))
    assert c.license.authorized is False


def test_unauthorized_content_is_not_usable() -> None:
    c = _content(license=_license(authorized=False))
    decision = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)
    assert c.is_usable(decision) is False


def test_authorized_content_is_usable_when_available() -> None:
    c = _content(available_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC))
    decision = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)
    assert c.is_usable(decision) is True


# --- duplicate URL ----------------------------------------------------------


def test_duplicate_url_is_stable_and_traceable() -> None:
    url = "https://example.com/news/1"
    first = _content(url=url, ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC))
    second = _content(url=url, ingest_time=datetime(2026, 8, 21, 2, 5, tzinfo=UTC))

    assert first.url == second.url == url
    assert first.fingerprint == second.fingerprint
    assert first.record_id == second.record_id  # same lineage
    assert first.version_id != second.version_id  # distinct versions
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


# --- version audit chain (I1) -----------------------------------------------


def test_update_creates_new_version_pointing_to_old() -> None:
    old = _content(title="旧标题", body="旧正文")
    new = updated_content(
        old,
        title="新标题",
        body="新正文",
        publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )

    assert old.title == "旧标题"  # old version unchanged
    assert new.title == "新标题"
    assert new.record_id == old.record_id
    assert new.version_id != old.version_id
    assert new.previous_version_id == old.version_id
    assert new.fingerprint != old.fingerprint


def test_metadata_update_same_fingerprint_different_version_id() -> None:
    # Same body but a later ingest/available time -> same fingerprint, new version.
    old = _content(title="标题", body="正文")
    new = updated_content(
        old,
        title="标题",
        body="正文",
        publish_time=old.publish_time,
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )
    assert new.fingerprint == old.fingerprint
    assert new.version_id != old.version_id
    assert new.previous_version_id == old.version_id


def test_backward_time_update_is_rejected() -> None:
    old = _content(ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC))
    with pytest.raises(ValueError, match="ingest_time"):
        updated_content(
            old,
            title="新标题",
            body="新正文",
            publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),  # backwards
            available_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
        )


def test_delete_creates_tombstone_preserving_audit() -> None:
    original = _content(
        source=_source(source_id="cninfo", evidence_id="evt-keep"),
        license=_license(),
        available_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
    )
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))

    assert tombstone.deleted is True
    assert tombstone.deleted_at is not None
    assert tombstone.source == original.source
    assert tombstone.license == original.license
    assert tombstone.fingerprint == original.fingerprint
    assert tombstone.url == original.url
    assert tombstone.record_id == original.record_id
    assert tombstone.previous_version_id == original.version_id
    assert original.deleted is False  # original untouched


def test_delete_tombstone_is_not_self_referencing() -> None:
    original = _content()
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    assert tombstone.version_id != tombstone.previous_version_id
    assert tombstone.previous_version_id == original.version_id


def test_delete_before_available_is_rejected() -> None:
    original = _content(available_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="deleted_at"):
        mark_deleted(original, deleted_at=datetime(2026, 8, 21, 1, 0, tzinfo=UTC))


def test_update_of_deleted_record_is_rejected() -> None:
    original = _content()
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="deleted"):
        updated_content(
            tombstone,
            title="复活",
            body="正文",
            publish_time=datetime(2026, 8, 21, 5, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 5, 5, tzinfo=UTC),
            available_time=datetime(2026, 8, 21, 5, 5, tzinfo=UTC),
        )


# --- time-zone and provenance fail-closed -----------------------------------


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _content(publish_time=datetime(2026, 8, 21, 1, 0))  # naive


def test_non_utc_aware_datetime_is_normalized_to_utc() -> None:
    east8 = timezone(timedelta(hours=8))
    c = _content(
        publish_time=datetime(2026, 8, 21, 9, 0, tzinfo=east8),  # 01:00 UTC
        ingest_time=datetime(2026, 8, 21, 9, 5, tzinfo=east8),
    )
    assert c.publish_time == datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
    assert c.publish_time.tzinfo == UTC


def test_empty_source_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="source"):
        _content(source=ContentSource(source_id="", source_version="v1", evidence_id="evt-001"))


def test_empty_evidence_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence"):
        _content(source=ContentSource(source_id="cninfo", source_version="v1", evidence_id=""))


def test_empty_license_is_rejected() -> None:
    with pytest.raises(ValueError, match="license"):
        _content(
            license=LicenseMetadata(
                license_id="", usage_restriction="internal-only", authorized=True
            )
        )


def test_empty_usage_restriction_is_rejected() -> None:
    with pytest.raises(ValueError, match="usage"):
        _content(
            license=LicenseMetadata(license_id="COMMERCIAL", usage_restriction="", authorized=True)
        )


def test_invalid_content_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="content_type"):
        _content(content_type="BLOG")  # type: ignore[arg-type]


def test_empty_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="url"):
        _content(url="")


def test_empty_record_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="record_id"):
        _content(record_id="")


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
            available_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
            license=_license(),
            record_id="rec-1",
            deleted=True,
            deleted_at=None,
        )


def test_non_deleted_rejects_deleted_at() -> None:
    with pytest.raises(ValueError, match="deleted"):
        _content(deleted=False, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))


# --- PIT monotonicity (I1) --------------------------------------------------


def test_update_publish_time_backwards_is_rejected() -> None:
    old = _content(
        publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="publish_time"):
        updated_content(
            old,
            title="新",
            body="新",
            publish_time=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),  # backwards
            ingest_time=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
            available_time=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
        )


def test_update_ingest_time_backwards_is_rejected() -> None:
    old = _content(
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="ingest_time"):
        updated_content(
            old,
            title="新",
            body="新",
            publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),  # == old (not later)
            available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        )


def test_update_available_time_backwards_is_rejected() -> None:
    old = _content(available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC))
    with pytest.raises(ValueError, match="available_time"):
        updated_content(
            old,
            title="新",
            body="新",
            publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
            available_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),  # backwards
        )


def test_update_available_before_ingest_is_rejected() -> None:
    old = _content()
    with pytest.raises(ValueError, match="ingest_time"):
        updated_content(
            old,
            title="新",
            body="新",
            publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
            available_time=datetime(2026, 8, 21, 3, 30, tzinfo=UTC),  # < ingest
        )


def test_update_with_valid_monotonic_times_succeeds() -> None:
    old = _content()
    new = updated_content(
        old,
        title="新",
        body="新",
        publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )
    assert new.version_id != old.version_id
    assert new.previous_version_id == old.version_id


# --- tombstone usability (I2) -----------------------------------------------


def test_tombstone_is_not_usable_before_or_after_deletion() -> None:
    original = _content(available_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC))
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    before = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)
    after = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)
    assert tombstone.is_usable(before) is False
    assert tombstone.is_usable(after) is False


def test_authorized_tombstone_is_not_usable() -> None:
    original = _content(license=_license(authorized=True))
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    assert tombstone.license.authorized is True
    assert tombstone.is_usable(datetime(2026, 8, 21, 5, 0, tzinfo=UTC)) is False


def test_unauthorized_tombstone_is_not_usable() -> None:
    original = _content(license=_license(authorized=False))
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    assert tombstone.is_usable(datetime(2026, 8, 21, 5, 0, tzinfo=UTC)) is False


def test_tombstone_preserves_audit_fields() -> None:
    original = _content(
        source=_source(source_id="cninfo", evidence_id="evt-keep"),
        license=_license(),
        original_source=_source(source_id="orig", evidence_id="evt-o"),
    )
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    assert tombstone.source == original.source
    assert tombstone.license == original.license
    assert tombstone.original_source == original.original_source
    assert tombstone.fingerprint == original.fingerprint
    assert tombstone.previous_version_id == original.version_id
    assert original.deleted is False


# --- previous_version_id format validation (I5) -----------------------------


def test_previous_version_id_blank_is_rejected() -> None:
    with pytest.raises(ValueError, match="previous_version_id"):
        _content(previous_version_id="")


def test_previous_version_id_wrong_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="previous_version_id"):
        _content(previous_version_id="a" * 63)
    with pytest.raises(ValueError, match="previous_version_id"):
        _content(previous_version_id="a" * 65)


def test_previous_version_id_uppercase_hex_is_rejected() -> None:
    with pytest.raises(ValueError, match="previous_version_id"):
        _content(previous_version_id="A" * 64)


def test_previous_version_id_non_hex_is_rejected() -> None:
    with pytest.raises(ValueError, match="previous_version_id"):
        _content(previous_version_id="g" * 64)


def test_previous_version_id_never_equals_own_version_id() -> None:
    # A valid predecessor id is accepted, and the derived version id (which
    # binds the predecessor id itself) never collides with it.
    valid = "a" * 64
    c = _content(previous_version_id=valid)
    assert c.previous_version_id == valid
    assert c.version_id != valid


def test_previous_version_id_valid_hex_is_accepted() -> None:
    valid = "a" * 64
    c = _content(previous_version_id=valid)
    assert c.previous_version_id == valid


def test_self_reference_is_rejected_when_version_id_collides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The self-reference guard is normally unreachable because version_id binds
    # previous_version_id (no SHA-256 fixed point exists). Force the derived
    # version_id to collide with the predecessor id to exercise the guard.
    prev = "a" * 64

    def fake_derive(material: object) -> str:
        return prev

    monkeypatch.setattr("event_core.content.raw_content._derive_version_id", fake_derive)
    with pytest.raises(ValueError, match="self-reference"):
        _content(previous_version_id=prev)
