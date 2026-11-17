"""Role-Based Access Control model for Authorization-Aware RAG.

Each role maps to the set of departments whose documents the role may retrieve.
Document-level security is enforced at the Pinecone metadata filter level.
"""
from pydantic import BaseModel, Field


# Canonical departments used for Pinecone metadata tagging
DEPARTMENTS = ("IT", "HR", "FINANCE", "SECURITY")

# Public / general documents every authenticated user may see
PUBLIC_DEPARTMENT = "GENERAL"


class RoleDefinition(BaseModel):
    """A named enterprise role and the departments it may access."""
    name: str
    description: str
    allowed_departments: tuple[str, ...]
    is_admin: bool = False


RBAC_ROLES: dict[str, RoleDefinition] = {
    "IT Support": RoleDefinition(
        name="IT Support",
        description="Internal IT support staff — general company IT knowledge.",
        allowed_departments=("IT", "GENERAL"),
    ),
    "HR": RoleDefinition(
        name="HR",
        description="HR staff — employee benefits, leave and people policies.",
        allowed_departments=("HR", "GENERAL"),
    ),
    "Finance": RoleDefinition(
        name="Finance",
        description="Finance staff — expense, procurement and payroll documents.",
        allowed_departments=("FINANCE", "GENERAL"),
    ),
    "Security Admin": RoleDefinition(
        name="Security Admin",
        description="Security administrators — full access to all departments plus audit administration.",
        allowed_departments=("IT", "HR", "FINANCE", "SECURITY", "GENERAL"),
        is_admin=True,
    ),
}

# Seeded demo users: username -> {"password": plaintext (demo only), "roles": [...]}
DEMO_USERS: dict[str, dict] = {
    "it.user": {"password": "it-pass-123", "roles": ["IT Support"]},
    "hr.user": {"password": "hr-pass-123", "roles": ["HR"]},
    "fin.user": {"password": "fin-pass-123", "roles": ["Finance"]},
    "secadmin": {"password": "sec-pass-123", "roles": ["Security Admin"]},
}


class User(BaseModel):
    """Authenticated user principal injected into protected endpoints and the agent graph."""
    username: str
    roles: list[str] = Field(default_factory=list)
    allowed_departments: tuple[str, ...] = ()
    is_admin: bool = False


def build_user(username: str, roles: list[str]) -> User:
    """Construct a User principal from role names, resolving department access via RBAC."""
    defs = [RBAC_ROLES[r] for r in roles if r in RBAC_ROLES]
    depts: set[str] = set()
    for d in defs:
        depts.update(d.allowed_departments)
    return User(
        username=username,
        roles=sorted({d.name for d in defs}),
        allowed_departments=tuple(sorted(depts)),
        is_admin=any(d.is_admin for d in defs),
    )
