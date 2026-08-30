#!/usr/bin/env python3
"""
E2E / dev-testing fixture ONLY — not part of the shipped app's normal startup.

Seeds the database with the deterministic synthetic dataset (app/data/synthetic.py) and runs
detection across it, reproducing the four known scenarios (validated / ambiguous / suppressed
noise / suppressed data-quality) that frontend/e2e/golden-path.spec.ts asserts against. The
real app (scripts/seed_and_run.py) no longer does this — it starts empty and is populated via
the Data page's CSV/Excel upload. This script exists purely so the e2e suite has a known,
reproducible UI to test against without hand-uploading megabyte-scale fixture files through a
browser automation tool.

Usage: python scripts/seed_test_fixture.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# This fixture backs the e2e suite (frontend/e2e/golden-path.spec.ts), which must stay
# deterministic — a live LLM call here would make report text (and therefore any assertion
# that touches it) depend on whatever OPENROUTER_API_KEY/ANTHROPIC_API_KEY happens to be sitting
# in the developer's real .env. Force the template writer regardless of what's configured
# there, same as backend/tests/conftest.py does for pytest.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

from app.data.playbooks_seed import seed as seed_playbooks
from app.data.synthetic import generate as generate_synthetic
from app.data.users_seed import seed as seed_users
from app.db import Base, SessionLocal, engine


def main() -> None:
    print("Dropping and recreating all tables...")
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("Generating synthetic dataset (structured + unstructured, 365 days)...")
        generate_synthetic(db)
        print("Seeding playbook library...")
        seed_playbooks(db)
        print("Seeding demo user accounts...")
        seed_users(db)

        from app.models import Metric
        from app.pipeline.orchestrator import run_detection

        print("Running detection across all seeded metrics...")
        for metric in db.query(Metric).all():
            result = run_detection(db, metric)
            print(f"  {metric.key:24s} -> {result['status']}")
        print("Done. This is test-fixture data — do not point a real deployment at this script.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
