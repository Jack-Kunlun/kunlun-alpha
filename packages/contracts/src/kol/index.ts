export {
  parseKolDomainSnapshotPayload,
  selectKolDomainSnapshotAt,
  validateKolDomainSnapshotPayload,
  type KolDomainSnapshot,
} from "./aggregate.js";

export {
  APPROVED_REVIEW_SEMANTICS,
  KOL_ALGORITHM_VERSION,
  KOL_CLAIM_SCHEMA_VERSION,
  KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION,
  KOL_EVIDENCE_GRADE_VERSION,
  computeKolContentFingerprint,
  KOL_CONTENT_SCHEMA_VERSION,
  KOL_EVIDENCE_SCHEMA_VERSION,
  KOL_MENTION_SCHEMA_VERSION,
  KOL_POSITION_CLAIM_SCHEMA_VERSION,
  KOL_MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION,
  MEDIA_RECOGNITION_CANDIDATE_SCHEMA_VERSION,
  NON_EXECUTABLE_POSITION_CLAIM,
  isKolClaimVisibleAt,
  isKolContentVisibleAt,
  validateKolClaimPayload,
  validateKolContentPayload,
  validateKolEvidencePayload,
  validateKolMentionPayload,
  validateKolPositionClaimPayload,
  validateKolMediaTextEvidencePayload,
} from "./validators.js";
export type { ValidationResult } from "./validators.js";

export {
  CLAIM_EXTRACTION_ALGORITHM_VERSION,
  KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION,
  KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION,
  CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION,
  CLAIM_REVIEW_SCHEMA_VERSION,
  CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION,
  ClaimExtractionValidationError,
  PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION,
  PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION,
  parseClaimExtractionCandidatePayload,
  parseClaimReviewPayload,
  parseClaimReviewSubmissionPayload,
  validateClaimExtractionCandidatePayload,
  validateClaimReviewPayload,
  validateClaimReviewSubmissionPayload,
  computeCandidateIdFromPayload,
  computeCandidateRevisionIdFromPayload,
  canonicalizeClaimExtractionCandidatePayload,
  compareClaimExtractionInstants,
  computeClaimExtractionCandidatePayloadFingerprint,
} from "./claim-extraction.js";
export type {
  ClaimExtractionCandidatePayload,
  ClaimReviewPayload,
  ClaimReviewSubmissionPayload,
} from "./claim-extraction.js";
