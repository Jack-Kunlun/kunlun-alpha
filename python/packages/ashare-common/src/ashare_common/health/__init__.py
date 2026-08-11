from datetime import UTC, datetime

from pydantic import BaseModel, Field


class HealthStatus(BaseModel):
    status: str = "ok"
    service: str
    version: str = "0.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class HealthHandler:
    """Stateless health-check responder."""

    def __init__(self, service: str, version: str = "0.0.0") -> None:
        self._service = service
        self._version = version

    def check(self) -> HealthStatus:
        return HealthStatus(service=self._service, version=self._version)
