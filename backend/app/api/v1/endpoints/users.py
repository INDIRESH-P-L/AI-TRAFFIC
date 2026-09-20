"""TRAFFICINTEL AI - User Administration & RBAC Endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles, get_password_hash
from app.models.entities import User, AuditLog, utc_now
from app.schemas.domain import UserResponse, UserCreate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"]))
):
    return db.query(User).all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"]))
):
    existing = db.query(User).filter((User.username == data.username) | (User.email == data.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already in use.")

    new_user = User(
        username=data.username,
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role=data.role.upper(),
        is_active=True
    )
    db.add(new_user)
    db.flush()

    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="CREATE_USER",
        resource_type="User",
        resource_id=new_user.id,
        result="EXECUTED",
        details={"username": new_user.username, "role": new_user.role}
    )
    db.add(audit)
    db.commit()
    db.refresh(new_user)
    return new_user
