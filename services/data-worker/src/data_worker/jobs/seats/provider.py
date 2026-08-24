"""Provider boundary for seat-list observations; no network implementation."""

from typing import Protocol

from data_worker.jobs.seats.models import SeatFetchRequest, SeatProviderBatch


class SeatListProvider(Protocol):
    def fetch(self, request: SeatFetchRequest) -> SeatProviderBatch:
        """Return one immutable provider batch for the requested point in time."""
        ...


__all__ = ["SeatListProvider"]
