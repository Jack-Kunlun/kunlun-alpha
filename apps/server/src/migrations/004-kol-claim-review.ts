import type { Migration } from "@kunlun/db";

export const migrations: Migration[] = [{
  version: 4,
  name: "kol_claim_review_projection",
  up: [
    {
      name: "kol_claim_candidate_projection",
      columns: [
        { name: "candidate_id", type: "TEXT", notNull: true }, { name: "revision_id", type: "TEXT", notNull: true }, { name: "previous_revision_id", type: "TEXT" }, { name: "previous_available_at", type: "TIMESTAMPTZ" }, { name: "available_at", type: "TIMESTAMPTZ", notNull: true }, { name: "deleted", type: "BOOLEAN", notNull: true }, { name: "deleted_at", type: "TIMESTAMPTZ" }, { name: "deletion_reason", type: "TEXT" }, { name: "confidence_bps", type: "INTEGER", notNull: true }, { name: "integrity_fingerprint", type: "TEXT", notNull: true }, { name: "payload_fingerprint", type: "TEXT", notNull: true }, { name: "canonical_payload", type: "JSONB", notNull: true },
      ],
      constraints: ["CONSTRAINT kol_claim_candidate_projection_pk PRIMARY KEY (candidate_id, revision_id)", "CONSTRAINT kol_claim_candidate_revision_available_uq UNIQUE (candidate_id, revision_id, available_at)", "CONSTRAINT kol_claim_candidate_previous_fk FOREIGN KEY (candidate_id, previous_revision_id, previous_available_at) REFERENCES kol_claim_candidate_projection (candidate_id, revision_id, available_at)", "CONSTRAINT kol_claim_candidate_previous_pair_ck CHECK ((previous_revision_id IS NULL AND previous_available_at IS NULL) OR (previous_revision_id IS NOT NULL AND previous_available_at IS NOT NULL))", "CONSTRAINT kol_claim_candidate_previous_time_ck CHECK (previous_available_at IS NULL OR previous_available_at < available_at)", "CONSTRAINT kol_claim_candidate_confidence_ck CHECK (confidence_bps BETWEEN 0 AND 10000)", "CONSTRAINT kol_claim_candidate_revision_self_ck CHECK (previous_revision_id IS NULL OR previous_revision_id <> revision_id)", "CONSTRAINT kol_claim_candidate_tombstone_ck CHECK ((deleted = TRUE AND deleted_at IS NOT NULL AND deletion_reason IS NOT NULL AND char_length(deletion_reason) BETWEEN 1 AND 1000) OR (deleted = FALSE AND deleted_at IS NULL AND deletion_reason IS NULL))"],
      indexes: [{ name: "kol_claim_candidate_revision_uq", columns: ["candidate_id", "revision_id"], unique: true }, { name: "kol_claim_candidate_root_uq", columns: ["candidate_id"], unique: true, predicate: "previous_revision_id IS NULL" }, { name: "kol_claim_candidate_predecessor_uq", columns: ["candidate_id", "previous_revision_id"], unique: true, predicate: "previous_revision_id IS NOT NULL" }],
    },
    {
      name: "kol_claim_reviews",
      columns: [
        { name: "review_id", type: "TEXT", primaryKey: true, notNull: true }, { name: "candidate_id", type: "TEXT", notNull: true }, { name: "candidate_revision_id", type: "TEXT", notNull: true }, { name: "decision", type: "TEXT", notNull: true }, { name: "reason", type: "TEXT", notNull: true }, { name: "comment", type: "TEXT" }, { name: "reviewer_ref", type: "TEXT", notNull: true }, { name: "created_at", type: "TIMESTAMPTZ", notNull: true }, { name: "available_at", type: "TIMESTAMPTZ", notNull: true }, { name: "submission_fingerprint", type: "TEXT", notNull: true }, { name: "previous_review_id", type: "TEXT" },
      ],
      constraints: ["CONSTRAINT kol_claim_reviews_candidate_fk FOREIGN KEY (candidate_id, candidate_revision_id) REFERENCES kol_claim_candidate_projection (candidate_id, revision_id)", "CONSTRAINT kol_claim_reviews_identity_uq UNIQUE (review_id, candidate_id, candidate_revision_id)", "CONSTRAINT kol_claim_reviews_previous_same_candidate_fk FOREIGN KEY (previous_review_id, candidate_id, candidate_revision_id) REFERENCES kol_claim_reviews (review_id, candidate_id, candidate_revision_id)", "CONSTRAINT kol_claim_reviews_decision_ck CHECK (decision IN ('IN_REVIEW','APPROVED','REJECTED'))", "CONSTRAINT kol_claim_reviews_reason_ck CHECK (char_length(reason) BETWEEN 1 AND 1000)", "CONSTRAINT kol_claim_reviews_comment_ck CHECK (comment IS NULL OR char_length(comment) BETWEEN 1 AND 4000)", "CONSTRAINT kol_claim_reviews_times_ck CHECK (created_at <= available_at)", "CONSTRAINT kol_claim_reviews_self_fk_ck CHECK (previous_review_id IS NULL OR previous_review_id <> review_id)"],
      indexes: [{ name: "kol_claim_reviews_submission_uq", columns: ["submission_fingerprint"], unique: true }, { name: "kol_claim_reviews_root_uq", columns: ["candidate_id", "candidate_revision_id"], unique: true, predicate: "previous_review_id IS NULL" }, { name: "kol_claim_reviews_predecessor_uq", columns: ["candidate_id", "candidate_revision_id", "previous_review_id"], unique: true, predicate: "previous_review_id IS NOT NULL" }],
    },
  ],
  down: ["kol_claim_reviews", "kol_claim_candidate_projection"],
}];
