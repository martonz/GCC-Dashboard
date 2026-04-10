from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/wardb"
    )

    # Risk thresholds
    risk_window_minutes: int = 60
    alert_risk_threshold: int = 70
    alert_delta_threshold: int = 20
    alert_kinetic_hits: int = 3
    alert_cooldown_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
