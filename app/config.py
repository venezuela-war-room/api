from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto"
    master_admin_key: str = "change-me-in-production"
    cors_origins: list[str] = ["*"]
    debug: bool = False


settings = Settings()
