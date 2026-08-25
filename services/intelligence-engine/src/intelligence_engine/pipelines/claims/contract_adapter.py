"""Public contract adapter for the claim candidate domain."""

from collections.abc import Mapping

from kol_core.extraction import (
    ClaimExtractionCandidate,
    parse_claim_extraction_candidate_payload,
    to_claim_extraction_candidate_contract,
)


def parse_claim_candidate_payload(payload: Mapping[str, object]) -> ClaimExtractionCandidate:
    return parse_claim_extraction_candidate_payload(payload)


def to_claim_candidate_contract(candidate: ClaimExtractionCandidate):
    return to_claim_extraction_candidate_contract(candidate)


__all__ = ["parse_claim_candidate_payload", "to_claim_candidate_contract"]
