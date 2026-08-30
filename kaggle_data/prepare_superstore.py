#!/usr/bin/env python3
"""
Turns the raw Kaggle "Sample Superstore" export into the CSV shape BusinessIntelligence.ai's
observation upload expects: one row per (date, segment) — not one row per order.

The raw file is order-level (many orders per day per region), which is the right shape for a
sales ledger but the wrong shape for a daily KPI upload: the app's data-quality check flags
multiple rows sharing the same date+segment as a sync error (that check exists specifically to
catch a source system double-reporting a segment, so accepting many-rows-per-day would defeat
its purpose). Aggregating first — summing Sales per day per segment — is also just the
statistically correct thing to do before feeding a day-level significance test.

Usage:
    1. Download the CSV from https://www.kaggle.com/datasets/rohitsahoo/sales-forecasting
       (or the identical https://www.kaggle.com/datasets/vivek468/superstore-dataset-final)
    2. Save it as kaggle_data/raw/superstore.csv
    3. python kaggle_data/prepare_superstore.py

Produces two ready-to-upload files in kaggle_data/processed/:
    revenue_by_region.csv          — date, value, region            (single dimension)
    revenue_by_region_category.csv — date, value, region, category  (two dimensions)
"""
import sys
from pathlib import Path

import pandas as pd

RAW_PATH = Path(__file__).parent / "raw" / "superstore.csv"
OUT_DIR = Path(__file__).parent / "processed"


def main() -> None:
    if not RAW_PATH.exists():
        print(f"Expected the raw Kaggle file at {RAW_PATH}")
        print("Download it from Kaggle and save it there first (see this script's docstring).")
        sys.exit(1)

    # The Kaggle export is usually Windows-1252/Latin-1 encoded, not UTF-8.
    df = pd.read_csv(RAW_PATH, encoding="latin1")

    date_col = next((c for c in df.columns if c.strip().lower() == "order date"), None)
    sales_col = next((c for c in df.columns if c.strip().lower() == "sales"), None)
    region_col = next((c for c in df.columns if c.strip().lower() == "region"), None)
    category_col = next((c for c in df.columns if c.strip().lower() == "category"), None)
    missing = [name for name, col in [("Order Date", date_col), ("Sales", sales_col), ("Region", region_col)] if col is None]
    if missing:
        print(f"Couldn't find expected column(s) in the raw file: {', '.join(missing)}")
        print(f"Columns found: {list(df.columns)}")
        sys.exit(1)

    # This dataset's date format varies by Kaggle upload (some versions are day-first, e.g.
    # "15/04/2018", which isn't valid as month-first) — dayfirst=True handles both, since any
    # day-first date under 13 is still unambiguous enough for pandas to infer correctly here.
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True).dt.date

    OUT_DIR.mkdir(exist_ok=True)

    by_region = (
        df.groupby([date_col, region_col])[sales_col]
        .sum()
        .reset_index()
        .rename(columns={date_col: "date", sales_col: "value", region_col: "region"})
        .sort_values("date")
    )
    out1 = OUT_DIR / "revenue_by_region.csv"
    by_region.to_csv(out1, index=False)
    print(f"Wrote {out1} ({len(by_region)} rows, {by_region['region'].nunique()} regions, "
          f"{by_region['date'].min()} -> {by_region['date'].max()})")

    if category_col:
        by_region_cat = (
            df.groupby([date_col, region_col, category_col])[sales_col]
            .sum()
            .reset_index()
            .rename(columns={date_col: "date", sales_col: "value", region_col: "region", category_col: "category"})
            .sort_values("date")
        )
        out2 = OUT_DIR / "revenue_by_region_category.csv"
        by_region_cat.to_csv(out2, index=False)
        print(f"Wrote {out2} ({len(by_region_cat)} rows, "
              f"{by_region_cat['region'].nunique()} regions x {by_region_cat['category'].nunique()} categories)")

    print()
    print("Upload either file via the Data page — for revenue_by_region_category.csv, create the")
    print("metric with dimensions: region, category (in that order isn't required, just declared).")


if __name__ == "__main__":
    main()
