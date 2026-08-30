import os

# The test suite must stay deterministic and offline regardless of what's in the developer's
# .env — force the LLM narrative path off *before* any app module (narrative.py reads these at
# import time into a module-level Settings singleton) gets imported, so tests always exercise
# the deterministic template writer, never a live Gemini/Anthropic/OpenRouter call.
os.environ["GEMINI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data.playbooks_seed import seed as seed_playbooks
from app.data.synthetic import generate as generate_synthetic
from app.data.users_seed import seed as seed_users
from app.db import Base


@pytest.fixture(scope="session")
def db_engine():
    # StaticPool: FastAPI's TestClient runs sync route handlers in a worker thread, and a plain
    # SQLite ":memory:" engine hands each thread its own (schema-less) connection by default —
    # StaticPool keeps every checkout on the single real connection regardless of thread. This
    # also lets a detection job's background thread (app/pipeline/jobs.py) open its own Session
    # against the same in-memory database via a sessionmaker bound to this engine.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="session")
def db_session(db_engine):
    session = sessionmaker(bind=db_engine)()
    generate_synthetic(session)
    seed_playbooks(session)
    seed_users(session)
    yield session
    session.close()


@pytest.fixture
def client(db_session, db_engine):
    """A FastAPI TestClient wired to the shared in-memory fixture DB — used by any test that
    needs to drive requests through the real HTTP/routing/dependency layer (RBAC, logging on
    real endpoints), not just call pipeline functions directly."""
    from fastapi.testclient import TestClient

    from app.db import get_db, get_session_factory
    from app.main import app
    from app.models import Metric, Report
    from app.pipeline.orchestrator import run_detection

    # A couple of tests need a Sales-routed and a Support-routed report to exist — don't rely
    # on test_pipeline.py having already run first (pytest's collection order isn't a contract
    # this should depend on).
    if db_session.query(Report).filter(Report.routed_to == "Sales").first() is None:
        run_detection(db_session, db_session.query(Metric).filter(Metric.key == "revenue").one())
    if db_session.query(Report).filter(Report.routed_to == "Support").first() is None:
        run_detection(db_session, db_session.query(Metric).filter(Metric.key == "csat").one())

    app.dependency_overrides[get_db] = lambda: db_session
    # Detection jobs run on a background thread against a fresh Session — point that at the
    # same in-memory test engine rather than the app's real (file-based) engine.
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(bind=db_engine)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
