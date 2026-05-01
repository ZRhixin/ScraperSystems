"""
Database snapshot — dumps all tables to a timestamped JSON file.
Usage: python snapshot.py
Output: snapshots/snapshot_YYYYMMDD_HHMMSS.json
"""
import json
import os
from datetime import date, datetime
from decimal import Decimal

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

TABLES = [
    "properties",
    "appraiser_transfer_history",
    "rod_captures",
    "court_captures",
    "document_extractions",
    "investigation_sessions",
    "investigation_questions",
    "investigation_trace",
    "incidental_records",
    "chain_conclusions",
]


def serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


def snapshot():
    conn = psycopg2.connect(os.getenv("SCRAPER_DB_URL"))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    data = {}
    for table in TABLES:
        try:
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            rows = [dict(r) for r in cur.fetchall()]
            data[table] = rows
            print(f"  {table}: {len(rows)} rows")
        except Exception as e:
            print(f"  {table}: SKIPPED ({e})")
            data[table] = []

    conn.close()

    os.makedirs("snapshots", exist_ok=True)
    filename = f"snapshots/snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2, default=serial)

    print(f"\nSaved: {filename}")


if __name__ == "__main__":
    snapshot()
