from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Base

url = make_url(settings.database_url)
connect_args = {}

if url.get_backend_name() == "sqlite":
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30   # wait up to 30 s if another process holds a write lock
    if url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
