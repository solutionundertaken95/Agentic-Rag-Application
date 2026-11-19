"""Agent-side MCP client + LangChain tool wrappers for the Action Agent.

Connects to the MCP server (streamable-http on 127.0.0.1:8001), discovers tools,
and exposes them to the LangGraph workflow. Mutating tools are never executed
directly by the agent — the workflow creates a pending_action ticket and the
tool is invoked only after human approval.
"""
import json
import logging
from datetime import datetime, timezone

import mysql.connector

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Tools that mutate state and therefore REQUIRE human approval before execution
MUTATING_TOOLS = {"create_service_desk_ticket", "reset_test_account"}

# RBAC on tools: which departments may invoke each tool at all
TOOL_ALLOWED_DEPARTMENTS = {
    "get_ticket_status": None,          # any authenticated user
    "search_incidents": None,           # dept filter applied per-user by the agent
    "get_system_health": None,
    "create_service_desk_ticket": ("IT", "HR", "FINANCE", "SECURITY"),
    "reset_test_account": ("IT", "SECURITY"),
}


# ---------------- pending action store (MySQL) ----------------

def _con() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        database=settings.mysql_database,
    )


def create_pending_action(username: str, roles: list[str], tool_name: str, arguments: dict, department: str) -> str:
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM pending_actions")
    seq = cur.fetchone()[0] + 1
    ref = f"ACT-{datetime.now(timezone.utc).year}-{seq:04d}"
    cur.execute(
        "INSERT INTO pending_actions"
        "(action_ref, created_at, username, roles, tool_name, arguments_json, department, status)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending_approval')",
        (ref, datetime.now(timezone.utc).isoformat(), username, ",".join(roles),
         tool_name, json.dumps(arguments), department),
    )
    con.commit()
    cur.close()
    con.close()
    return ref


def list_pending_actions(status: str | None = None, department: str | None = None) -> list[dict]:
    con = _con()
    cur = con.cursor()
    sql = "SELECT * FROM pending_actions WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = %s"; params.append(status)
    if department:
        sql += " AND department = %s"; params.append(department)
    sql += " ORDER BY id DESC LIMIT 100"
    cur.execute(sql, tuple(params))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); con.close()
    for r in rows:
        r["arguments"] = json.loads(r.pop("arguments_json") or "{}")
    return rows


def get_pending_action(action_ref: str) -> dict | None:
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT * FROM pending_actions WHERE action_ref = %s", (action_ref,))
    cols = [d[0] for d in cur.description] if cur.description else []
    row = cur.fetchone()
    cur.close(); con.close()
    if row is None:
        return None
    d = dict(zip(cols, row))
    d["arguments"] = json.loads(d.pop("arguments_json") or "{}")
    return d


def decide_pending_action(action_ref: str, reviewer: str, resolution: str, comment: str) -> dict | None:
    """Approve or reject a pending action. On approval, EXECUTE the tool via MCP."""
    action = get_pending_action(action_ref)
    if action is None or action["status"] != "pending_approval":
        return None
    con = _con()
    cur = con.cursor()
    cur.execute(
        "UPDATE pending_actions SET status = 'resolved', resolution = %s, reviewer = %s,"
        " reviewer_comment = %s, resolved_at = %s WHERE action_ref = %s AND status = 'pending_approval'",
        (resolution, reviewer, comment, datetime.now(timezone.utc).isoformat(), action_ref),
    )
    con.commit()
    cur.close(); con.close()

    if resolution == "approved":
        result = execute_tool(action["tool_name"], action["arguments"])
        con = _con()
        cur = con.cursor()
        cur.execute("UPDATE pending_actions SET execution_result = %s WHERE action_ref = %s",
                    (json.dumps(result), action_ref))
        con.commit(); cur.close(); con.close()
    else:
        result = {"executed": False, "reason": "rejected by reviewer"}
    return {**get_pending_action(action_ref), "execution": result}


# ---------------- MCP client ----------------

_client = None
_tools = None


async def _get_tools():
    """Connect to the MCP server and load its tools as LangChain tools."""
    global _client, _tools
    if _tools is not None:
        return _tools
    from langchain_mcp_adapters.client import MultiServerMCPClient

    _client = MultiServerMCPClient({
        "enterprise-support-tools": {
            "url": "http://127.0.0.1:8001/mcp",
            "transport": "streamable_http",
        }
    })
    _tools = await _client.get_tools()
    logger.info("MCP tools loaded: %s", [t.name for t in _tools])
    return _tools


async def call_mcp_tool(name: str, arguments: dict) -> str:
    """Invoke a tool on the MCP server and return its string result."""
    tools = await _get_tools()
    for t in tools:
        if t.name == name:
            result = await t.ainvoke(arguments)
            return result if isinstance(result, str) else json.dumps(result)
    return json.dumps({"error": f"Tool {name} not found on MCP server."})


def execute_tool(name: str, arguments: dict) -> dict:
    """Synchronous execution bridge used on approval (runs the async MCP call)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                raw = pool.submit(asyncio.run, call_mcp_tool(name, arguments)).result()
        else:
            raw = loop.run_until_complete(call_mcp_tool(name, arguments))
    except RuntimeError:
        raw = asyncio.run(call_mcp_tool(name, arguments))
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}


def tool_departments_for_user(allowed_departments) -> dict[str, bool]:
    """Which tools the user may *request* given their department scope."""
    allowed = set(allowed_departments) | {"GENERAL"}
    out = {}
    for tool, depts in TOOL_ALLOWED_DEPARTMENTS.items():
        out[tool] = True if depts is None else bool(allowed & set(depts))
    return out
