"""Action Agent MCP Server (FastMCP, streamable-http transport on port 8001).

Exposes 5 governed tools for the enterprise support agent, backed by MySQL:

Read-only (safe to execute immediately):
  - get_ticket_status(ticket_ref)
  - search_incidents(query, department?)
  - get_system_health()

Mutating (risky -> the AGENT creates a pending_action ticket for human approval;
these tools are only invoked AFTER a reviewer approves):
  - create_service_desk_ticket(title, description, priority, department, requester)
  - reset_test_account(username)

Run:  python -m mcp_server.server
"""
import json
from datetime import datetime, timezone

from fastmcp import FastMCP
import mysql.connector

from app.core.config import get_settings

settings = get_settings()

mcp = FastMCP(
    "enterprise-support-tools",
    instructions=(
        "Enterprise IT/HR/Finance/Security support tools. Read-only tools can be called "
        "freely. Mutating tools (create_service_desk_ticket, reset_test_account) MUST only "
        "be called after a human reviewer approved the corresponding pending action."
    ),
)


def _con() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Read-only tools
# --------------------------------------------------------------------------

@mcp.tool
def get_ticket_status(ticket_ref: str) -> str:
    """Look up a service-desk ticket by its reference (e.g. SDT-5001).
    Returns reference, title, state, priority, assignee, and description."""
    con = _con()
    cur = con.cursor()
    cur.execute(
        "SELECT ticket_ref, title, state, priority, assignee, department, description, created_at"
        " FROM service_desk_tickets WHERE ticket_ref = %s",
        (ticket_ref.strip().upper(),),
    )
    row = cur.fetchone()
    cur.close()
    con.close()
    if row is None:
        return json.dumps({"error": f"Ticket {ticket_ref} not found."})
    ref, title, state, priority, assignee, department, description, created = row
    return json.dumps({
        "ticket_ref": ref, "title": title, "state": state, "priority": priority,
        "assignee": assignee, "department": department, "description": description,
        "created_at": created,
    })


@mcp.tool
def search_incidents(query: str, department: str = "", limit: int = 5) -> str:
    """Search the incident database by keyword across title/description.
    Optionally restrict to a department (IT, HR, FINANCE, SECURITY).
    The caller MUST pass a department from the requesting user's allowed scope —
    RBAC is enforced by the agent before invoking this tool."""
    con = _con()
    cur = con.cursor()
    sql = (
        "SELECT incident_ref, title, department, status, priority, reported_at, description"
        " FROM incidents WHERE (title LIKE %s OR description LIKE %s)"
    )
    like = f"%{query}%"
    params: list = [like, like]
    if department:
        sql += " AND department = %s"
        params.append(department.upper())
    sql += " ORDER BY reported_at DESC LIMIT %s"
    params.append(max(1, min(int(limit), 10)))
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    cur.close()
    con.close()
    results = [
        {"incident_ref": r[0], "title": r[1], "department": r[2], "status": r[3],
         "priority": r[4], "reported_at": r[5], "description": r[6]}
        for r in rows
    ]
    return json.dumps({"query": query, "department": department or "ALL", "count": len(results), "incidents": results})


@mcp.tool
def get_system_health() -> str:
    """Fetch current mock system-health status for core internal services
    (VPN, email, payroll portal, knowledge base). Read-only."""
    # Deterministic mock health feed (no external calls needed)
    health = {
        "checked_at": _now(),
        "services": [
            {"service": "VPN Gateway", "status": "operational", "latency_ms": 42},
            {"service": "Email / M365", "status": "operational", "latency_ms": 87},
            {"service": "Payroll Portal", "status": "degraded", "latency_ms": 940,
             "note": "Elevated latency since 14:00 UTC — infra team engaged"},
            {"service": "Knowledge Base API", "status": "operational", "latency_ms": 65},
        ],
        "overall": "degraded",
    }
    return json.dumps(health)


# --------------------------------------------------------------------------
# Mutating tools (invoked only AFTER human approval of a pending action)
# --------------------------------------------------------------------------

@mcp.tool
def create_service_desk_ticket(
    title: str, description: str, priority: str, department: str, requester: str
) -> str:
    """Create a new service-desk ticket. HIGH-RISK MUTATION: the agent must have
    obtained human approval (pending action approved) before calling this tool."""
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM service_desk_tickets")
    seq = cur.fetchone()[0] + 5001
    ref = f"SDT-{seq}"
    cur.execute(
        "INSERT INTO service_desk_tickets"
        "(ticket_ref, requester, title, department, state, priority, assignee, description, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ref, requester, title, department.upper(), "open", priority.upper(), None, description, _now()),
    )
    con.commit()
    cur.close()
    con.close()
    return json.dumps({"created": True, "ticket_ref": ref, "title": title, "state": "open"})


@mcp.tool
def reset_test_account(username: str) -> str:
    """Reset a TEST account's password to a one-time value. HIGH-RISK MUTATION:
    only callable after Security Admin (or IT) approval of the pending action."""
    # Simulated reset: we do not touch a real identity provider.
    result = {
        "reset": True,
        "account": username,
        "temporary_password": "Tmp-" + datetime.now(timezone.utc).strftime("%H%M%S"),
        "expires_in_minutes": 30,
        "note": "Simulated test-account reset; no real identity provider was contacted.",
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
