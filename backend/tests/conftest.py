from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Base
import app.services.storage_service as storage_service
import app.services.trip_service as trip_service


@pytest.fixture(autouse=True)
def isolate_tests_from_development_database(monkeypatch):
    """Give every test a fresh in-memory SQLite database."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    monkeypatch.setattr(storage_service, "engine", test_engine)
    monkeypatch.setattr(storage_service, "SessionLocal", test_session_local)
    monkeypatch.setattr(storage_service, "_db_initialized", False)
    Base.metadata.create_all(bind=test_engine)
    storage_service._db_initialized = True

    yield

    test_engine.dispose()


@pytest.fixture(autouse=True)
def isolate_trip_generation_from_external_services(monkeypatch):
    """Keep unit/API tests deterministic and independent from paid network APIs."""

    contexts = [
        "大理古城适合慢游、拍照和体验当地美食。",
        "大理洱海生态廊道适合骑行，喜洲古镇适合安排半日游。",
    ]

    def empty_usage() -> dict[str, int]:
        return {"prompt_tokens": 0, "completion_tokens": 0}

    monkeypatch.setattr(trip_service, "ENABLE_AMAP_ENRICHMENT", False)
    monkeypatch.setattr(
        trip_service,
        "collect_trip_context",
        lambda **kwargs: (
            contexts,
            empty_usage(),
            empty_usage(),
            empty_usage(),
        ),
    )
    monkeypatch.setattr(
        trip_service,
        "generate_planner_draft",
        lambda request, rag_contexts, day_count: (None, empty_usage()),
    )
