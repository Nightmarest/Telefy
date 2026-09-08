"""Runtime configuration loaded from environment / .env file."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")
    owner_id: int = Field(..., alias="OWNER_ID")
    channel_id: str = Field(..., alias="CHANNEL_ID")

    db_path: str = Field("./state.sqlite", alias="DB_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    api_base: str = Field("https://api.telegram.org", alias="API_BASE")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
