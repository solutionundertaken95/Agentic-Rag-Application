"""JWT issuing/verification and password hashing for Authorization-Aware RAG."""
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.auth.rbac import DEMO_USERS, RoleDefinition, User, build_user
from app.core.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 480  # 8 hour workday session


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def authenticate(username: str, password: str) -> User | None:
    """Validate credentials against seeded demo users and return a User principal."""
    record = DEMO_USERS.get(username)
    if record is None or not verify_password(password, record["password"]):
        return None
    return build_user(username, record["roles"])


# Pre-hash the seeded demo passwords once at import so plaintext comparisons never occur.
for _record in DEMO_USERS.values():
    _record["password"] = _pwd_context.hash(_record["password"])


def create_access_token(user: User) -> str:
    payload = {
        "sub": user.username,
        "roles": user.roles,
        "depts": list(user.allowed_departments),
        "adm": user.is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> User | None:
    """Decode a JWT and rebuild the User principal. Returns None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    username = payload.get("sub")
    roles = payload.get("roles", [])
    if not username:
        return None
    return build_user(username, roles)
