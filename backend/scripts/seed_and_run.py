#!/usr/bin/env python3
"""
Rebuilds the database from scratch: creates tables, seeds the playbook library and the demo
login accounts, and runs detection for every metric that already has data (none, on a fresh
database — you populate metrics and upload observations through the Data page after this).

Usage: python scripts/seed_and_run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.playbooks_seed import seed as seed_playbooks
from app.data.users_seed import seed as seed_users
from app.db import Base, SessionLocal, engine


def main() -> None:
    print("Dropping and recreating all tables...")
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("Seeding playbook library...")
        seed_playbooks(db)
        print("Seeding demo user accounts...")
        seed_users(db)

        from app.models import Metric
        from app.pipeline.orchestrator import run_detection

        metrics = db.query(Metric).all()
        if metrics:
            print("Running detection across all monitored metrics...")
            for metric in metrics:
                result = run_detection(db, metric)
                print(f"  {metric.key:24s} -> {result['status']}")
        print()
        print("Done. The database is empty of metrics — sign in as an admin and use the")
        print("Data page (/data) to create a metric and upload real observations/tickets.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
