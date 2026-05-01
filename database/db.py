"""
Database connection helper for the Scraper DB (Neon PostgreSQL).
"""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_DB_URL = os.getenv("SCRAPER_DB_URL")


def get_conn():
    if not _DB_URL:
        raise RuntimeError("SCRAPER_DB_URL not set in .env")
    return psycopg2.connect(_DB_URL)


def dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
