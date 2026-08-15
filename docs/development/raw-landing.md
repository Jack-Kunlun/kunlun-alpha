# P1-R03 原始响应落地与重放

Raw landing separates immutable content objects from per-response capture
manifests:

- `objects/<sha256>` stores one complete response byte stream. Identical bytes
  are deduplicated by checksum only.
- `index/<source>/<date>/<capture_id>.<manifest_sha256>.json` stores one
  content-bound manifest for every response. The filename capture id and
  canonical-manifest digest are verified on every list/read operation.
- `pending/<source>/<date>/<capture_id>.<intent_sha256>.json` is an atomic
  intent written before object publication. A retry can finish an interrupted
  transaction without leaving an object without provenance.

Legacy P1-N05 files named `index/<source>/<date>/<object_id>.json` remain
read-only compatible. The filename must equal both the manifest object id and
checksum. Because the old format did not record capture identity or collection
times, the reader assigns `legacy-object-<digest-prefix>` and uses the
deterministic date-partition timestamp at `00:00:00 UTC`; this is a fallback,
not the original acquisition time. The old format cannot recover provenance
for multiple requests that shared one object. New writes never rewrite legacy
files and use only the content-bound format above.

## Capture and idempotency

`capture_id` is the explicit event/idempotency boundary. Reusing it with the
same source, date, sanitized request, object checksum, size, and content type
returns the original manifest; a different event raises
`CaptureConflictError` before a new object is written. `idempotency_key` is an
optional caller key that derives a bounded, stable `idem-<digest>` capture id.
When neither is supplied, each response receives a fresh UUID capture id even
when its bytes match another response.

Capture transactions hold a capture-level OS lock from preflight through final
verification. The lock marker is intentionally persistent, while ownership is
the OS lock (POSIX `fcntl.flock`, Windows `msvcrt.locking`); a crashed process
does not leave a lock that must be stolen by mtime. Acquisition is bounded and
fails closed. Target publication also uses a hashed sibling OS lock, writes a
complete short-named temporary file, and publishes it atomically without
overwriting an existing target. Lock markers are harmless hidden files.

## Manifest fields and request privacy

Each manifest records `capture_id`, source/date, a sanitized request identity,
`object_id`, checksum, byte size, content type, timezone-aware `ingest_time`,
and `available_time`. `available_time` cannot precede `ingest_time`.

Only the first request line (method and target) is parsed. The path is replaced
with `path_sha256=<digest>`, so account identifiers and path credentials never
enter storage. Query values are allowlisted to `exchange`, `cursor`, `page`,
`limit`, `date`, and `code`; unknown keys are dropped. Only an ASCII-numeric
cursor is retained as-is. Any opaque or non-numeric cursor, even a short
URL-safe token, becomes a stable `sha256-<digest>` value. Other unsafe or
oversized allowlisted values are dropped. Headers and bodies are never
persisted.

Source/date/capture identifiers are ASCII path components with a portable
length limit. Separators, dot segments, controls, trailing dots/spaces, and
Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `CLOCK$`, `COM1`-`COM9`, and
`LPT1`-`LPT9`, including extensions) are rejected on every platform before
filesystem access.

## Verification and replay

`get` and both replay paths verify the stored checksum and manifest byte size.
Corrupt or truncated objects raise `RawIntegrityError`. `replay` emits every
capture in `(ingest_time, capture_id)` order, including captures that share one
object. `decode_json`/`replay_json` use `parse_float=Decimal` so price-sensitive
JSON does not enter the normalizer as binary floats.

Example:

```python
manifest = storage.put(
    "provider-x",
    "2026-08-13",
    "GET /bars?exchange=SH",
    response_bytes,
    capture_id="provider-x-20260813-0001",
    content_type="application/json",
)
```
