from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.rbac import Permission, Role, RolePermission
from app.schemas.rbac import PermissionOut, RoleCreate, RoleOut, RoleUpdate
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Roles & Permissions"])

_LOAD_OPTS = selectinload(Role.permission_links).selectinload(RolePermission.permission)


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PERMISSIONS_VIEW)),
):
    result = await db.execute(select(Permission).order_by(Permission.module, Permission.code))
    return result.scalars().all()


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ROLES_VIEW)),
):
    result = await db.execute(select(Role).options(_LOAD_OPTS).order_by(Role.name))
    return [_to_role_out(r) for r in result.scalars().unique().all()]


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ROLES_VIEW)),
):
    role = await _get_role_or_404(db, role_id)
    return _to_role_out(role)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ROLES_MANAGE)),
):
    existing = await db.execute(select(Role).where(Role.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A role with this name already exists")

    role = Role(name=payload.name, description=payload.description, is_system=False)
    db.add(role)
    await db.flush()

    await _sync_permissions(db, role, payload.permission_codes)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="role.create",
        entity_type="Role", entity_id=role.id,
        new_value={"name": role.name, "permission_codes": payload.permission_codes},
    )
    await db.commit()
    return _to_role_out(await _get_role_or_404(db, role.id))


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ROLES_MANAGE)),
):
    role = await _get_role_or_404(db, role_id)
    if role.is_system and payload.is_active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System roles cannot be deactivated")

    previous_codes = sorted(link.permission.code for link in role.permission_links)

    if payload.description is not None:
        role.description = payload.description
    if payload.is_active is not None:
        role.is_active = payload.is_active
    if payload.permission_codes is not None:
        await _sync_permissions(db, role, payload.permission_codes)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="role.update",
        entity_type="Role", entity_id=role.id,
        previous_value={"permission_codes": previous_codes},
        new_value={"permission_codes": payload.permission_codes} if payload.permission_codes is not None else None,
    )
    await db.commit()
    return _to_role_out(await _get_role_or_404(db, role_id))


# --- helpers ---

async def _get_role_or_404(db: AsyncSession, role_id: int) -> Role:
    result = await db.execute(select(Role).where(Role.id == role_id).options(_LOAD_OPTS))
    role = result.unique().scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


async def _sync_permissions(db: AsyncSession, role: Role, permission_codes: list[str]) -> None:
    """Replaces the role's full permission set with exactly the codes given."""
    if permission_codes:
        result = await db.execute(select(Permission).where(Permission.code.in_(permission_codes)))
        found = result.scalars().all()
        found_codes = {p.code for p in found}
        missing = set(permission_codes) - found_codes
        if missing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permission code(s): {', '.join(sorted(missing))}")
    else:
        found = []

    # Clear existing links, then re-add — simplest correct approach for a small permission set.
    existing_links = await db.execute(select(RolePermission).where(RolePermission.role_id == role.id))
    for link in existing_links.scalars().all():
        await db.delete(link)
    await db.flush()

    for permission in found:
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))


def _to_role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id, name=role.name, description=role.description,
        is_system=role.is_system, is_active=role.is_active,
        permissions=[
            PermissionOut(id=l.permission.id, code=l.permission.code, module=l.permission.module, description=l.permission.description)
            for l in role.permission_links
        ],
    )
