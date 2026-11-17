"""Audit service: query audit (who asked what) + document-access audit (which documents
were retrieved by whom) for the Authorization-Aware RAG feature."""
import json
import sqlite3
from datetime import datetime, timezone
from app.core.config import get_settings

settings = get_settings()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(settings.audit_db_path)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    con = _connect()
    con.execute(
        """CREATE TABLE IF NOT EXISTS query_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            question TEXT NOT NULL,
            source_used TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            username TEXT NOT NULL DEFAULT 'anonymous',
            roles TEXT NOT NULL DEFAULT '',
            doc_departments TEXT NOT NULL DEFAULT ''
        )"""
    )
    # Migration for pre-existing databases created before the auth feature
    cols = {row["name"] for row in con.execute("PRAGMA table_info(query_audit)")}
    if "username" not in cols:
        con.execute("ALTER TABLE query_audit ADD COLUMN username TEXT NOT NULL DEFAULT 'anonymous'")
    if "roles" not in cols:
        con.execute("ALTER TABLE query_audit ADD COLUMN roles TEXT NOT NULL DEFAULT ''")
    if "doc_departments" not in cols:
        con.execute("ALTER TABLE query_audit ADD COLUMN doc_departments TEXT NOT NULL DEFAULT ''")

    con.execute(
        """CREATE TABLE IF NOT EXISTS document_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            username TEXT NOT NULL,
            roles TEXT NOT NULL,
            question TEXT NOT NULL,
            document TEXT NOT NULL,
            department TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'retrieved'
        )"""
    )
    con.commit()
    con.close()


def write_audit(
    question: str,
    source_used: str,
    trace: list[str],
    username: str = "anonymous",
    roles: list[str] | None = None,
    doc_departments: list[str] | None = None,
) -> None:
    con = _connect()
    con.execute(
        "INSERT INTO query_audit(created_at, question, source_used, trace_json, username, roles, doc_departments)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            question,
            source_used,
            json.dumps(trace),
            username,
            ",".join(roles or []),
            ",".join(sorted(set(doc_departments or []))),
        ),
    )
    con.commit()
    con.close()


def write_document_access(
    username: str,
    roles: list[str],
    question: str,
    accessed: list[dict],
) -> None:
    """Record one row per (document, department) retrieved during a query."""
    if not accessed:
        return
    con = _connect()
    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "INSERT INTO document_access(created_at, username, roles, question, document, department, action)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (now, username, ",".join(roles), question, a["document"], a["department"], "retrieved")
            for a in accessed
        ],
    )
    con.commit()
    con.close()


def read_query_audit(limit: int = 100) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT * FROM query_audit ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def read_document_access(limit: int = 100) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT * FROM document_access ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def audit_summary() -> dict:
    con = _connect()
    q_total = con.execute("SELECT COUNT(*) c FROM query_audit").fetchone()["c"]
    d_total = con.execute("SELECT COUNT(*) c FROM document_access").fetchone()["c"]
    per_user = [
        dict(r)
        for r in con.execute(
            "SELECT username, COUNT(*) queries FROM query_audit GROUP BY username ORDER BY queries DESC"
        )
    ]
    con.close()
    return {"total_queries": q_total, "total_document_accesses": d_total, "queries_per_user": per_user}
