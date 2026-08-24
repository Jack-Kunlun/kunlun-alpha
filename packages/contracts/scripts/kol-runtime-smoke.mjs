const kol = await import("@kunlun/contracts/kol");

const requiredExports = [
  "parseKolDomainSnapshotPayload",
  "validateKolDomainSnapshotPayload",
  "validateKolContentPayload",
];
for (const name of requiredExports) {
  if (typeof kol[name] !== "function") {
    throw new Error(`missing @kunlun/contracts/kol export: ${name}`);
  }
}

const validation = kol.validateKolDomainSnapshotPayload({
  content: [],
  evidence: [],
  claims: [],
  positionClaims: [],
});
if (!validation.valid) throw new Error(validation.errors.join("; "));

const snapshot = kol.parseKolDomainSnapshotPayload({
  content: [],
  evidence: [],
  claims: [],
  positionClaims: [],
});
if (!Array.isArray(snapshot.content)) throw new Error("aggregate parser did not return a snapshot");

console.log("@kunlun/contracts/kol runtime smoke passed");
