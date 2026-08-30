import type { PoolClient, QueryResultRow } from "pg";
import { pgInstant, pgText, sourceVersion } from "./pg-row";
import { validateSectorMembershipPayload, validateSectorPayload } from "./pit-validation";
import type { PitRecord, SectorContext } from "./read-model.types";

interface SectorRow extends QueryResultRow {
  membership_payload: unknown;
  sector_payload: unknown;
  effective_from: unknown;
  membership_available_time: unknown;
  membership_processing_time: unknown;
  membership_source: unknown;
  membership_source_version: unknown;
  membership_evidence_id: unknown;
  sector_available_time: unknown;
  sector_processing_time: unknown;
  sector_source: unknown;
  sector_source_version: unknown;
  sector_evidence_id: unknown;
}

const SQL = [
  "WITH visible_memberships AS (",
  "  SELECT DISTINCT ON (sector_id)",
  "    sector_id, payload, effective_from, available_time, processing_time,",
  "    source, source_version, evidence_id",
  "  FROM sector_membership_revisions",
  "  WHERE instrument_id = $1",
  "    AND effective_from <= $2::timestamptz",
  "    AND (effective_to IS NULL OR effective_to > $2::timestamptz)",
  "    AND available_time <= $2::timestamptz",
  "    AND processing_time <= $2::timestamptz",
  "  ORDER BY sector_id, effective_from DESC, available_time DESC,",
  "           processing_time DESC, revision_id DESC",
  ")",
  "SELECT m.payload AS membership_payload, s.payload AS sector_payload,",
  "       m.effective_from,",
  "       m.available_time AS membership_available_time,",
  "       m.processing_time AS membership_processing_time,",
  "       m.source AS membership_source,",
  "       m.source_version AS membership_source_version,",
  "       m.evidence_id AS membership_evidence_id,",
  "       s.available_time AS sector_available_time,",
  "       s.processing_time AS sector_processing_time,",
  "       s.source AS sector_source,",
  "       s.source_version AS sector_source_version,",
  "       s.evidence_id AS sector_evidence_id",
  "FROM visible_memberships m",
  "LEFT JOIN LATERAL (",
  "  SELECT payload, available_time, processing_time, source, source_version, evidence_id",
  "  FROM sector_master_revisions",
  "  WHERE sector_id = m.sector_id",
  "    AND effective_from <= $2::timestamptz",
  "    AND (effective_to IS NULL OR effective_to > $2::timestamptz)",
  "    AND available_time <= $2::timestamptz",
  "    AND processing_time <= $2::timestamptz",
  "  ORDER BY effective_from DESC, available_time DESC, processing_time DESC, revision_id DESC",
  "  LIMIT 1",
  ") s ON TRUE",
  "ORDER BY m.sector_id",
].join("\n");

export async function loadSectorContext(
  client: Pick<PoolClient, "query">,
  instrumentId: string,
  asOf: string,
): Promise<PitRecord<SectorContext>[]> {
  const result = await client.query<SectorRow>(SQL, [instrumentId, asOf]);
  return result.rows.map((row) => {
    if (row.sector_payload === null || row.sector_payload === undefined) {
      throw new Error("visible sector membership has no visible sector master");
    }
    const membershipSource = pgText(row.membership_source, "membership_source");
    const membershipVersion = pgText(row.membership_source_version, "membership_source_version");
    const sectorSource = pgText(row.sector_source, "sector_source");
    const sectorVersion = pgText(row.sector_source_version, "sector_source_version");
    const membershipAvailable = pgInstant(
      row.membership_available_time,
      "membership_available_time",
    );
    const sectorAvailable = pgInstant(row.sector_available_time, "sector_available_time");
    const membershipProcessing = pgInstant(
      row.membership_processing_time,
      "membership_processing_time",
    );
    const sectorProcessing = pgInstant(row.sector_processing_time, "sector_processing_time");
    return {
      data: {
        membership: validateSectorMembershipPayload(row.membership_payload),
        sector: validateSectorPayload(row.sector_payload),
      },
      eventTime: pgInstant(row.effective_from, "effective_from"),
      availableTime:
        Date.parse(membershipAvailable) >= Date.parse(sectorAvailable)
          ? membershipAvailable
          : sectorAvailable,
      processingTime:
        Date.parse(membershipProcessing) >= Date.parse(sectorProcessing)
          ? membershipProcessing
          : sectorProcessing,
      sourceVersions: [
        sourceVersion(membershipSource, membershipVersion),
        sourceVersion(sectorSource, sectorVersion),
      ],
      evidenceIds: [
        pgText(row.membership_evidence_id, "membership_evidence_id"),
        pgText(row.sector_evidence_id, "sector_evidence_id"),
      ],
    };
  });
}

export const SECTOR_CONTEXT_PIT_SQL = SQL;
