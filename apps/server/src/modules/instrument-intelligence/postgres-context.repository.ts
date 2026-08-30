import type { Pool } from "pg";
import { loadMarketEvents } from "./postgres-event.read-model";
import { loadInstrumentMaster } from "./postgres-instrument-master.read-model";
import {
  loadKolClaims,
  loadPersistedEvidence,
  loadSeatTrades,
} from "./postgres-seat-kol.read-model";
import { loadSectorContext } from "./postgres-sector.read-model";
import type {
  PostgresInstrumentContext,
  PostgresInstrumentContextReadModel,
} from "./read-model.types";

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

export class PostgresInstrumentContextRepository implements PostgresInstrumentContextReadModel {
  constructor(private readonly pool: Pool) {}

  async load(instrumentId: string, asOf: string): Promise<PostgresInstrumentContext> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
      const identity = await loadInstrumentMaster(client, instrumentId, asOf);
      const sectors = await loadSectorContext(client, instrumentId, asOf);
      const events = await loadMarketEvents(client, instrumentId, asOf);
      const seats = await loadSeatTrades(client, instrumentId, asOf);
      const claims = await loadKolClaims(client, instrumentId, asOf);
      const evidenceIds = unique([
        ...(identity?.evidenceIds ?? []),
        ...sectors.flatMap((item) => item.evidenceIds),
        ...events.flatMap((item) => item.evidenceIds),
        ...seats.flatMap((item) => item.evidenceIds),
        ...claims.flatMap((item) => item.evidenceIds),
      ]);
      const evidence = await loadPersistedEvidence(client, evidenceIds, asOf);
      await client.query("COMMIT");
      return { identity, sectors, events, seats, claims, evidence };
    } catch (error) {
      try {
        await client.query("ROLLBACK");
      } catch {
        // Preserve the original query or integrity failure.
      }
      throw error;
    } finally {
      client.release();
    }
  }
}
