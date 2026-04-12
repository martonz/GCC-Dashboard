from __future__ import annotations
import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — required, no default
    database_url: str

    # Celery — required, no default
    celery_broker_url: str
    celery_result_backend: str

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
        '["Iran US war strike missile Hormuz", '
        '"Iran nuclear ceasefire diplomacy"]'
    )
    gdelt_max_records: int = 100

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
        return json.loads(self.rss_queries)

    def get_gdelt_queries(self) -> list[str]:
        return json.loads(self.gdelt_queries)

    def get_youtube_streams(self) -> list[dict]:
        return json.loads(self.youtube_streams)


@lru_cache
def get_settings() -> Settings:
    return Settings()
