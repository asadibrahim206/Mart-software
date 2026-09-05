from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import CurrentUser
from app.services import audit_service
from app.services.auth_service import authenticate_user, load_user_with_roles

router = APIRouter(prefix="/auth", tags=["Authentication"])

_LOGIN_ERROR_MESSAGES = {
    "invalid_credentials": "Incorrect username or password",
    "account_locked": "Account temporarily locked due to repeated failed login attempts. Try again later.",
    "account_inactive": "This account has been deactivated. Contact your administrator.",
    "account_suspended": "This account has been suspended. Contact your administrator.",
}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user, error = await authenticate_user(db, payload.username, payload.password)
    if error:
        await audit_service.record(
            db,
            user_id=user.id if user else None,
            role_name=None,
            action="auth.login_failed",
            entity_type="User",
            entity_id=str(user.id) if user else None,
            new_value={"reason": error, "identifier": payload.username},
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_LOGIN_ERROR_MESSAGES[error])

    await audit_service.record(
        db,
        user_id=user.id,
        role_name=None,
        action="auth.login_success",
        entity_type="User",
        entity_id=str(user.id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_payload = decode_token(payload.refresh_token)
    if token_payload is None or token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = int(token_payload["sub"])
    user = await load_user_with_roles(db, user_id)
    if user is None or user.status.value != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer active")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=CurrentUser)
async def me(current_user: CurrentUser = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await load_user_with_roles(db, current_user.id)
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    await audit_service.record(
        db,
        user_id=user.id,
        role_name=None,
        action="auth.password_changed",
        entity_type="User",
        entity_id=str(user.id),
    )
    await db.commit()
    return MessageResponse(message="Password updated successfully")
