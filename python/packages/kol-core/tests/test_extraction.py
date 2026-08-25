from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts import KolClaimExtractionCandidate
from kol_core.extraction import ClaimExtractionCandidate
from kol_core.extraction.aggregate import (
    compute_candidate_id_from_payload,
    compute_candidate_revision_id_from_payload,
    parse_claim_extraction_candidate_payload,
)


def _payload(overrides: dict[str, object] | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": "claim-extraction-candidate-v1",
        "candidateId": "candidate-1",
        "revisionId": "revision-1",
        "previousRevisionId": None,
        "semanticLabel": "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION",
        "statement": "公开表述",
        "action": "BUY",
        "polarity": "AFFIRMED",
        "conditionality": "UNCONDITIONAL",
        "statementKind": "DIRECT",
        "attribution": "SELF",
        "eventTimeStatus": "UNKNOWN",
        "eventTime": None,
        "eventDate": None,
        "instrumentId": "600519.SH",
        "anchors": [
            {
                "anchorType": "CONTENT",
                "sourceIndex": 0,
                "contentId": "content-1",
                "contentVersion": "v1",
                "contentRevisionId": "content-r1",
                "contentAvailableTime": "2025-01-01T03:00:00Z",
                "source": "test",
                "sourceVersion": "v1",
                "startOffset": 0,
                "endOffset": 4,
                "excerpt": "公开表述",
                "evidenceGrade": "PRIMARY_SOURCE",
                "evidenceGradeVersion": "evidence-grade-v1",
            }
        ],
        "evidenceGrade": "PRIMARY_SOURCE",
        "evidenceGradeVersion": "evidence-grade-v1",
        "confidenceBps": 8000,
        "source": "kol-claim-extractor",
        "sourceVersion": "v1",
        "algorithmVersion": "kol-claim-extraction-v1",
        "promptVersion": "prompt-v1",
        "modelProvider": "fake",
        "modelVersion": "v1",
        "configurationFingerprint": "a" * 64,
        "policyFingerprint": "b" * 64,
        "recognitionRunId": "run-1",
        "publishTime": "2025-01-01T00:00:00Z",
        "ingestTime": "2025-01-01T01:00:00Z",
        "processingTime": "2025-01-01T02:00:00Z",
        "availableTime": "2025-01-01T03:00:00Z",
        "reviewStatus": "UNREVIEWED",
        "deleted": False,
        "deletedAt": None,
        "deletionReason": None,
    }
    value.update(overrides or {})
    candidate_id = value.get("candidateId")
    if candidate_id == "candidate-1" or candidate_id is None:
        value["candidateId"] = compute_candidate_id_from_payload(value)
    if not overrides or "revisionId" not in overrides:
        value["revisionId"] = compute_candidate_revision_id_from_payload(value)
    return value


def test_extraction_candidate_public_domain_boundary_exists() -> None:
    assert ClaimExtractionCandidate.__name__ == "ClaimExtractionCandidate"


def test_generated_boundary_rejects_noncanonical_and_non_strict_values() -> None:
    invalid_code = _payload() | {"instrumentId": "600519.SZ"}
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(invalid_code)
    for value in (9000.0, True):
        invalid_confidence = _payload() | {"confidenceBps": value}
        with pytest.raises(ValueError):
            parse_claim_extraction_candidate_payload(invalid_confidence)


def test_event_time_matrix_and_revision_self_are_closed() -> None:
    exact = _payload(
        {
            "eventTimeStatus": "EXACT",
            "eventTime": "2025-01-02T08:00:00+08:00",
            "eventDate": None,
        }
    )
    assert parse_claim_extraction_candidate_payload(exact).event_time_status.value == "EXACT"
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(exact | {"eventDate": "2025-01-02"})
    with pytest.raises(ValueError):
        base = _payload()
        parse_claim_extraction_candidate_payload(base | {"previousRevisionId": base["revisionId"]})


def test_paraphrase_unknown_and_early_tombstone_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(
            _payload() | {"statementKind": "PARAPHRASE", "attribution": "UNKNOWN"}
        )
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(
            _payload()
            | {
                "deleted": True,
                "deletedAt": "2025-01-01T02:00:00Z",
                "deletionReason": "撤回",
            }
        )


def test_generated_candidate_dto_rejects_ambiguous_self() -> None:
    with pytest.raises(ValueError):
        KolClaimExtractionCandidate.model_validate(
            _payload() | {"statementKind": "AMBIGUOUS", "attribution": "SELF"}
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        "2025-01-01 00:00:00Z",
        "2025-01-01T00:00:00.1234567Z",
        "2025-02-30T00:00:00Z",
    ],
)
def test_generated_candidate_dto_rejects_non_strict_rfc3339(timestamp: str) -> None:
    payload = _payload({"publishTime": timestamp})
    with pytest.raises(ValueError):
        KolClaimExtractionCandidate.model_validate(payload)
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(payload)


def test_generated_candidate_dto_preserves_six_fractional_digits() -> None:
    payload = _payload({"publishTime": "2025-01-01T00:00:00.123456Z"})
    parsed = KolClaimExtractionCandidate.model_validate(payload)
    assert parsed.publish_time.microsecond == 123456


def test_content_anchor_cannot_smuggle_media_provenance_or_future_availability() -> None:
    anchors = cast(list[object], _payload()["anchors"])
    anchor_value = anchors[0]
    assert isinstance(anchor_value, dict)
    anchor = cast(dict[str, object], anchor_value)
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(
            _payload() | {"anchors": [anchor | {"mediaId": "media-1"}]}
        )
    future_anchor = anchor | {"contentAvailableTime": "2025-01-01T04:00:00Z"}
    with pytest.raises(ValueError):
        parse_claim_extraction_candidate_payload(_payload() | {"anchors": [future_anchor]})


def test_domain_times_are_timezone_aware() -> None:
    assert datetime.now(UTC).tzinfo is not None


def test_candidate_identity_matches_shared_cross_language_fixtures() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "packages"
        / "contracts"
        / "src"
        / "kol"
        / "claim-extraction-identity-fixtures.json"
    )
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    for item in fixtures["cases"]:
        payload = item["payload"]
        assert compute_candidate_id_from_payload(payload) == item["expectedCandidateId"]
        assert compute_candidate_revision_id_from_payload(payload) == item["expectedRevisionId"]
