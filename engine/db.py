"""
db.py — "the filing cabinet".

Everything is stored in one SQLite file (runs.db). Five tables:
  runs          one row per pipeline run (with the full result as JSON)
  rule_results  one row per rule per run
  documents     one row per uploaded file per run
  events        append-only audit log: nothing is ever updated or deleted
  ai_cache      saved AI answers, keyed by the file's SHA-256 fingerprint
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    vendor_name TEXT,
    case_label TEXT,
    machine_status TEXT,
    final_status TEXT,
    flag TEXT,
    top_reason TEXT,
    ai_mode TEXT,
    started_at TEXT,
    finished_at TEXT,
    previous_run_id TEXT,
    result_json TEXT
);
CREATE TABLE IF NOT EXISTS rule_results (
    run_id TEXT, rule_id TEXT, stage TEXT, passed INTEGER,
    severity TEXT, reason TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    run_id TEXT, file_name TEXT, sha256 TEXT, doc_type TEXT,
    type_confidence REAL, fields TEXT, metadata TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT, at TEXT, actor TEXT, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY, answer TEXT, saved_at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def new_run_id():
    return "RUN-" + uuid.uuid4().hex[:8].upper()


def start_run(run_id, vendor_name, case_label, ai_mode, previous_run_id=None):
    with connect() as con:
        con.execute(
            "INSERT INTO runs (run_id, vendor_name, case_label, machine_status, final_status, "
            "ai_mode, started_at, previous_run_id) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, vendor_name, case_label, "Running", "Running", ai_mode, now(), previous_run_id))
    log_event(run_id, "system", "run_started", f"AI mode: {ai_mode}")


def log_event(run_id, actor, action, detail=""):
    with connect() as con:
        con.execute("INSERT INTO events VALUES (?,?,?,?,?)", (run_id, now(), actor, action, detail))


def finish_run(run_id, result):
    with connect() as con:
        con.execute(
            "UPDATE runs SET machine_status=?, final_status=?, flag=?, top_reason=?, "
            "finished_at=?, result_json=? WHERE run_id=?",
            (result["status"], result["status"], result.get("flag"), result.get("top_reason"),
             now(), json.dumps(result, default=str), run_id))
        for r in result["rules"]:
            con.execute("INSERT INTO rule_results VALUES (?,?,?,?,?,?,?)",
                        (run_id, r["rule"], r["stage"], int(r["passed"]), r["severity"],
                         r["reason"], json.dumps(r.get("evidence", {}), default=str)))
        for d in result["documents"]:
            con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
                        (run_id, d["file_name"], d["sha256"], d.get("doc_type"),
                         d.get("doc_type_confidence"), json.dumps(d.get("fields", {})),
                         json.dumps(d.get("metadata", {}), default=str)))
    log_event(run_id, "system", "decision", f"{result['status']} — {result.get('top_reason', '')}")


def override(run_id, new_status, reviewer, reason):
    """A human changes the outcome. The machine's verdict is kept alongside."""
    with connect() as con:
        con.execute("UPDATE runs SET final_status=? WHERE run_id=?", (new_status, run_id))
    log_event(run_id, f"reviewer:{reviewer}", "override", f"Set to {new_status}. Reason: {reason}")


def list_runs():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY started_at DESC")]


def get_run(run_id):
    with connect() as con:
        row = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_events(run_id):
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY rowid", (run_id,))]


def latest_run_for_vendor(vendor_name):
    with connect() as con:
        row = con.execute("SELECT run_id FROM runs WHERE vendor_name=? AND finished_at IS NOT NULL "
                          "ORDER BY started_at DESC LIMIT 1", (vendor_name,)).fetchone()
        return row["run_id"] if row else None


def cache_get(key):
    with connect() as con:
        row = con.execute("SELECT answer FROM ai_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row["answer"]) if row else None


def cache_put(key, answer):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO ai_cache VALUES (?,?,?)", (key, json.dumps(answer), now()))


def clear_runs():
    """Wipe run history (keeps the AI cache). Used by the 'reset demo' button."""
    with connect() as con:
        for t in ("runs", "rule_results", "documents", "events"):
            con.execute(f"DELETE FROM {t}")
