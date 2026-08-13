"""Raw object manifest.

A manifest describes one landed raw object: where it came from, when it was
collected, what request produced it, and how to verify its integrity. The
``object_id`` is the SHA-256 of the content, which makes objects content-
addressed and immutable — a repeated fetch of identical content maps to the
same object and never overwrites a previous one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast


@dataclass(frozen=True)
class RawObjectManifest:
    """Metadata for one immutable raw object."""

    object_id: str
    source: str
    date: str
    request: str
    checksum: str
    size: int
    content_type: str = "application/octet-stream"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> RawObjectManifest:
        return cls(
            object_id=str(raw["object_id"]),
            source=str(raw["source"]),
            date=str(raw["date"]),
            request=str(raw["request"]),
            checksum=str(raw["checksum"]),
            size=cast(int, raw["size"]),
            content_type=str(raw.get("content_type", "application/octet-stream")),
        )
