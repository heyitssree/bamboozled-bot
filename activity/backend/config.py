from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_INTERNAL_API_URL: str = "http://localhost:8080"
    BOT_INTERNAL_SECRET: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    DB_PATH: str = "data/bamboozled_activity.db"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"


settings = Settings()
