/**
 * Task lifecycle state (mirrors data-worker/scheduler).
 *
 * The API exposes task status to clients; the authoritative state machine
 * lives in the Python data-worker scheduler. This module keeps the status
 * vocabulary and terminal/retry predicates in sync for the TypeScript side.
 */

export type TaskStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "DEAD";

export interface TaskRecord {
  taskId: string;
  status: TaskStatus;
  attempts: number;
}

export function isTerminal(status: TaskStatus): boolean {
  return status === "SUCCEEDED" || status === "DEAD";
}

export function canRetry(status: TaskStatus): boolean {
  return status === "PENDING" || status === "FAILED";
}
