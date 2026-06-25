"""
audit.py — Append-only audit log.

Uses SQLite with a write-trigger that raises an error on any UPDATE or DELETE,
demonstrating immutability in code. Every engine event is recorded here.
"""
import sqlite3
import json
import datetime
import os

AUDIT_DB = os.path.join(os.path.dirname(__file__), "audit", "audit_log.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AUDIT_DB), exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    _bootstrap(conn)
    return conn


def _bootstrap(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            event       TEXT    NOT NULL,
            firm_id     TEXT,
            data        TEXT    NOT NULL
        )
    """)
    # Immutability triggers — prevent UPDATE and DELETE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is prohibited');
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is prohibited');
        END
    """)
    conn.commit()


def log_event(event: str, data: dict, firm_id: str = None):
    """Append one audit event. Cannot be updated or deleted after insertion."""
    conn = _get_conn()
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    conn.execute(
        "INSERT INTO audit_log (ts, event, firm_id, data) VALUES (?, ?, ?, ?)",
        (ts, event, firm_id, json.dumps(data, default=str)),
    )
    conn.commit()
    conn.close()


def dump_log(firm_id: str = None) -> list:
    conn = _get_conn()
    if firm_id:
        rows = conn.execute(
            "SELECT id, ts, event, firm_id, data FROM audit_log WHERE firm_id=? OR firm_id IS NULL ORDER BY id",
            (firm_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ts, event, firm_id, data FROM audit_log ORDER BY id"
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "id": row[0], "ts": row[1], "event": row[2],
            "firm_id": row[3], "data": json.loads(row[4]),
        })
    return result
