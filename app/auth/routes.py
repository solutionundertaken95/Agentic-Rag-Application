"""FastAPI dependencies and auth router for login and current-user resolution."""
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth.rbac import RBAC_ROLES, User
from app.auth.security import authenticate, create_access_token, decode_token

_bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    roles: list[str]
    allowed_departments: list[str]


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> User:
    """Dependency: resolve the User principal from the Authorization: Bearer JWT header."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Obtain a token via /api/auth/login.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = decode_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency: restrict an endpoint to roles flagged as admin (Security Admin)."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Security Admin role required.")
    return user


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    return LoginResponse(
        access_token=create_access_token(user),
        username=user.username,
        roles=user.roles,
        allowed_departments=list(user.allowed_departments),
    )


@auth_router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "roles": user.roles,
        "allowed_departments": list(user.allowed_departments),
        "is_admin": user.is_admin,
    }


@auth_router.get("/roles")
def list_roles():
    """Public: describe the RBAC role model for the UI/docs."""
    return {
        role.name: {
            "description": role.description,
            "allowed_departments": list(role.allowed_departments),
            "is_admin": role.is_admin,
        }
        for role in RBAC_ROLES.values()
    }
