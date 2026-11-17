"""MySQL-backed audit + escalation store for Authorization-Aware RAG and
Human-in-the-Loop escalation workflows.

Migrated from SQLite: all audit and ticket data now lives in the `agentic_rag`
MySQL database (config via MYSQL_* settings).
"""
import json
from datetime import datetime, timezone

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool

from app.core.config import get_settings

settings = get_settings()

_pool: MySQLConnectionPool | None = None


def _db_config() -> dict:
    return {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "database": settings.mysql_database,
        "autocommit": False,
    }


def _connect():
    global _pool
    if _pool is None:
        _pool = MySQLConnectionPool(pool_name="rag_pool", pool_size=5, **_db_config())
    return _pool.get_connection()


def _rows(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def init_db() -> None:
    """Create the audit + escalation schema if it does not exist yet."""
    # Connect without database first in case schema was dropped
    cfg = _db_config()
    con = mysql.connector.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"]
    )
    cur = con.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS {settings.mysql_database} CHARACTER SET utf8mb4"
    )
    cur.close()
    con.close()

    con = _connect()
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS query_audit (
            id INT AUTO_INCREMENT PRIMARY KEY,
            created_at VARCHAR(64) NOT NULL,
            question TEXT NOT NULL,
            source_used VARCHAR(64) NOT NULL,
            trace_json LONGTEXT NOT NULL,
            username VARCHAR(128) NOT NULL DEFAULT 'anonymous',
            roles TEXT NOT NULL,
            doc_departments TEXT NOT NULL,
            INDEX idx_qa_user (username),
            INDEX idx_qa_source (source_used)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS document_access (
            id INT AUTO_INCREMENT PRIMARY KEY,
            created_at VARCHAR(64) NOT NULL,
            username VARCHAR(128) NOT NULL,
            roles TEXT NOT NULL,
            question TEXT NOT NULL,
            document TEXT NOT NULL,
            department VARCHAR(32) NOT NULL,
            action VARCHAR(32) NOT NULL DEFAULT 'retrieved',
            INDEX idx_da_user (username),
            INDEX idx_da_dept (department)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS escalation_tickets (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ticket_ref VARCHAR(32) NOT NULL UNIQUE,
            created_at VARCHAR(64) NOT NULL,
            username VARCHAR(128) NOT NULL,
            roles TEXT NOT NULL,
            question TEXT NOT NULL,
            draft_answer LONGTEXT NOT NULL,
            evidence_json LONGTEXT NOT NULL,
            confidence INT NOT NULL,
            department VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            resolution VARCHAR(32) DEFAULT NULL,
            reviewer VARCHAR(128) DEFAULT NULL,
            reviewer_comment TEXT,
            resolved_at VARCHAR(64) DEFAULT NULL,
            released_answer LONGTEXT,
            INDEX idx_esc_status (status),
            INDEX idx_esc_dept (department)
        )"""
    )
    con.commit()
    cur.close()
    con.close()


# ------------------------- audit writes -------------------------

def write_audit(
    question: str,
    source_used: str,
    trace: list[str],
    username: str = "anonymous",
    roles: list[str] | None = None,
    doc_departments: list[str] | None = None,
) -> None:
    con = _connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO query_audit(created_at, question, source_used, trace_json, username, roles, doc_departments)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
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
    cur.close()
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
    cur = con.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.executemany(
        "INSERT INTO document_access(created_at, username, roles, question, document, department, action)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [
            (now, username, ",".join(roles), question, a["document"], a["department"], "retrieved")
            for a in accessed
        ],
    )
    con.commit()
    cur.close()
    con.close()


# ------------------------- audit reads -------------------------

def read_query_audit(limit: int = 100) -> list[dict]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM query_audit ORDER BY id DESC LIMIT %s", (limit,))
    rows = _rows(cur)
    cur.close()
    con.close()
    return rows


def read_document_access(limit: int = 100) -> list[dict]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM document_access ORDER BY id DESC LIMIT %s", (limit,))
    rows = _rows(cur)
    cur.close()
    con.close()
    return rows


def audit_summary() -> dict:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM query_audit")
    q_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM document_access")
    d_total = cur.fetchone()[0]
    cur.execute(
        "SELECT username, COUNT(*) FROM query_audit GROUP BY username ORDER BY COUNT(*) DESC"
    )
    per_user = [{"username": u, "queries": c} for u, c in cur.fetchall()]
    cur.close()
    con.close()
    return {"total_queries": q_total, "total_document_accesses": d_total, "queries_per_user": per_user}


# ------------------------- escalation tickets -------------------------

def create_escalation(
    username: str,
    roles: list[str],
    question: str,
    draft_answer: str,
    evidence: list[dict],
    confidence: int,
    department: str,
) -> str:
    """Create a pending escalation ticket and return its human-readable reference."""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM escalation_tickets")
    seq = cur.fetchone()[0] + 1
    ref = f"ESC-{datetime.now(timezone.utc).year}-{seq:04d}"
    cur.execute(
        "INSERT INTO escalation_tickets"
        "(ticket_ref, created_at, username, roles, question, draft_answer, evidence_json, confidence, department, status)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
        (
            ref,
            datetime.now(timezone.utc).isoformat(),
            username,
            ",".join(roles),
            question,
            draft_answer,
            json.dumps(evidence),
            int(confidence),
            department,
        ),
    )
    con.commit()
    cur.close()
    con.close()
    return ref


def list_escalations(status: str | None = None, department: str | None = None, limit: int = 100) -> list[dict]:
    con = _connect()
    cur = con.cursor()
    sql = "SELECT * FROM escalation_tickets WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = %s"
        params.append(status)
    if department:
        sql += " AND department = %s"
        params.append(department)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    cur.execute(sql, tuple(params))
    rows = _rows(cur)
    cur.close()
    con.close()
    for r in rows:
        r["evidence"] = json.loads(r.pop("evidence_json") or "[]")
    return rows


def get_escalation(ticket_ref: str) -> dict | None:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM escalation_tickets WHERE ticket_ref = %s", (ticket_ref,))
    row = cur.fetchone()
    cur.close()
    con.close()
    if row is None:
        return None
    cols = ["id", "ticket_ref", "created_at", "username", "roles", "question", "draft_answer",
            "evidence_json", "confidence", "department", "status", "resolution", "reviewer",
            "reviewer_comment", "resolved_at", "released_answer"]
    d = dict(zip(cols, row))
    d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
    return d


def resolve_escalation(
    ticket_ref: str,
    reviewer: str,
    resolution: str,
    comment: str,
) -> dict | None:
    """Approve or reject a ticket. Returns the updated ticket or None if not found."""
    status = "resolved" if resolution == "approved" else "resolved"
    con = _connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE escalation_tickets SET status = %s, resolution = %s, reviewer = %s,"
        " reviewer_comment = %s, resolved_at = %s WHERE ticket_ref = %s AND status = 'pending'",
        (
            status,
            resolution,
            reviewer,
            comment,
            datetime.now(timezone.utc).isoformat(),
            ticket_ref,
        ),
    )
    updated = cur.rowcount
    con.commit()
    cur.close()
    con.close()
    return get_escalation(ticket_ref) if updated else None


def tickets_for_user(username: str, limit: int = 20) -> list[dict]:
    con = _connect()
    cur = con.cursor()
    cur.execute(
        "SELECT ticket_ref, created_at, question, status, resolution, reviewer_comment,"
        " released_answer, confidence FROM escalation_tickets WHERE username = %s"
        " ORDER BY id DESC LIMIT %s",
        (username, limit),
    )
    rows = _rows(cur)
    cur.close()
    con.close()
    return rows
