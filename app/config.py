from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto"
    master_admin_key: str = "change-me-in-production"
    cors_origins: list[str] = ["*"]
    debug: bool = False
    environment: str = "production"
    posthog_api_key: str | None = None
    posthog_host: str = "https://us.i.posthog.com"

    @field_validator("database_url")
    @classmethod
    def force_asyncpg_driver(cls, v: str) -> str:
        # Managed Postgres providers hand out bare `postgres://` / `postgresql://`
        # URLs. SQLAlchemy's async engine needs the asyncpg driver explicitly, or
        # it falls back to psycopg2 (not installed) and import fails at startup.
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v


settings = Settings()
