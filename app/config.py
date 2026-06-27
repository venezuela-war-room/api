from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto"
    master_admin_key: str = "change-me-in-production"
    cors_origins: list[str] = ["*"]
    debug: bool = False

    # ── Geocoding (OpenStreetMap Nominatim) ──────────────────────────────────
    # Fills instalacion.direccion / lat / lon when a record arrives without an
    # address. The PUBLIC endpoint forbids parallel requests (~1 req/sec, valid
    # User-Agent required), so geocoding_concurrency defaults to 1. Raise it only
    # when nominatim_base_url points at a self-hosted/commercial instance.
    geocoding_enabled: bool = True
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "terremoto-venezuela-war-room/0.1 (+https://github.com/terremoto-venezuela-war-room)"
    geocoding_timeout: float = 5.0
    geocoding_concurrency: int = 1
    geocoding_country_codes: str = "ve"
    geocoding_request_delay: float = 1.0  # seconds between Nominatim calls (politeness)

    # Background geocoding worker (app/geocoding_worker.py), started in the app lifespan.
    geocoding_worker_enabled: bool = True
    geocoding_worker_interval: float = 60.0  # idle sleep when no facilities are pending
    geocoding_batch_size: int = 10  # facilities claimed per cycle

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
