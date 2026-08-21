"""Contract-boundary tests (P3-N01 C3 / I2).

Proves the JSON Schema DTO and the event-core domain model share one
serialization truth, that the DTO→domain conversion is lossless and validates
the fingerprint/version identity, and that the generated DTO enforces the
Schema constraints (64-hex fingerprint, explicit strict authorization, required
availableTime, deleted/deletedAt condition, version chain). All failure tests
operate on the real camelCase wire payload, never a snake_case Python object.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from ashare_contracts import ContentType as ContentTypeDTO
from ashare_contracts import RawContent as RawContentDTO
from event_core.content import (
    ContentSource,
    ContentType,
    LicenseMetadata,
    RawContent,
    from_contract,
    mark_deleted,
    to_contract,
    updated_content,
)
from pydantic import ValidationError


def _domain(
    *,
    title: str = "标题",
    body: str = "正文",
    content_type: ContentType = "NEWS",
    available_time: datetime = datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
    deleted: bool = False,
    deleted_at: datetime | None = None,
) -> RawContent:
    return RawContent(
        content_type=content_type,
        source=ContentSource(source_id="cninfo", source_version="v1", evidence_id="evt-001"),
        url="https://example.com/news/1",
        title=title,
        body=body,
        publish_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
        available_time=available_time,
        license=LicenseMetadata(
            license_id="COMMERCIAL", usage_restriction="internal-only", authorized=True
        ),
        record_id="rec-1",
        deleted=deleted,
        deleted_at=deleted_at,
    )


def _wire_data(domain: RawContent | None = None) -> dict[str, Any]:
    """The real camelCase wire payload (by_alias + JSON mode)."""
    return to_contract(domain or _domain()).model_dump(by_alias=True, mode="json")


# --- lossless round-trip (I4) -----------------------------------------------


def test_dto_domain_dto_roundtrip_preserves_all_fields() -> None:
    domain = _domain(title="标题", body="正文")
    dto = to_contract(domain)
    back = from_contract(dto)

    assert back == domain
    assert back.fingerprint == domain.fingerprint
    assert back.version_id == domain.version_id
    assert back.available_time == domain.available_time
    assert back.source == domain.source
    assert back.license == domain.license


def test_dto_wire_dict_dto_roundtrip() -> None:
    dto = to_contract(_domain())
    wire = dto.model_dump(by_alias=True, mode="json")
    assert "contentType" in wire
    assert "availableTime" in wire
    assert "recordId" in wire
    assert "versionId" in wire
    rebuilt = RawContentDTO.model_validate(wire)
    assert rebuilt == dto


def test_domain_dto_domain_roundtrip() -> None:
    domain = _domain()
    assert from_contract(to_contract(domain)) == domain


def test_roundtrip_preserves_repost_and_previous_version() -> None:
    first = _domain()
    repost = RawContent(
        content_type="NEWS",
        source=ContentSource(source_id="repost", source_version="v1", evidence_id="evt-r"),
        url="https://repost.example.com/1",
        title="标题",
        body="正文",
        publish_time=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
        license=LicenseMetadata(
            license_id="COMMERCIAL", usage_restriction="internal-only", authorized=True
        ),
        record_id="rec-2",
        original_source=ContentSource(source_id="orig", source_version="v1", evidence_id="evt-o"),
        previous_version_id=first.version_id,
    )
    back = from_contract(to_contract(repost))
    assert back.original_source == repost.original_source
    assert back.previous_version_id == first.version_id


# --- fingerprint / version identity validation ------------------------------


def test_forged_fingerprint_is_rejected() -> None:
    domain = _domain()
    forged = to_contract(domain).model_copy(update={"fingerprint": "0" * 64})
    with pytest.raises(ValueError, match="fingerprint"):
        from_contract(forged)


def test_forged_version_id_is_rejected() -> None:
    domain = _domain()
    forged = to_contract(domain).model_copy(update={"version_id": "0" * 64})
    with pytest.raises(ValueError, match="version_id"):
        from_contract(forged)


# --- version_id binds the full immutable wire material (C1) -----------------


def test_version_id_binds_source() -> None:
    data = _wire_data()
    data["source"]["sourceId"] = "evil-source"  # type: ignore[index]
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_license_policy() -> None:
    data = _wire_data()
    data["license"]["licenseId"] = "EVIL-LICENSE"  # type: ignore[index]
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_authorized() -> None:
    data = _wire_data()
    data["license"]["authorized"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_usage_restriction() -> None:
    data = _wire_data()
    data["license"]["usageRestriction"] = "evil-restriction"  # type: ignore[index]
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_url() -> None:
    data = _wire_data()
    data["url"] = "https://evil.example.com/news/1"
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_content_type() -> None:
    data = _wire_data()
    data["contentType"] = "SOCIAL"
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_publish_time() -> None:
    data = _wire_data()
    data["publishTime"] = "2026-08-21T01:01:00Z"
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_original_source() -> None:
    data = _wire_data()
    data["originalSource"] = {
        "sourceId": "evil-orig",
        "sourceVersion": "v1",
        "evidenceId": "evt-evil",
    }
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_previous_version_id() -> None:
    data = _wire_data()
    data["previousVersionId"] = "0" * 64
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_deleted_state() -> None:
    data = _wire_data()
    data["deleted"] = True
    data["deletedAt"] = "2026-08-21T04:00:00Z"
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


def test_version_id_binds_deleted_time() -> None:
    tombstone = mark_deleted(_domain(), deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    data = _wire_data(tombstone)
    data["deletedAt"] = "2026-08-21T05:00:00Z"
    with pytest.raises(ValueError, match="version_id"):
        from_contract(RawContentDTO.model_validate(data))


# --- strict boolean (C2) ----------------------------------------------------


def _assert_validation_error(
    data: dict[str, Any],
    expected_loc: tuple[str | int, ...],
    msg_contains: str | None = None,
) -> None:
    """Assert a wire payload fails with the exact error location (and message)."""
    with pytest.raises(ValidationError) as exc_info:
        RawContentDTO.model_validate(data)
    errors = exc_info.value.errors()
    locs = {tuple(e["loc"]) for e in errors}
    assert expected_loc in locs, f"expected loc {expected_loc}, got {locs}"
    if msg_contains is not None:
        msgs = [e.get("msg", "") for e in errors]
        assert any(msg_contains in m for m in msgs), f"expected msg containing {msg_contains!r}"


def _with(data: dict[str, Any], field_path: list[str], value: object) -> dict[str, Any]:
    """Return a copy of ``data`` with one nested field mutated."""
    node = data
    for key in field_path[:-1]:
        node = node[key]  # type: ignore[index]
    node[field_path[-1]] = value  # type: ignore[index]
    return data


# --- strict boolean with exact loc (C2 / I2) --------------------------------


def test_authorized_strict_bool_rejects_non_bool() -> None:
    for bad in (1, 0, "true", "false", None):
        _assert_validation_error(
            _with(_wire_data(), ["license", "authorized"], bad),
            ("license", "authorized"),
        )


def test_authorized_missing_is_rejected() -> None:
    data = _wire_data()
    del data["license"]["authorized"]  # type: ignore[arg-type]
    _assert_validation_error(data, ("license", "authorized"))


def test_deleted_strict_bool_rejects_non_bool() -> None:
    for bad in (0, 1, "true", "false", None):
        _assert_validation_error(_with(_wire_data(), ["deleted"], bad), ("deleted",))


def test_deleted_missing_is_rejected() -> None:
    data = _wire_data()
    del data["deleted"]
    _assert_validation_error(data, ("deleted",))


def test_false_authorized_is_preserved() -> None:
    domain = _domain()
    domain = RawContent(
        content_type=domain.content_type,
        source=domain.source,
        url=domain.url,
        title=domain.title,
        body=domain.body,
        publish_time=domain.publish_time,
        ingest_time=domain.ingest_time,
        available_time=domain.available_time,
        license=LicenseMetadata(
            license_id="COMMERCIAL", usage_restriction="internal-only", authorized=False
        ),
        record_id=domain.record_id,
    )
    dto = to_contract(domain)
    assert dto.license.authorized is False
    assert from_contract(dto).license.authorized is False


# --- deleted / deletedAt condition with exact loc (I3) ----------------------


def test_deleted_true_missing_deleted_at_rejected() -> None:
    data = _wire_data()
    data["deleted"] = True
    del data["deletedAt"]
    _assert_validation_error(data, ("deletedAt",), msg_contains="deletedAt")


def test_deleted_true_null_deleted_at_rejected() -> None:
    data = _wire_data()
    data["deleted"] = True
    data["deletedAt"] = None
    _assert_validation_error(data, ("deletedAt",), msg_contains="deletedAt")


def test_deleted_false_with_deleted_at_rejected() -> None:
    data = _wire_data()
    data["deletedAt"] = "2026-08-21T04:00:00Z"
    _assert_validation_error(data, ("deletedAt",), msg_contains="deletedAt")


def test_deleted_false_without_deleted_at_passes() -> None:
    data = _wire_data()
    assert data["deleted"] is False
    assert data["deletedAt"] is None
    assert RawContentDTO.model_validate(data).deleted is False


# --- DTO field constraint with exact loc (I4) -------------------------------


def test_empty_fingerprint_rejected_by_dto() -> None:
    data = _wire_data()
    data["fingerprint"] = ""
    _assert_validation_error(data, ("fingerprint",))


def test_malformed_fingerprint_rejected_by_dto() -> None:
    short = _wire_data()
    short["fingerprint"] = "a" * 63
    _assert_validation_error(short, ("fingerprint",))
    upper = _wire_data()
    upper["fingerprint"] = "A" * 64
    _assert_validation_error(upper, ("fingerprint",))


def test_missing_available_time_rejected_by_dto() -> None:
    data = _wire_data()
    del data["availableTime"]
    _assert_validation_error(data, ("availableTime",))


def test_missing_record_id_rejected_by_dto() -> None:
    data = _wire_data()
    del data["recordId"]
    _assert_validation_error(data, ("recordId",))


def test_invalid_version_id_rejected_by_dto() -> None:
    data = _wire_data()
    data["versionId"] = "not-a-version-id"
    _assert_validation_error(data, ("versionId",))


def test_invalid_previous_version_id_rejected_by_dto() -> None:
    data = _wire_data()
    data["previousVersionId"] = "BAD"
    _assert_validation_error(data, ("previousVersionId",))


def test_empty_usage_restriction_rejected_by_dto() -> None:
    data = _wire_data()
    data["license"]["usageRestriction"] = ""  # type: ignore[index]
    _assert_validation_error(data, ("license", "usageRestriction"))


# --- cross-contract consistency ---------------------------------------------


def test_dto_enum_values_match_domain() -> None:
    dto = to_contract(_domain(content_type="ANNOUNCEMENT"))
    assert dto.content_type == ContentTypeDTO.announcement
    assert dto.content_type.value == "ANNOUNCEMENT"
    assert dto.fingerprint_algorithm_version.value == "sha256-v1"


def test_every_content_type_roundtrips() -> None:
    for ct in ("NEWS", "ANNOUNCEMENT", "RESEARCH", "INTERACTION", "SOCIAL"):
        domain = _domain(content_type=ct)
        assert from_contract(to_contract(domain)).content_type == ct


# --- version / deletion chain across the boundary ---------------------------


def test_update_chain_roundtrips() -> None:
    old = _domain(title="旧", body="旧")
    new = updated_content(
        old,
        title="新",
        body="新",
        publish_time=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 3, 5, tzinfo=UTC),
    )
    back = from_contract(to_contract(new))
    assert back.previous_version_id == old.version_id
    assert back.record_id == old.record_id


def test_tombstone_roundtrips() -> None:
    original = _domain()
    tombstone = mark_deleted(original, deleted_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC))
    back = from_contract(to_contract(tombstone))
    assert back.deleted is True
    assert back.previous_version_id == original.version_id
    assert back.fingerprint == original.fingerprint
