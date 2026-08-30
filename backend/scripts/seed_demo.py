#!/usr/bin/env python3
"""
Judge-demo dataset — drops/recreates the database, then seeds:
  - the playbook library and demo user accounts (same as the other seed scripts)
  - app/data/demo_scenarios.py's dataset: REAL Kaggle Superstore revenue history for four
    scenarios (validated / ambiguous / suppressed / data-quality), each its own metric, plus a
    synthetic companion ticket-volume metric and synthetic demonstration text evidence — see
    that module's docstring for exactly what's real vs. synthetic and why.

Requires kaggle_data/processed/revenue_by_region_category.csv to already exist — run
`python kaggle_data/prepare_superstore.py` first if it doesn't (see that script's docstring for
where to get the raw Kaggle file; this script itself makes no network calls).

This is a one-click RESET: re-running it rebuilds the whole demo from scratch, deterministically
— the same four scenarios resolve to the same statuses every time (see README's Demo Setup
section for the exact expected status of each). It does NOT touch ANTHROPIC_API_KEY/
OPENROUTER_API_KEY — if one is configured, reports use the real LLM narrative writer; if not,
the deterministic template writer runs instead. Either way, which status each scenario resolves
to (validated/ambiguous/suppressed) never depends on the LLM — only the prose does.

Usage: python scripts/seed_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.demo_scenarios import generate as generate_demo
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

        print("Loading demo dataset (real Kaggle Superstore revenue + synthetic demo evidence)...")
        info = generate_demo(db)
        window_start, window_end = info["window"]
        print(f"  anomaly window: {window_start} -> {window_end}")
        for scenario, key in info["metrics"].items():
            print(f"  {scenario:14s} -> metric '{key}'")

        from app.models import Metric
        from app.pipeline.orchestrator import run_detection

        print()
        print("Running detection across the four scenario metrics...")
        expected = {
            "demo_revenue_validated": "validated",
            "demo_revenue_ambiguous": "ambiguous",
            "demo_revenue_suppressed": ("suppressed_noise", "suppressed_data_quality"),
            "demo_revenue_data_quality": "suppressed_data_quality",
        }
        all_ok = True
        for key, want in expected.items():
            metric = db.query(Metric).filter(Metric.key == key).one()
            result = run_detection(db, metric)
            got = result["status"]
            want_set = {want} if isinstance(want, str) else set(want)
            ok = got in want_set
            all_ok = all_ok and ok
            flag = "OK" if ok else "MISMATCH"
            print(f"  {key:26s} -> {got:26s} (expected {'/'.join(want_set)}) [{flag}]")

        print()
        if all_ok:
            print("All four scenarios resolved as expected. Demo dataset ready.")
        else:
            print("WARNING: at least one scenario did not resolve as expected — see MISMATCH above.")
        print("Sign in as admin/admin123 and open the Dashboard, or jump straight to each")
        print("metric's page / Reports to walk through the four scenarios.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
