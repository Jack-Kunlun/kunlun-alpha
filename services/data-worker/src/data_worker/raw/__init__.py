"""Raw data landing zone.

Every external provider response is stored immutably by source and collection
date. The raw zone never mixes normalized results in — it only holds the
original payload plus a manifest that locates the source and request.
"""

from data_worker.raw.manifest import RawObjectManifest, sanitize_request_identity
from data_worker.raw.replay import decode_json, replay, replay_json
from data_worker.raw.storage import (
    CaptureConflictError,
    LocalFileStorage,
    RawIntegrityError,
    RawStorage,
    RawStorageError,
)

__all__ = [
    "CaptureConflictError",
    "decode_json",
    "LocalFileStorage",
    "RawObjectManifest",
    "RawIntegrityError",
    "RawStorageError",
    "RawStorage",
    "replay",
    "replay_json",
    "sanitize_request_identity",
]
