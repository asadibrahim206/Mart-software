from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.core.security import hash_password
from app.models.rbac import Role, RolePermission, UserRole
from app.models.user import User, UserStatus
from app.schemas.common import MessageResponse, Page, PageMeta
from app.schemas.user import CurrentUser, UserCreate, UserOut, UserUpdate
from app.services import audit_service
from app.services.auth_service import get_user_by_username_or_email

router = APIRouter(prefix="/users", tags=["Users"])


class UserRoleAssignBody(BaseModel):
    role_id: int
    scope_type: Optional[str] = None
    scope_id: Optional[int] = None

_LOAD_OPTS = selectinload(User.role_links).selectinload(UserRole.role).selectinload(Role.permission_links).selectinload(RolePermission.permission)


@router.get("", response_model=Page[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[UserStatus] = Query(None, alias="status"),
    mart_id: Optional[int] = None,
    district_id: Optional[int] = None,
    search: Optional[str] = Query(None, description="Matches username, email, or full name"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_VIEW)),
):
    query = select(User).options(_LOAD_OPTS)
    count_query = select(func.count()).select_from(User)

    if status_filter:
        query = query.where(User.status == status_filter)
        count_query = count_query.where(User.status == status_filter)
    if mart_id:
        query = query.where(User.mart_id == mart_id)
        count_query = count_query.where(User.mart_id == mart_id)
    if district_id:
        query = query.where(User.district_id == district_id)
        count_query = count_query.where(User.district_id == district_id)
    if search:
        like = f"%{search}%"
        cond = (User.username.ilike(like)) | (User.email.ilike(like)) | (User.full_name.ilike(like))
        query = query.where(cond)
        count_query = count_query.where(cond)

    total_items = (await db.execute(count_query)).scalar_one()
    query = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
    users = (await db.execute(query)).scalars().unique().all()

    return Page(
        items=[_to_user_out(u) for u in users],
        meta=PageMeta(page=page, page_size=page_size, total_items=total_items, total_pages=max(1, -(-total_items // page_size))),
    )


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_VIEW)),
):
    user = await _get_user_or_404(db, user_id)
    return _to_user_out(user)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_CREATE)),
):
    existing = await get_user_by_username_or_email(db, payload.username)
    if existing is None:
        existing = await get_user_by_username_or_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already in use")

    user = User(
        organization_id=payload.organization_id,
        region_id=payload.region_id,
        district_id=payload.district_id,
        mart_id=payload.mart_id,
        warehouse_id=payload.warehouse_id,
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()  # assigns user.id without committing yet

    for assignment in payload.role_assignments:
        role = await db.get(Role, assignment.role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role {assignment.role_id} does not exist")
        db.add(UserRole(user_id=user.id, role_id=role.id, scope_type=assignment.scope_type, scope_id=assignment.scope_id))

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="user.create",
        entity_type="User", entity_id=user.id,
        new_value={"username": user.username, "email": user.email, "roles": [a.role_id for a in payload.role_assignments]},
    )
    await db.commit()

    return _to_user_out(await _get_user_or_404(db, user.id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_UPDATE)),
):
    user = await _get_user_or_404(db, user_id)
    previous = {"status": user.status.value, "full_name": user.full_name}

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="user.update",
        entity_type="User", entity_id=user.id,
        previous_value=previous, new_value=payload.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    return _to_user_out(await _get_user_or_404(db, user_id))


@router.post("/{user_id}/deactivate", response_model=MessageResponse)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_DEACTIVATE)),
):
    user = await _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    previous_status = user.status.value
    user.status = UserStatus.INACTIVE
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="user.deactivate",
        entity_type="User", entity_id=user.id,
        previous_value={"status": previous_status}, new_value={"status": UserStatus.INACTIVE.value},
    )
    await db.commit()
    return MessageResponse(message=f"User {user.username} deactivated")


@router.post("/{user_id}/roles", response_model=UserOut)
async def assign_role(
    user_id: int,
    assignment: UserRoleAssignBody,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_UPDATE)),
):
    user = await _get_user_or_404(db, user_id)
    role = await db.get(Role, assignment.role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    db.add(UserRole(user_id=user.id, role_id=role.id, scope_type=assignment.scope_type, scope_id=assignment.scope_id))
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="user.role_assigned",
        entity_type="User", entity_id=user.id,
        new_value={"role_id": role.id, "role_name": role.name, "scope_type": assignment.scope_type, "scope_id": assignment.scope_id},
    )
    await db.commit()
    return _to_user_out(await _get_user_or_404(db, user_id))


@router.delete("/{user_id}/roles/{role_id}", response_model=MessageResponse)
async def revoke_role(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.USERS_UPDATE)),
):
    result = await db.execute(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id))
    links = result.scalars().all()
    if not links:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User does not hold this role")
    for link in links:
        await db.delete(link)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="user.role_revoked",
        entity_type="User", entity_id=user_id, previous_value={"role_id": role_id},
    )
    await db.commit()
    return MessageResponse(message="Role revoked")


# --- helpers ---

async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id).options(_LOAD_OPTS))
    user = result.unique().scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _to_user_out(user: User) -> UserOut:
    from app.schemas.rbac import PermissionOut, RoleOut

    roles = []
    for link in user.role_links:
        role = link.role
        roles.append(RoleOut(
            id=role.id, name=role.name, description=role.description,
            is_system=role.is_system, is_active=role.is_active,
            permissions=[PermissionOut(id=pl.permission.id, code=pl.permission.code, module=pl.permission.module, description=pl.permission.description) for pl in role.permission_links],
        ))
    return UserOut(
        id=user.id, organization_id=user.organization_id, region_id=user.region_id,
        district_id=user.district_id, mart_id=user.mart_id, warehouse_id=user.warehouse_id,
        username=user.username, email=user.email, full_name=user.full_name, phone=user.phone,
        status=user.status, must_change_password=user.must_change_password, roles=roles,
    )
