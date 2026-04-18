from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=5,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from .models import Item, RiskTimeseries, Alert  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Lightweight schema upgrade for deployments without a migration tool.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS direct_url TEXT"))
