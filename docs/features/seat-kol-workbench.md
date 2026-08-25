# Seat and KOL workbench

P4-N10 adds the read-only `/api/v1/seat-kol/workbench` endpoint and the
`/seat-kol` Web route. The response is versioned as
`seat-kol-workbench-v1` and supports point-in-time `asOf`, entity, review-state,
and text filters.

Every displayed metric must carry `algorithmVersion`, `policyVersion`,
`sampleCount`, `confidenceBps`, and `dataCutoffTime`. Evidence and timeline
records keep their own source version and availability time.

KOL Claims represent reviewed public wording. They are never broker-confirmed
trades, orders, fills, positions, or account facts. Cooccurrence only means two
entities appeared together in the configured public-data sample.

Until a persisted workbench projection is connected, non-production server
runs expose an explicitly labeled sanitized `LOCAL_PREVIEW` snapshot. Production
defaults to an empty repository rather than presenting preview data as real.
