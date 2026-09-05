"""
Authentication + permission resolution.

Permissions are computed fresh from the database on every request (not baked into the JWT),
so revoking a role or deactivating a user takes effect on the user's very next request rather
than waiting for their token to expire. This trades a small amount of per-request DB work for
a security guarantee that matters a lot for this system (e.g. immediately cutting off a
terminated cashier's ability to distribute welfare goods).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import verify_password
from app.models.rbac import Role, RolePermission, UserRole
from app.models.user import User, UserStatus

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


async def get_user_by_username_or_email(db: AsyncSession, identifier: str) -> Optional[User]:
    result = await db.execute(select(User).where((User.username == identifier) | (User.email == identifier)))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, identifier: str, password: str) -> tuple[Optional[User], Optional[str]]:
    """
    Returns (user, error_code). error_code is None on success, otherwise one of:
    invalid_credentials | account_locked | account_inactive | account_suspended
    """
    user = await get_user_by_username_or_email(db, identifier)
    if user is None:
        return None, "invalid_credentials"

    if user.is_locked:
        return None, "account_locked"

    if user.status == UserStatus.SUSPENDED:
        return None, "account_suspended"
    if user.status == UserStatus.INACTIVE:
        return None, "account_inactive"

    if not verify_password(password, user.hashed_password):
        await _register_failed_attempt(db, user)
        return None, "invalid_credentials"

    # Successful login — reset failure counters, stamp last login.
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(failed_login_attempts=0, locked_until=None, last_login_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return user, None


async def _register_failed_attempt(db: AsyncSession, user: User) -> None:
    attempts = user.failed_login_attempts + 1
    values = {"failed_login_attempts": attempts}
    if attempts >= MAX_FAILED_ATTEMPTS:
        values["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
    await db.execute(update(User).where(User.id == user.id).values(**values))
    await db.commit()


async def load_user_with_roles(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.role_links).selectinload(UserRole.role).selectinload(Role.permission_links).selectinload(RolePermission.permission))
    )
    return result.scalar_one_or_none()


def get_effective_permissions(user: User) -> set[str]:
    """Union of every permission granted by every role the user currently holds."""
    codes: set[str] = set()
    for user_role in user.role_links:
        role = user_role.role
        if not role.is_active:
            continue
        for link in role.permission_links:
            codes.add(link.permission.code)
    return codes


def get_role_names(user: User) -> list[str]:
    return [ur.role.name for ur in user.role_links if ur.role.is_active]
