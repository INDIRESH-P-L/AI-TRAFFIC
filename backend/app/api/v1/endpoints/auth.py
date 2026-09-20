"""TRAFFICINTEL AI - Authentication & Authorization Endpoints
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, get_current_user
from app.models.entities import User, AuditLog, utc_now
from app.schemas.domain import Token, UserResponse, UserCreate

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user account")

    user.last_login = utc_now()
    
    # Audit log
    audit = AuditLog(
        actor_id=user.id,
        actor_username=user.username,
        action="USER_LOGIN",
        resource_type="User",
        resource_id=user.id,
        result="EXECUTED"
    )
    db.add(audit)
    db.commit()

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/register-initial-admin", response_model=UserResponse)
def register_initial_admin(user_in: UserCreate, db: Session = Depends(get_db)):
    """Allows bootstrapping the initial administrator on clean installation."""
    existing_users = db.query(User).count()
    if existing_users > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Initial admin setup is closed. Existing administrator must create additional users."
        )

    admin_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role="ADMIN",
        is_active=True
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    return admin_user
