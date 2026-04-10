from __future__ import annotations
import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_base_url: str = "http://localhost:8000"

    youtube_streams: str = (
        '[{"name":"Al Jazeera English","url":"https://www.youtube.com/@AlJazeeraEnglish/live"},'
        '{"name":"BBC News","url":"https://www.youtube.com/@BBCNews/live"},'
        '{"name":"CNN","url":"https://www.youtube.com/@CNN/live"},'
        '{"name":"Sky News","url":"https://www.youtube.com/@SkyNews/live"},'
        '{"name":"France 24","url":"https://www.youtube.com/@FRANCE24/live"}]'
    )

    alert_risk_threshold: int = 70
    alert_delta_threshold: int = 20

    def get_youtube_streams(self) -> list[dict]:
        return json.loads(self.youtube_streams)


@lru_cache
def get_settings() -> Settings:
    return Settings()
