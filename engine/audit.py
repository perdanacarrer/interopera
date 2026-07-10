"""
audit.py — Append-only audit log (SQLite).
UPDATE and DELETE are blocked by database triggers.
"""
import sqlite3, json, datetime, os

AUDIT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit", "audit_log.db")

def _get_conn():
    os.makedirs(os.path.dirname(AUDIT_DB), exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, event TEXT NOT NULL, firm_id TEXT, data TEXT NOT NULL)""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS prevent_update
        BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit_log is append-only: UPDATE is prohibited'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS prevent_delete
        BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit_log is append-only: DELETE is prohibited'); END""")
    conn.commit()
    return conn

def log_event(event: str, data: dict, firm_id: str = None):
    conn = _get_conn()
    conn.execute("INSERT INTO audit_log (ts,event,firm_id,data) VALUES (?,?,?,?)",
        (datetime.datetime.utcnow().isoformat()+"Z", event, firm_id, json.dumps(data, default=str)))
    conn.commit(); conn.close()

def dump_log(firm_id=None):
    conn = _get_conn()
    q = "SELECT id,ts,event,firm_id,data FROM audit_log" + (" WHERE firm_id=?" if firm_id else "") + " ORDER BY id"
    rows = conn.execute(q, (firm_id,) if firm_id else ()).fetchall()
    conn.close()
    return [{"id":r[0],"ts":r[1],"event":r[2],"firm_id":r[3],"data":json.loads(r[4])} for r in rows]
