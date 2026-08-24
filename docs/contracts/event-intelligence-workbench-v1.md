# Event Intelligence Workbench V1

- `GET /v1/event-intelligence/events`: versioned `MarketEvent` query with date, type, canonical instrument, confidence and
  bounded limit filters.
- `GET /v1/event-intelligence/hot-topics`: latest snapshot per topic at or before required `asOf`, with lifecycle and score
  filters.
- `POST /v1/event-feedback`: append-only, authenticated human feedback from P3-N09.

PostgreSQL payloads are validated before crossing the API boundary. `market_events` and `hot_topic_snapshots` are immutable
read models keyed by content-addressed IDs; a new model, prompt, algorithm or policy version inserts new rows rather than
overwriting historical facts. Event evidence excerpts are rendered with source, half-open offsets and availability time;
the page never exposes raw object-store paths or provider credentials.

The Web route is `/event-workbench`. It renders loading, empty, error, forbidden and success states; uses Asia/Shanghai for
display only while retaining UTC contract timestamps; labels model confidence explicitly and keeps feedback outside the
fact layer until reviewed and promoted into a new evaluation dataset version.
