from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.organization import District, Mart, Warehouse
from app.schemas.organization import (
    MartCreate, MartOut, MartUpdate, WarehouseCreate, WarehouseOut,
)
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Warehouses & Marts"])


@router.get("/warehouses", response_model=list[WarehouseOut])
async def list_warehouses(
    district_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WAREHOUSES_VIEW)),
):
    query = select(Warehouse).order_by(Warehouse.name)
    if district_id:
        query = query.where(Warehouse.district_id == district_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WAREHOUSES_MANAGE)),
):
    if await db.get(District, payload.district_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="District does not exist")
    existing = await db.execute(select(Warehouse).where(Warehouse.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Warehouse code already in use")

    warehouse = Warehouse(**payload.model_dump())
    db.add(warehouse)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="warehouse.create",
                                entity_type="Warehouse", entity_id=warehouse.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(warehouse)
    return warehouse


@router.get("/marts", response_model=list[MartOut])
async def list_marts(
    district_id: int | None = None,
    accepts_welfare: bool | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.MARTS_VIEW)),
):
    query = select(Mart).order_by(Mart.name)
    if district_id:
        query = query.where(Mart.district_id == district_id)
    if accepts_welfare is not None:
        query = query.where(Mart.accepts_welfare == accepts_welfare)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/marts/{mart_id}", response_model=MartOut)
async def get_mart(
    mart_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.MARTS_VIEW)),
):
    mart = await db.get(Mart, mart_id)
    if mart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mart not found")
    return mart


@router.post("/marts", response_model=MartOut, status_code=status.HTTP_201_CREATED)
async def create_mart(
    payload: MartCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.MARTS_MANAGE)),
):
    if await db.get(District, payload.district_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="District does not exist")
    if payload.default_warehouse_id and await db.get(Warehouse, payload.default_warehouse_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warehouse does not exist")
    existing = await db.execute(select(Mart).where(Mart.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mart code already in use")

    mart = Mart(**payload.model_dump())
    db.add(mart)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="mart.create",
                                entity_type="Mart", entity_id=mart.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(mart)
    return mart


@router.patch("/marts/{mart_id}", response_model=MartOut)
async def update_mart(
    mart_id: int,
    payload: MartUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.MARTS_MANAGE)),
):
    mart = await db.get(Mart, mart_id)
    if mart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mart not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(mart, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="mart.update",
                                entity_type="Mart", entity_id=mart.id, new_value=changes)
    await db.commit()
    await db.refresh(mart)
    return mart
