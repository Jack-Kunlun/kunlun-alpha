import {
  validateKolClaimPayload,
  validateKolContentPayload,
  validateKolEvidencePayload,
  validateKolPositionClaimPayload,
  type ValidationResult,
} from "./validators.js";

type JsonRecord = Record<string, unknown>;
type FrozenRecord = Readonly<JsonRecord>;

export interface KolDomainSnapshot {
  readonly content: readonly FrozenRecord[];
  readonly evidence: readonly FrozenRecord[];
  readonly claims: readonly FrozenRecord[];
  readonly positionClaims: readonly FrozenRecord[];
}

const SNAPSHOT_FIELDS = ["content", "evidence", "claims", "positionClaims"] as const;
const INSTANT_PATTERN = /T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function record(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function instant(value: unknown, field: string, errors: string[]): number | undefined {
  if (typeof value !== "string" || !INSTANT_PATTERN.test(value)) {
    errors.push(`${field} must be a timezone-aware RFC 3339 instant`);
    return undefined;
  }
  const milliseconds = Date.parse(value);
  if (Number.isNaN(milliseconds)) errors.push(`${field} must be a valid instant`);
  return Number.isNaN(milliseconds) ? undefined : milliseconds;
}

function stringValue(value: unknown, field: string, errors: string[]): string | undefined {
  if (typeof value !== "string" || value.length === 0) {
    errors.push(`${field} must be a non-empty string`);
    return undefined;
  }
  return value;
}

function entityKey(entityId: string, revisionId: string): string {
  return `${entityId}\u0000${revisionId}`;
}

function contentKey(contentId: string, contentVersion: string): string {
  return `${contentId}\u0000${contentVersion}`;
}

function validateRevisionGraph(
  records: readonly JsonRecord[],
  entityName: string,
  entityIdField: string,
  errors: string[],
): void {
  const groups = new Map<string, JsonRecord[]>();
  records.forEach((recordValue, index) => {
    const entityId = stringValue(
      recordValue[entityIdField],
      `${entityName}[${index}].${entityIdField}`,
      errors,
    );
    if (entityId === undefined) return;
    const group = groups.get(entityId);
    if (group === undefined) groups.set(entityId, [recordValue]);
    else group.push(recordValue);
  });

  for (const [logicalId, group] of groups) {
    const byRevision = new Map<string, JsonRecord>();
    const roots: string[] = [];
    group.forEach((recordValue, index) => {
      const revisionId = stringValue(
        recordValue.revisionId,
        `${entityName}[${index}].revisionId`,
        errors,
      );
      if (revisionId === undefined) return;
      if (byRevision.has(revisionId)) {
        errors.push(`${entityName} has duplicate logical id and revision`);
        return;
      }
      byRevision.set(revisionId, recordValue);
      if (recordValue.previousRevisionId === null) roots.push(revisionId);
    });

    if (roots.length !== 1) {
      errors.push(`${entityName} logical id ${logicalId} must have exactly one root`);
    }

    const parentByRevision = new Map<string, string>();
    const childByRevision = new Map<string, string>();
    for (const [revisionId, recordValue] of byRevision) {
      if (recordValue.previousRevisionId === null) continue;
      const previous = stringValue(
        recordValue.previousRevisionId,
        `${entityName}.${revisionId}.previousRevisionId`,
        errors,
      );
      if (previous === undefined) continue;
      if (previous === revisionId) {
        errors.push(`${entityName} revision graph contains a cycle`);
        continue;
      }
      const parent = byRevision.get(previous);
      if (parent === undefined) {
        errors.push(`${entityName} previous revision must exist under the same logical id`);
        continue;
      }
      const existingChild = childByRevision.get(previous);
      if (existingChild !== undefined && existingChild !== revisionId) {
        errors.push(`${entityName} revision graph contains a fork`);
      }
      childByRevision.set(previous, revisionId);
      parentByRevision.set(revisionId, previous);
      const parentAvailable = instant(
        parent.availableTime,
        `${entityName}.${previous}.availableTime`,
        errors,
      );
      const childAvailable = instant(
        recordValue.availableTime,
        `${entityName}.${revisionId}.availableTime`,
        errors,
      );
      if (
        parentAvailable !== undefined &&
        childAvailable !== undefined &&
        childAvailable <= parentAvailable
      ) {
        errors.push(`${entityName} revisions must have strictly increasing availableTime`);
      }
    }

    for (const revisionId of byRevision.keys()) {
      const visited = new Set<string>();
      let current: string | undefined = revisionId;
      while (current !== undefined) {
        if (visited.has(current)) {
          errors.push(`${entityName} revision graph contains a cycle`);
          break;
        }
        visited.add(current);
        current = parentByRevision.get(current);
        if (current !== undefined && !byRevision.has(current)) {
          errors.push(`${entityName} revision graph is disconnected`);
          break;
        }
      }
    }

    if (roots.length === 1) {
      const reachable = new Set<string>();
      let current: string | undefined = roots[0];
      while (current !== undefined) {
        if (reachable.has(current)) {
          errors.push(`${entityName} revision graph contains a cycle`);
          break;
        }
        reachable.add(current);
        current = childByRevision.get(current);
      }
      if (reachable.size !== byRevision.size) {
        errors.push(`${entityName} revision graph is disconnected`);
      }
    }
  }
}

function collection(
  payload: JsonRecord,
  field: (typeof SNAPSHOT_FIELDS)[number],
  errors: string[],
): JsonRecord[] {
  const value = payload[field];
  if (!Array.isArray(value)) {
    errors.push(`${field} must be an array`);
    return [];
  }
  const records: JsonRecord[] = [];
  value.forEach((item, index) => {
    const itemRecord = record(item);
    if (itemRecord === null) errors.push(`${field}[${index}] must be an object`);
    else records.push(itemRecord);
  });
  return records;
}

function prefixed(result: ValidationResult, field: string, errors: string[]): void {
  if (!result.valid) result.errors.forEach((error) => errors.push(`${field}: ${error}`));
}

function validateLinks(
  content: readonly JsonRecord[],
  evidence: readonly JsonRecord[],
  claims: readonly JsonRecord[],
  positions: readonly JsonRecord[],
  errors: string[],
): void {
  const contents = new Map<string, JsonRecord>();
  for (const item of content) {
    const contentId = typeof item.contentId === "string" ? item.contentId : undefined;
    const contentVersion =
      typeof item.contentVersion === "string" ? item.contentVersion : undefined;
    if (contentId === undefined || contentVersion === undefined) continue;
    const key = contentKey(contentId, contentVersion);
    if (contents.has(key)) errors.push("content has duplicate contentId/contentVersion");
    contents.set(key, item);
  }

  const evidences = new Map<string, JsonRecord>();
  for (const item of evidence) {
    const evidenceId = typeof item.evidenceId === "string" ? item.evidenceId : undefined;
    const revisionId = typeof item.revisionId === "string" ? item.revisionId : undefined;
    const contentId = typeof item.contentId === "string" ? item.contentId : undefined;
    const contentVersion =
      typeof item.contentVersion === "string" ? item.contentVersion : undefined;
    if (evidenceId === undefined || revisionId === undefined) continue;
    evidences.set(entityKey(evidenceId, revisionId), item);
    if (contentId === undefined || contentVersion === undefined) continue;
    const linkedContent = contents.get(contentKey(contentId, contentVersion));
    if (linkedContent === undefined) {
      errors.push("evidence must bind to an actual content id and version");
      continue;
    }
    const contentAvailable = instant(linkedContent.availableTime, "content.availableTime", errors);
    const evidenceContentAvailable = instant(
      item.contentAvailableTime,
      "evidence.contentAvailableTime",
      errors,
    );
    if (
      contentAvailable !== undefined &&
      evidenceContentAvailable !== undefined &&
      contentAvailable !== evidenceContentAvailable
    ) {
      errors.push("evidence contentAvailableTime must match the actual content revision");
    }
    if (
      item.source !== linkedContent.source ||
      item.sourceVersion !== linkedContent.sourceVersion
    ) {
      errors.push("evidence source does not match the actual content revision");
    }
    const evidenceAvailable = instant(item.availableTime, "evidence.availableTime", errors);
    if (
      contentAvailable !== undefined &&
      evidenceAvailable !== undefined &&
      evidenceAvailable < contentAvailable
    ) {
      errors.push("evidence availableTime must include content availability");
    }
  }

  const claimsByKey = new Map<string, JsonRecord>();
  for (const item of claims) {
    const claimId = typeof item.claimId === "string" ? item.claimId : undefined;
    const revisionId = typeof item.revisionId === "string" ? item.revisionId : undefined;
    const contentId = typeof item.contentId === "string" ? item.contentId : undefined;
    const contentVersion =
      typeof item.contentVersion === "string" ? item.contentVersion : undefined;
    if (claimId === undefined || revisionId === undefined) continue;
    claimsByKey.set(entityKey(claimId, revisionId), item);
    if (contentId === undefined || contentVersion === undefined) continue;
    const linkedContent = contents.get(contentKey(contentId, contentVersion));
    if (linkedContent === undefined) {
      errors.push("claim must bind to an actual content id and version");
    } else {
      const contentAvailable = instant(
        linkedContent.availableTime,
        "content.availableTime",
        errors,
      );
      const claimContentAvailable = instant(
        item.contentAvailableTime,
        "claim.contentAvailableTime",
        errors,
      );
      if (
        contentAvailable !== undefined &&
        claimContentAvailable !== undefined &&
        contentAvailable !== claimContentAvailable
      ) {
        errors.push("claim contentAvailableTime must match the actual content revision");
      }
      const claimAvailable = instant(item.availableTime, "claim.availableTime", errors);
      if (
        contentAvailable !== undefined &&
        claimAvailable !== undefined &&
        claimAvailable < contentAvailable
      ) {
        errors.push("claim availableTime must include content availability");
      }
    }
    const references = Array.isArray(item.evidence) ? item.evidence : [];
    references.forEach((reference, index) => {
      const ref = record(reference);
      if (ref === null) return;
      const evidenceId = typeof ref.evidenceId === "string" ? ref.evidenceId : undefined;
      const evidenceRevisionId =
        typeof ref.evidenceRevisionId === "string" ? ref.evidenceRevisionId : undefined;
      if (evidenceId === undefined || evidenceRevisionId === undefined) return;
      const linkedEvidence = evidences.get(entityKey(evidenceId, evidenceRevisionId));
      if (linkedEvidence === undefined) {
        errors.push(`claim evidence[${index}] must bind to an actual evidence revision`);
        return;
      }
      if (
        ref.contentId !== linkedEvidence.contentId ||
        ref.contentVersion !== linkedEvidence.contentVersion
      ) {
        errors.push(`claim evidence[${index}] content identity does not match evidence`);
      }
      if (ref.contentId !== contentId || ref.contentVersion !== contentVersion) {
        errors.push(`claim evidence[${index}] content identity does not match claim`);
      }
      const refContentAvailable = instant(
        ref.contentAvailableTime,
        `claim evidence[${index}].contentAvailableTime`,
        errors,
      );
      const evidenceContentAvailable = instant(
        linkedEvidence.contentAvailableTime,
        "evidence.contentAvailableTime",
        errors,
      );
      if (
        refContentAvailable !== undefined &&
        evidenceContentAvailable !== undefined &&
        refContentAvailable !== evidenceContentAvailable
      ) {
        errors.push(`claim evidence[${index}] content availability does not match evidence`);
      }
      const refEvidenceAvailable = instant(
        ref.evidenceAvailableTime,
        `claim evidence[${index}].evidenceAvailableTime`,
        errors,
      );
      const evidenceAvailable = instant(
        linkedEvidence.availableTime,
        "evidence.availableTime",
        errors,
      );
      if (
        refEvidenceAvailable !== undefined &&
        evidenceAvailable !== undefined &&
        refEvidenceAvailable !== evidenceAvailable
      ) {
        errors.push(`claim evidence[${index}] availability does not match evidence`);
      }
      if (
        ref.source !== linkedEvidence.source ||
        ref.sourceVersion !== linkedEvidence.sourceVersion
      ) {
        errors.push(`claim evidence[${index}] source does not match evidence`);
      }
      const claimAvailable = instant(item.availableTime, "claim.availableTime", errors);
      if (
        claimAvailable !== undefined &&
        evidenceAvailable !== undefined &&
        claimAvailable < evidenceAvailable
      ) {
        errors.push(`claim evidence[${index}] availability exceeds claim availability`);
      }
    });
  }

  for (const [index, item] of positions.entries()) {
    const claimId = typeof item.claimId === "string" ? item.claimId : undefined;
    const claimRevisionId =
      typeof item.claimRevisionId === "string" ? item.claimRevisionId : undefined;
    if (claimId === undefined || claimRevisionId === undefined) continue;
    const linkedClaim = claimsByKey.get(entityKey(claimId, claimRevisionId));
    if (linkedClaim === undefined) {
      errors.push(`positionClaims[${index}] must bind to an actual claim revision`);
      continue;
    }
    if (item.kolId !== linkedClaim.kolId || item.instrumentId !== linkedClaim.instrumentId) {
      errors.push(`positionClaims[${index}] identity does not match claim`);
    }
    const linkedFields = [
      "confidenceBps",
      "reviewStatus",
      "eventTime",
      "publishTime",
      "ingestTime",
      "processingTime",
      "source",
      "sourceVersion",
    ] as const;
    for (const field of linkedFields) {
      if (item[field] !== linkedClaim[field]) {
        errors.push(`positionClaims[${index}] ${field} does not match claim`);
      }
    }
    const claimAvailable = instant(linkedClaim.availableTime, "claim.availableTime", errors);
    const positionAvailable = instant(item.availableTime, "positionClaim.availableTime", errors);
    if (
      claimAvailable !== undefined &&
      positionAvailable !== undefined &&
      positionAvailable < claimAvailable
    ) {
      errors.push(`positionClaims[${index}] availability does not include claim availability`);
    }
  }
}

export function validateKolDomainSnapshotPayload(input: unknown): ValidationResult {
  const payload = record(input);
  if (payload === null) return { valid: false, errors: ["snapshot must be an object"] };
  const errors: string[] = [];
  for (const key of Object.keys(payload).sort()) {
    if (!SNAPSHOT_FIELDS.includes(key as (typeof SNAPSHOT_FIELDS)[number]))
      errors.push(`unknown field: ${key}`);
  }
  const content = collection(payload, "content", errors);
  const evidence = collection(payload, "evidence", errors);
  const claims = collection(payload, "claims", errors);
  const positions = collection(payload, "positionClaims", errors);
  content.forEach((item, index) =>
    prefixed(validateKolContentPayload(item), `content[${index}]`, errors),
  );
  evidence.forEach((item, index) =>
    prefixed(validateKolEvidencePayload(item), `evidence[${index}]`, errors),
  );
  claims.forEach((item, index) =>
    prefixed(validateKolClaimPayload(item), `claims[${index}]`, errors),
  );
  positions.forEach((item, index) =>
    prefixed(validateKolPositionClaimPayload(item), `positionClaims[${index}]`, errors),
  );
  validateRevisionGraph(content, "content", "contentId", errors);
  validateRevisionGraph(evidence, "evidence", "evidenceId", errors);
  validateRevisionGraph(claims, "claims", "claimId", errors);
  validateRevisionGraph(positions, "positionClaims", "positionClaimId", errors);
  validateLinks(content, evidence, claims, positions, errors);
  return { valid: errors.length === 0, errors };
}

function cloneJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => cloneJson(item));
  if (value !== null && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(object).map(([key, nested]) => [key, cloneJson(nested)]),
    );
  }
  return value;
}

function deepFreeze(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) return value;
  if (Array.isArray(value)) {
    value.forEach((item) => deepFreeze(item));
  } else {
    Object.values(value as Record<string, unknown>).forEach((item) => deepFreeze(item));
  }
  return Object.freeze(value);
}

function freezeRecords(records: readonly JsonRecord[]): readonly FrozenRecord[] {
  const cloned = records.map((item) => deepFreeze(cloneJson(item)) as FrozenRecord);
  return Object.freeze(cloned);
}

function snapshotFromRecords(
  content: readonly JsonRecord[],
  evidence: readonly JsonRecord[],
  claims: readonly JsonRecord[],
  positions: readonly JsonRecord[],
): KolDomainSnapshot {
  return Object.freeze({
    content: freezeRecords(content),
    evidence: freezeRecords(evidence),
    claims: freezeRecords(claims),
    positionClaims: freezeRecords(positions),
  });
}

export function parseKolDomainSnapshotPayload(input: unknown): KolDomainSnapshot {
  const validation = validateKolDomainSnapshotPayload(input);
  if (!validation.valid)
    throw new Error(`invalid KOL domain snapshot: ${validation.errors.join("; ")}`);
  const payload = record(input);
  if (payload === null) throw new TypeError("snapshot must be an object");
  return snapshotFromRecords(
    collection(payload, "content", []),
    collection(payload, "evidence", []),
    collection(payload, "claims", []),
    collection(payload, "positionClaims", []),
  );
}

function latestVisible(
  records: readonly FrozenRecord[],
  entityIdField: string,
  decisionMilliseconds: number,
): readonly FrozenRecord[] {
  const latest = new Map<string, FrozenRecord>();
  for (const item of records) {
    const entityId = typeof item[entityIdField] === "string" ? item[entityIdField] : undefined;
    const availableMilliseconds = instant(item.availableTime, "availableTime", []);
    if (
      entityId === undefined ||
      availableMilliseconds === undefined ||
      availableMilliseconds > decisionMilliseconds
    )
      continue;
    const previous = latest.get(entityId);
    const previousMilliseconds =
      previous === undefined ? undefined : instant(previous.availableTime, "availableTime", []);
    if (previousMilliseconds === undefined || availableMilliseconds > previousMilliseconds)
      latest.set(entityId, item);
  }
  return Object.freeze(
    [...latest.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([, value]) => value),
  );
}

export function selectKolDomainSnapshotAt(input: unknown, decisionTime: string): KolDomainSnapshot {
  const decisionMilliseconds = instant(decisionTime, "decisionTime", []);
  if (decisionMilliseconds === undefined)
    throw new TypeError("decisionTime must be timezone-aware");
  const snapshot = parseKolDomainSnapshotPayload(input);
  return snapshotFromRecords(
    latestVisible(snapshot.content, "contentId", decisionMilliseconds),
    latestVisible(snapshot.evidence, "evidenceId", decisionMilliseconds),
    latestVisible(snapshot.claims, "claimId", decisionMilliseconds),
    latestVisible(snapshot.positionClaims, "positionClaimId", decisionMilliseconds),
  );
}
