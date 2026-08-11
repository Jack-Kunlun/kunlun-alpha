/** Shared domain types. Populated as contracts are defined in later phases. */
export interface HealthStatus {
  status: "ok" | "degraded" | "error";
  timestamp: string;
  version: string;
}
