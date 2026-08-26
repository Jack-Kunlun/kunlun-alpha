# BenchmarkSeriesPoint v1

`BenchmarkSeriesPoint` is the public, reference-only point contract for a
benchmark series used by later point-in-time features. `schemaVersion` is the
literal `benchmark-series-point-v1`. `benchmarkId` and
`PreciousMetalFund.benchmarkSeriesId` use the exact versioned ASCII form
`benchmark:v1:<namespace>:<key>`. Namespace and key are lowercase ASCII
identifiers; they are not display labels and must not be derived from a fund
name or `benchmarkOrTrackingIndex`. Missing, null, whitespace, Unicode,
uppercase, legacy, or otherwise invalid bindings are unavailable.

Each point carries an ISO 4217 `currency`, explicit `priceBasis`, positive
fixed-point decimal `referenceValue` on the wire as a JSON string. The Python
domain field is `Decimal`; TypeScript keeps the wire type as `string`. JSON
numbers, floats, integers, booleans, zero, negative values, scientific
notation, leading plus signs, and surrounding whitespace are invalid. The
timestamps are strict RFC3339 strings with `T`, a real calendar date, valid
00-23/00-59/00-59 time fields, optional 1-6 fractional digits, and `Z` or a
valid `+/-HH:MM` offset. The required time order is:

```text
eventTime <= ingestTime <= availableTime <= processingTime
```

`source`, `sourceRevision`, `rawObjectId`, and `payloadDigest` preserve the
source lineage. `referenceOnly` is strictly the JSON literal `true`; the value
is research reference data and never an executable price or an order input.

`PreciousMetalFund.benchmarkSeriesId` is an optional explicit binding for
legacy compatibility. A missing or null binding is valid metadata but feature
consumers must fail closed. Consumers match only after validating both
contracts and an exact
`benchmarkSeriesId == BenchmarkSeriesPoint.benchmarkId` pair; they must never
use `benchmarkOrTrackingIndex` or fund display text as a fallback.

P5-N14 consumers own the policy decision. They may calculate a feature only
when the benchmark is present in a versioned policy allowlist, the canonical
binding is an exact match, `referenceOnly` is true, the observation is
point-in-time visible, currencies are compatible, and basis/currency are
consistent across the calculation window. Otherwise the output must be
`unavailable` or `degraded`; no default basis, currency, or display-name
inference is permitted. This contract does not implement the P5-N14 policy.
