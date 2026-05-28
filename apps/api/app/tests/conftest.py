from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings
from app.db.base import Base
from app.models import all_models  # noqa: F401


@pytest.fixture(autouse=True)
def disable_remote_refiners_for_tests(monkeypatch):
    for key in list(os.environ):
        if key.startswith("LYRICS_REFINER_") or key.startswith("PROMPT_REFINER_"):
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
