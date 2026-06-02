from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "event-gateway"
    version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./data/gateway.db"

    account_service_url: str = "http://localhost:8001"
    account_call_timeout_seconds: float = 2.0
    account_connect_timeout_seconds: float = 0.5

    retry_attempts: int = 3
    retry_min_wait_seconds: float = 0.1
    retry_max_wait_seconds: float = 1.5

    breaker_fail_max: int = 5
    breaker_reset_timeout_seconds: int = 30

    outbox_poll_interval_seconds: float = 5.0
    outbox_enabled: bool = True

    rate_limit_per_minute: int = 100
    rate_limit_enabled: bool = True

    otel_exporter_otlp_endpoint: str | None = None
    otel_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
