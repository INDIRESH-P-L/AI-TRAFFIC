"""TRAFFICINTEL AI - Security & Authentication

JWT Token handling, modern direct bcrypt password hashing, and RBAC authorization dependencies.
Never store plaintext credentials.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    # Truncate to 72 bytes per bcrypt spec
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from app.models.entities import User
    payload = decode_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_roles(allowed_roles: List[str]):
    def role_checker(current_user = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role: {current_user.role}. Required: {allowed_roles}"
            )
        return current_user
    return role_checker


# ---------------------------------------------------------------------------
# Scope-based authorisation
# ---------------------------------------------------------------------------

class Principal:
    """Whoever is making this request: an operator, or a machine key.

    Endpoints authorise against `scopes`, not against a role name, so the
    access model has one source of truth (app/governance/scopes.py) rather
    than a role list repeated at every call site.
    """

    def __init__(self, kind: str, identity: str, scopes, role=None, user=None, api_key=None):
        self.kind = kind          # USER | API_KEY
        self.identity = identity  # username or key name
        self.scopes = set(scopes)
        self.role = role
        self.user = user
        self.api_key = api_key

    def has(self, scope: str) -> bool:
        return scope in self.scopes

    def __repr__(self) -> str:
        return "Principal({}:{})".format(self.kind, self.identity)


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    """Resolves the caller from a bearer token or an X-API-Key header."""
    from app.governance import scopes as scope_vocab
    from app.governance.api_keys import resolve_api_key
    from app.models.entities import User

    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        record = resolve_api_key(db, api_key_header)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is invalid, revoked or expired",
            )
        return Principal(
            kind="API_KEY",
            identity=record.name,
            scopes=record.scopes or [],
            api_key=record,
        )

    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(authorization.split(" ", 1)[1].strip())
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first() if username else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return Principal(
        kind="USER",
        identity=user.username,
        scopes=scope_vocab.scopes_for_role(user.role),
        role=user.role,
        user=user,
    )


def require_scope(*required_scopes: str):
    """Dependency asserting the caller holds every listed scope."""
    def checker(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [scope for scope in required_scopes if not principal.has(scope)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Missing required scope(s): {}. This {} holds: {}.".format(
                        sorted(missing),
                        "API key" if principal.kind == "API_KEY" else
                        "role ({})".format(principal.role),
                        sorted(principal.scopes) or "no scopes",
                    )
                ),
            )
        return principal
    return checker
