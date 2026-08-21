"""Single conversion boundary between the wire DTO and the domain model.

The JSON Schema is the single source of serialization truth; the generated
``ashare_contracts.RawContent`` is the untrusted boundary DTO; the
``event_core.content.RawContent`` is the authoritative domain model that
enforces cross-field invariants. Business code must never treat an unvalidated
DTO as a trusted domain object — everything enters the domain through
:func:`from_contract`, which recomputes and verifies the fingerprint and the
version identity, and leaves through :func:`to_contract` for serialization.
"""

from __future__ import annotations

from ashare_contracts import (
    ContentSource as ContentSourceDTO,
)
from ashare_contracts import (
    ContentType as ContentTypeDTO,
)
from ashare_contracts import (
    FingerprintVersion as FingerprintVersionDTO,
)
from ashare_contracts import (
    LicenseMetadata as LicenseMetadataDTO,
)
from ashare_contracts import (
    RawContent as RawContentDTO,
)

from event_core.content.raw_content import (
    FINGERPRINT_ALGORITHM_VERSION,
    ContentSource,
    LicenseMetadata,
    RawContent,
)


def _source_from_dto(dto: ContentSourceDTO) -> ContentSource:
    return ContentSource(
        source_id=dto.source_id,
        source_version=dto.source_version,
        evidence_id=dto.evidence_id,
    )


def _source_to_dto(source: ContentSource) -> ContentSourceDTO:
    return ContentSourceDTO(
        sourceId=source.source_id,
        sourceVersion=source.source_version,
        evidenceId=source.evidence_id,
    )


def _license_from_dto(dto: LicenseMetadataDTO) -> LicenseMetadata:
    return LicenseMetadata(
        license_id=dto.license_id,
        usage_restriction=dto.usage_restriction,
        authorized=dto.authorized,
    )


def _license_to_dto(license: LicenseMetadata) -> LicenseMetadataDTO:
    return LicenseMetadataDTO(
        licenseId=license.license_id,
        usageRestriction=license.usage_restriction,
        authorized=license.authorized,
    )


def from_contract(dto: RawContentDTO) -> RawContent:
    """Validate an untrusted wire DTO into the authoritative domain model.

    Recomputes the content fingerprint and version identity from the raw title
    and body and rejects any mismatch, so a forged, empty or stale fingerprint
    or version id never reaches the domain. All fields are re-validated by the
    domain constructor.
    """
    domain = RawContent(
        content_type=dto.content_type.value,
        source=_source_from_dto(dto.source),
        url=dto.url,
        title=dto.title,
        body=dto.body,
        publish_time=dto.publish_time,
        ingest_time=dto.ingest_time,
        available_time=dto.available_time,
        license=_license_from_dto(dto.license),
        record_id=dto.record_id,
        original_source=_source_from_dto(dto.original_source) if dto.original_source else None,
        previous_version_id=dto.previous_version_id,
        deleted=dto.deleted,
        deleted_at=dto.deleted_at,
    )
    if domain.fingerprint != dto.fingerprint:
        raise ValueError("fingerprint mismatch: content fingerprint does not match title/body")
    if domain.version_id != dto.version_id:
        raise ValueError("version_id mismatch: version identity does not match record facts")
    if domain.fingerprint_algorithm_version != dto.fingerprint_algorithm_version.value:
        raise ValueError("fingerprint_algorithm_version mismatch")
    return domain


def to_contract(domain: RawContent) -> RawContentDTO:
    """Serialize the authoritative domain model back to the wire DTO losslessly."""
    return RawContentDTO(
        contentType=ContentTypeDTO(domain.content_type),
        recordId=domain.record_id,
        versionId=domain.version_id,
        url=domain.url,
        title=domain.title,
        body=domain.body,
        publishTime=domain.publish_time,
        ingestTime=domain.ingest_time,
        availableTime=domain.available_time,
        fingerprint=domain.fingerprint,
        fingerprintAlgorithmVersion=FingerprintVersionDTO(domain.fingerprint_algorithm_version),
        source=_source_to_dto(domain.source),
        license=_license_to_dto(domain.license),
        originalSource=_source_to_dto(domain.original_source) if domain.original_source else None,
        previousVersionId=domain.previous_version_id,
        deleted=domain.deleted,
        deletedAt=domain.deleted_at,
    )


__all__ = ["from_contract", "to_contract", "FINGERPRINT_ALGORITHM_VERSION"]
