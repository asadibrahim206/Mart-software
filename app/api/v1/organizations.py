from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.organization import District, Organization, Region
from app.schemas.organization import (
    DistrictCreate, DistrictOut, OrganizationCreate, OrganizationOut, OrganizationUpdate,
    RegionCreate, RegionOut,
)
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Organizations"])


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_VIEW)),
):
    result = await db.execute(select(Organization).order_by(Organization.name))
    return result.scalars().all()


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_MANAGE)),
):
    existing = await db.execute(select(Organization).where(Organization.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization code already in use")

    org = Organization(**payload.model_dump())
    db.add(org)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="organization.create",
                                entity_type="Organization", entity_id=org.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(org)
    return org


@router.patch("/organizations/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_MANAGE)),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(org, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="organization.update",
                                entity_type="Organization", entity_id=org.id, new_value=changes)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/regions", response_model=list[RegionOut])
async def list_regions(
    organization_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_VIEW)),
):
    query = select(Region).order_by(Region.name)
    if organization_id:
        query = query.where(Region.organization_id == organization_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/regions", response_model=RegionOut, status_code=status.HTTP_201_CREATED)
async def create_region(
    payload: RegionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_MANAGE)),
):
    if await db.get(Organization, payload.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization does not exist")
    region = Region(**payload.model_dump())
    db.add(region)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="region.create",
                                entity_type="Region", entity_id=region.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(region)
    return region


@router.get("/districts", response_model=list[DistrictOut])
async def list_districts(
    region_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_VIEW)),
):
    query = select(District).order_by(District.name)
    if region_id:
        query = query.where(District.region_id == region_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/districts", response_model=DistrictOut, status_code=status.HTTP_201_CREATED)
async def create_district(
    payload: DistrictCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.ORG_MANAGE)),
):
    if await db.get(Region, payload.region_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Region does not exist")
    district = District(**payload.model_dump())
    db.add(district)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="district.create",
                                entity_type="District", entity_id=district.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(district)
    return district
