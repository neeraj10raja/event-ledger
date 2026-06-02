from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "account-service"
    version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8001

    database_url: str = "sqlite+aiosqlite:///./data/account.db"

    otel_exporter_otlp_endpoint: str | None = None
    otel_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
