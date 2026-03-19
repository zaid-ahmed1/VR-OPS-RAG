#!/usr/bin/env python3
"""
Migrate trainee_performance_sample.xlsx into the vrops Postgres database.

Usage:
    pip install psycopg2-binary openpyxl pandas
    python migrate_xlsx.py --db "postgresql://vrops_authenticator:PASSWORD@localhost:5432/vrops" \
                           --xlsx /opt/vr-ops-rag/dashboard/trainee_performance_sample.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

STEP_NUMBERS = list(range(1, 9))


def load_xlsx(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Number of errors"] = pd.to_numeric(df["Number of errors"], errors="coerce").fillna(0).astype(int)
    df["Completion Time (mins)"] = pd.to_numeric(df["Completion Time (mins)"], errors="coerce").fillna(0)
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != "" and df["Date"].notna() if False else df["Date"].notna()]
    df = df[df["Name"].str.strip() != ""]
    for step in STEP_NUMBERS:
        col = f"Step {step} Appraisal"
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title()
            df.loc[~df[col].isin(["Right", "Wrong"]), col] = None
        time_col = f"Step {step} Time"
        if time_col in df.columns:
            df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
    return df.reset_index(drop=True)


def migrate(conn, df: pd.DataFrame) -> None:
    cur = conn.cursor()

    upserted = 0
    for _, row in df.iterrows():
        name = row["Name"]

        # Upsert trainee
        cur.execute(
            "INSERT INTO trainees (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (name,),
        )
        trainee_id = cur.fetchone()[0]

        # Insert session
        cur.execute(
            """
            INSERT INTO sessions (trainee_id, date, completion_time_mins, total_errors)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (trainee_id, row["Date"].isoformat(), float(row["Completion Time (mins)"]), int(row["Number of errors"])),
        )
        session_id = cur.fetchone()[0]

        # Insert steps
        step_rows = []
        for step in STEP_NUMBERS:
            appraisal = row.get(f"Step {step} Appraisal")
            time_val = row.get(f"Step {step} Time")
            appraisal = appraisal if appraisal in ("Right", "Wrong") else None
            time_val = float(time_val) if pd.notna(time_val) else None
            step_rows.append((session_id, step, time_val, appraisal))

        execute_values(
            cur,
            "INSERT INTO session_steps (session_id, step_number, time_mins, appraisal) VALUES %s",
            step_rows,
        )
        upserted += 1

    conn.commit()
    cur.close()
    print(f"Migrated {upserted} sessions.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate xlsx to Postgres")
    parser.add_argument("--db", required=True, help="PostgreSQL connection string")
    parser.add_argument(
        "--xlsx",
        default=str(Path(__file__).parent.parent / "dashboard" / "trainee_performance_sample.xlsx"),
        help="Path to xlsx file",
    )
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"ERROR: xlsx not found at {xlsx_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {xlsx_path} ...")
    df = load_xlsx(xlsx_path)
    print(f"  {len(df)} rows loaded.")

    print(f"Connecting to database ...")
    conn = psycopg2.connect(args.db)
    try:
        migrate(conn, df)
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()
