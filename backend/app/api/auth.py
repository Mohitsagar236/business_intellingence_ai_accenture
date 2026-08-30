from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.deps import get_current_user
from app.logging_config import event
from app.models import User
from app.rate_limit import clear_failures, is_locked_out, record_failure
from app.schemas import LoginRequest, TokenOut, UserOut
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    # Never log body.password — only the username (an identifier, not a secret) and outcome.
    remaining = is_locked_out(body.username)
    if remaining is not None:
        event(logger, logging.WARNING, "login_locked_out", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {remaining // 60 + 1} minute(s).",
        )

    user = db.query(User).filter(User.username == body.username).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        record_failure(body.username)
        event(logger, logging.WARNING, "login_failed", username=body.username)
        record_audit(db, username=body.username, role=user.role if user else None, action="login_failed", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    clear_failures(body.username)
    event(logger, logging.INFO, "login_success", username=user.username, role=user.role)
    record_audit(db, username=user.username, role=user.role, action="login_success", success=True)
    token = create_access_token(subject=user.username, role=user.role)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
