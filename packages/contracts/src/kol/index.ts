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
  NON_EXECUTABLE_POSITION_CLAIM,
  isKolClaimVisibleAt,
  isKolContentVisibleAt,
  validateKolClaimPayload,
  validateKolContentPayload,
  validateKolEvidencePayload,
  validateKolMentionPayload,
  validateKolPositionClaimPayload,
} from "./validators.js";
export type { ValidationResult } from "./validators.js";
