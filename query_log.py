"""Logs every query (question, generated SQL, mode, success/failure, retry
count) to its own SQLite table, separate from the Chinook data itself, so
the analytics DB stays read-only/untouched. Powers the 'recent queries'
sidebar and gives you a usage-analytics artifact for free."""
import sqlite3
import datetime

LOG_DB_PATH = "data/query_log.db"


def _init_db():
    conn = sqlite3.connect(LOG_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            question TEXT NOT NULL,
            sql TEXT,
            mode TEXT,
            success INTEGER,
            retries INTEGER,
            error TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def log_query(question: str, sql: str, mode: str, success: bool, retries: int = 0, error: str = None):
    _init_db()
    conn = sqlite3.connect(LOG_DB_PATH)
    conn.execute(
        "INSERT INTO query_log (timestamp, question, sql, mode, success, retries, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(), question, sql, mode, int(success), retries, error),
    )
    conn.commit()
    conn.close()


def get_recent_queries(limit: int = 10):
    _init_db()
    conn = sqlite3.connect(LOG_DB_PATH)
    cur = conn.execute(
        "SELECT timestamp, question, mode, success, retries FROM query_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows
