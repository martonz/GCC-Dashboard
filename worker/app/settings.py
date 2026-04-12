from __future__ import annotations
import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/wardb"
    )

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Discord
    discord_webhook_url: str = ""

    # Risk
    risk_window_minutes: int = 60
    alert_risk_threshold: int = 70
    alert_delta_threshold: int = 20
    alert_kinetic_hits: int = 3
    alert_cooldown_minutes: int = 30

    # RSS
    rss_queries: str = (
        '["Iran US strike missile", '
        '"Strait Hormuz tanker ship", '
        '"Iran nuclear IAEA ceasefire"]'
    )

    # GDELT
    gdelt_queries: str = (
        '["Iran United States war strike missile Hormuz", '
        '"Iran nuclear ceasefire diplomacy"]'
    )
    gdelt_max_records: int = 100
    gdelt_retry_warn_threshold: int = 3

    # Scheduling (minutes)
    rss_ingest_interval_minutes: int = 2
    gdelt_ingest_interval_minutes: int = 5
    risk_compute_interval_minutes: int = 5

    # YouTube streams (JSON array of {name, url})
    youtube_streams: str = (
        '[{"name":"Al Jazeera English","url":"https://www.youtube.com/@AlJazeeraEnglish/live"},'
        '{"name":"BBC News","url":"https://www.youtube.com/@BBCNews/live"},'
        '{"name":"CNN","url":"https://www.youtube.com/@CNN/live"},'
        '{"name":"Sky News","url":"https://www.youtube.com/@SkyNews/live"},'
        '{"name":"France 24","url":"https://www.youtube.com/@FRANCE24/live"}]'
    )

    def get_rss_queries(self) -> list[str]:
        try:
            return json.loads(self.rss_queries)
        except json.JSONDecodeError as exc:
            raise ValueError(f"RSS_QUERIES is not valid JSON: {exc}") from exc

    def get_gdelt_queries(self) -> list[str]:
        try:
            return json.loads(self.gdelt_queries)
        except json.JSONDecodeError as exc:
            raise ValueError(f"GDELT_QUERIES is not valid JSON: {exc}") from exc

    def get_youtube_streams(self) -> list[dict]:
        try:
            return json.loads(self.youtube_streams)
        except json.JSONDecodeError as exc:
            raise ValueError(f"YOUTUBE_STREAMS is not valid JSON: {exc}") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()
