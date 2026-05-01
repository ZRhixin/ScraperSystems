"""
Apply all pending SQL migrations in order.
Usage: python -m database.migrate
"""
import os
import re
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("SCRAPER_DB_URL")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run():
    if not DB_URL:
        raise RuntimeError("SCRAPER_DB_URL not set in .env")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    # Track applied migrations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id      SERIAL PRIMARY KEY,
            name    VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    conn.commit()

    cur.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in cur.fetchall()}

    files = sorted(
        f for f in MIGRATIONS_DIR.glob("*.sql")
        if re.match(r"^\d+_", f.name)
    )

    for f in files:
        if f.name in applied:
            print(f"  skip  {f.name}")
            continue
        print(f"  apply {f.name} ... ", end="", flush=True)
        sql = f.read_text(encoding="utf-8")
        cur.execute(sql)
        cur.execute("INSERT INTO _migrations (name) VALUES (%s)", (f.name,))
        conn.commit()
        print("done")

    cur.close()
    conn.close()
    print("All migrations complete.")


if __name__ == "__main__":
    run()
