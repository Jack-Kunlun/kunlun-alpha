"""Raw data landing zone.

Every external provider response is stored immutably by source and collection
date. The raw zone never mixes normalized results in — it only holds the
original payload plus a manifest that locates the source and request.
"""

from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.replay import replay
from data_worker.raw.storage import LocalFileStorage, RawStorage

__all__ = [
    "LocalFileStorage",
    "RawObjectManifest",
    "RawStorage",
    "replay",
]
