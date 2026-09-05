"""
Shared FastAPI dependencies.

get_current_user: decodes the bearer token, loads the user + roles + permissions fresh from
the DB, and rejects inactive/suspended/locked accounts even if their token is still technically
valid (e.g. a user suspended mid-session is cut off on their very next request).

require_permission(code): a dependency FACTORY — use it as
    Depends(require_permission(Perm.USERS_CREATE))
in any route to enforce that permission. This is how "permissions are configurable, not
hardcoded" is satisfied: the route only ever asks "does this user currently have code X",
and which roles grant code X is entirely DB-driven.
"""
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import UserStatus
from app.schemas.user import CurrentUser
from app.services.auth_service import get_effective_permissions, get_role_names, load_user_with_roles

# HTTPBearer (not OAuth2PasswordBearer) because /auth/login takes JSON, not the OAuth2 form-encoded
# body Swagger's OAuth2 flow expects. This makes the "Authorize" button in /docs just ask for a raw
# token to paste in, which matches how this API actually issues tokens.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception
    token = credentials.credentials

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise credentials_exception

    user = await load_user_with_roles(db, int(user_id_raw))
    if user is None:
        raise credentials_exception

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account is {user.status.value}")
    if user.is_locked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is temporarily locked")

    return CurrentUser(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        organization_id=user.organization_id,
        mart_id=user.mart_id,
        district_id=user.district_id,
        permission_codes=sorted(get_effective_permissions(user)),
        role_names=get_role_names(user),
    )


def require_permission(permission_code: str) -> Callable:
    async def _checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if permission_code not in current_user.permission_codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_code}",
            )
        return current_user

    return _checker


def require_any_permission(*permission_codes: str) -> Callable:
    async def _checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not set(permission_codes) & set(current_user.permission_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing one of required permissions: {', '.join(permission_codes)}",
            )
        return current_user

    return _checker
