"""Human-in-the-Loop escalation API: department reviewers manage pending tickets.

Review model: Security Admin sees everything; other roles review escalations whose
department matches one of their allowed departments.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.rbac import DEPARTMENTS, User
from app.auth.routes import get_current_user, require_admin
from app.core.config import get_settings
from app.services import audit
from app.rag import tools as action_tools

router = APIRouter(prefix="/api/escalations", tags=["escalations"])
settings = get_settings()


class ReviewRequest(BaseModel):
    resolution: str = Field(pattern="^(approved|rejected)$")
    comment: str = Field(default="", max_length=2000)


def _can_review(user: User, department: str) -> bool:
    """Security Admin reviews all; department owners review their own departments."""
    if user.is_admin:
        return True
    return department in user.allowed_departments


@router.get("/actions")
def list_pending_actions(status_filter: str | None = None, user: User = Depends(get_current_user)):
    """Reviewer queue for pending agent ACTIONS (mutating tool calls awaiting approval)."""
    if user.is_admin:
        items = action_tools.list_pending_actions(status=status_filter)
    else:
        items = []
        for dept in user.allowed_departments:
            items.extend(action_tools.list_pending_actions(status=status_filter, department=dept))
        seen, uniq = set(), []
        for a in items:
            if a["action_ref"] not in seen:
                seen.add(a["action_ref"]); uniq.append(a)
        items = uniq
    return {"count": len(items), "actions": items}


@router.post("/actions/{action_ref}/review")
def review_pending_action(action_ref: str, payload: ReviewRequest, user: User = Depends(get_current_user)):
    """Approve (executes the tool via MCP) or reject a pending agent action."""
    action = action_tools.get_pending_action(action_ref)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    if not _can_review(user, action["department"]):
        raise HTTPException(status_code=403, detail=f"Reviewer must own department {action['department']} or be Security Admin.")
    updated = action_tools.decide_pending_action(action_ref, user.username, payload.resolution, payload.comment)
    audit.write_document_access(user.username, user.roles,
                                f"[action:{payload.resolution}] tool={action['tool_name']}",
                                [{"document": action_ref, "department": action["department"]}])
    return {"message": f"Action {action_ref} {payload.resolution}.", "action": updated}


@router.get("")
def list_escalations(status_filter: str | None = None, user: User = Depends(get_current_user)):
    """List escalations visible to the reviewer (scoped by role/department)."""
    if user.is_admin:
        tickets = audit.list_escalations(status=status_filter or None)
    else:
        visible = []
        for dept in user.allowed_departments:
            visible.extend(audit.list_escalations(status=status_filter or None, department=dept))
        # de-duplicate by ticket_ref
        seen, uniq = set(), []
        for t in visible:
            if t["ticket_ref"] not in seen:
                seen.add(t["ticket_ref"])
                uniq.append(t)
        tickets = uniq
    return {"count": len(tickets), "tickets": tickets, "viewer": {"username": user.username, "is_admin": user.is_admin}}


@router.get("/mine")
def my_tickets(user: User = Depends(get_current_user)):
    """A user checks the status/outcome of their own escalated questions."""
    return {"tickets": audit.tickets_for_user(user.username)}


@router.get("/{ticket_ref}")
def escalation_detail(ticket_ref: str, user: User = Depends(get_current_user)):
    ticket = audit.get_escalation(ticket_ref)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if not _can_review(user, ticket["department"]) and ticket["username"] != user.username:
        raise HTTPException(status_code=403, detail="Not your department's escalation.")
    return ticket


@router.post("/{ticket_ref}/review")
def review_escalation(ticket_ref: str, payload: ReviewRequest, user: User = Depends(get_current_user)):
    """Approve or reject an escalated draft answer. Records reviewer + comment + history."""
    ticket = audit.get_escalation(ticket_ref)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if not _can_review(user, ticket["department"]):
        raise HTTPException(status_code=403, detail=f"Reviewer must own department {ticket['department']} or be Security Admin.")
    if ticket["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Ticket already resolved by {ticket['reviewer']}.")
    updated = audit.resolve_escalation(ticket_ref, user.username, payload.resolution, payload.comment)
    # Audit the human decision
    audit.write_document_access(user.username, user.roles, f"[escalation:{payload.resolution}] {ticket['question']}",
                                [{"document": ticket_ref, "department": ticket["department"]}])
    return {"message": f"Ticket {ticket_ref} {payload.resolution}.", "ticket": updated}
