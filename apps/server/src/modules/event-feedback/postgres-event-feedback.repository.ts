import type { EventFeedback } from "@kunlun/shared-types";
import type { Pool } from "pg";
import type { AppendFeedbackResult, EventFeedbackRepository } from "./event-feedback-repository";
import { type EventFeedbackQuery, validateFeedbackRecord } from "./event-feedback-validation";

interface FeedbackRow {
  feedback_id: string;
  client_request_id: string;
  event_id: string;
  model_configuration_fingerprint: string;
  action: string;
  reason_code: string;
  correction: unknown;
  comment: string | null;
  reviewer_ref: string;
  submission_fingerprint: string;
  created_at: Date | string;
  available_at: Date | string;
}

const RETURNING = `feedback_id, client_request_id, event_id, model_configuration_fingerprint,
action, reason_code, correction, comment, reviewer_ref, submission_fingerprint, created_at, available_at`;

const INSERT_SQL = `INSERT INTO event_feedback (
feedback_id, client_request_id, event_id, model_configuration_fingerprint, action, reason_code,
correction, comment, reviewer_ref, submission_fingerprint, created_at, available_at
) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12)
ON CONFLICT (feedback_id) DO NOTHING RETURNING ${RETURNING}`;

const FIND_SQL = `SELECT ${RETURNING} FROM event_feedback WHERE feedback_id = $1`;

const LIST_SQL = `SELECT ${RETURNING} FROM event_feedback
WHERE ($1::text IS NULL OR event_id = $1)
AND ($2::text IS NULL OR model_configuration_fingerprint = $2)
ORDER BY created_at DESC, feedback_id ASC LIMIT $3`;

function iso(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : value;
}

function fromRow(row: FeedbackRow): EventFeedback {
  return validateFeedbackRecord({
    schemaVersion: "event-feedback-v1",
    feedbackId: row.feedback_id,
    clientRequestId: row.client_request_id,
    eventId: row.event_id,
    modelConfigurationFingerprint: row.model_configuration_fingerprint,
    action: row.action,
    reasonCode: row.reason_code,
    ...(row.correction === null ? {} : { correction: row.correction }),
    ...(row.comment === null ? {} : { comment: row.comment }),
    reviewerRef: row.reviewer_ref,
    submissionFingerprint: row.submission_fingerprint,
    createdAt: iso(row.created_at),
    availableAt: iso(row.available_at),
  });
}

export class PostgresEventFeedbackRepository implements EventFeedbackRepository {
  constructor(private readonly pool: Pool) {}

  async append(feedback: EventFeedback): Promise<AppendFeedbackResult> {
    const params = [
      feedback.feedbackId,
      feedback.clientRequestId,
      feedback.eventId,
      feedback.modelConfigurationFingerprint,
      feedback.action,
      feedback.reasonCode,
      JSON.stringify(feedback.correction ?? null),
      feedback.comment ?? null,
      feedback.reviewerRef,
      feedback.submissionFingerprint,
      feedback.createdAt,
      feedback.availableAt,
    ];
    const inserted = await this.pool.query<FeedbackRow>(INSERT_SQL, params);
    const insertedRow = inserted.rows[0];
    if (insertedRow) return { disposition: "INSERTED", feedback: fromRow(insertedRow) };
    const existing = await this.pool.query<FeedbackRow>(FIND_SQL, [feedback.feedbackId]);
    const existingRow = existing.rows[0];
    if (!existingRow) throw new Error("event feedback conflict row disappeared");
    return { disposition: "EXISTING", feedback: fromRow(existingRow) };
  }

  async list(query: EventFeedbackQuery): Promise<EventFeedback[]> {
    const result = await this.pool.query<FeedbackRow>(LIST_SQL, [
      query.eventId ?? null,
      query.modelConfigurationFingerprint ?? null,
      query.limit,
    ]);
    return result.rows.map(fromRow);
  }
}
