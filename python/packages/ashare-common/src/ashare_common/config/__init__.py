from pydantic_settings import BaseSettings


class ServiceConfig(BaseSettings):
    """Base configuration shared by all services."""

    model_config = {"env_prefix": "KUNLUN_", "extra": "forbid"}

    service_name: str = "kunlun"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080
    shutdown_timeout_seconds: float = 10.0
