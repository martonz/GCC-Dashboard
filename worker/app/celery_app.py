from celery import Celery
from celery.schedules import crontab
from redbeat import RedBeatScheduler

from .settings import get_settings

settings = get_settings()

app = Celery(
    "gcc_dashboard",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=120,  # raise SoftTimeLimitExceeded after 2 min
    task_time_limit=180,       # hard kill after 3 min
    redbeat_redis_url=settings.celery_broker_url,  # includes password from env
    beat_scheduler="redbeat.RedBeatScheduler",
    beat_schedule={
        "ingest-rss": {
            "task": "app.tasks.ingest_rss",
            "schedule": settings.rss_ingest_interval_minutes * 60,
        },
        "ingest-gdelt": {
            "task": "app.tasks.ingest_gdelt",
            "schedule": settings.gdelt_ingest_interval_minutes * 60,
        },
        "compute-risk": {
            "task": "app.tasks.compute_risk",
            "schedule": settings.risk_compute_interval_minutes * 60,
        },
    },
)
