# Sector rotation V2

## Point-in-time inputs

SectorTaxonomy retains every non-overlapping historical interval. At a query
date it filters by effective interval and available_time, then resolves only
overlapping records by configured source priority. Equal-authority conflicts
fail closed.

SectorBarObservation binds a normalized Bar to previous_close, available_time,
integer revision, source version and evidence id. Snapshot canonicalization
filters availability before choosing the highest revision. Same-identity and
same-revision payload conflicts fail closed.

## SectorSnapshot V2

sector_snapshot_v2 computes, for the resolver-owned effective member set:

- average raw-price change;
- average change speed per elapsed minute where a prior bar exists;
- Decimal turnover;
- advancing breadth;
- deterministic leader and strength;
- sample/member counts, worst included-bar freshness and coverage confidence;
- membership/bar source versions, evidence ids and explicit exclusions.

Batch input and reverse-arrival incremental input use the same canonicalizer.

## Lifecycle V1

LifecycleConfig is immutable and carries lifecycle_v1. Every transition stores
sector/timestamp, snapshot/config versions, sample and freshness fields,
evidence ids, confidence and a deterministic transition id. Illegal state jumps
fail closed.

## RotationEvent V2

Input timestamps are timezone-aware, UTC-normalized, sorted and deduplicated.
Conflicting duplicate timestamps fail closed. Empty strength maps are skipped;
ties are barriers rather than insertion-order winners. A transient lead run
cannot be removed in a way that fabricates a direct historical crossover.

Crossover and decay events carry a SHA-256 identity based on stable semantic
identity, versioned evidence-window boundaries, sample size, source versions
and evidence ids. Extending an overlapping replay window does not change an
already detected event id.
