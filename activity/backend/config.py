from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The single .env lives at the bamboozled-bot repo root (three levels up from here).
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    BOT_INTERNAL_API_URL: str = "http://localhost:8080"
    BOT_INTERNAL_SECRET: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""
    DB_PATH: str = "data/bamboozled_activity.db"

    # The shared .env also holds bot/frontend variables; ignore the ones not declared here.
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")


settings = Settings()
