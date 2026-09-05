from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.inventory import Product, Stock, StockMovement, StockMovementType
from app.schemas.inventory import (
    DamageExpiryRequest, ProductOut, StockAdjustmentRequest, StockMovementOut, StockOut,
)
from app.schemas.user import CurrentUser
from app.services import audit_service, stock_service

router = APIRouter(tags=["Stock"])


@router.get("/stock", response_model=list[StockOut])
async def list_stock(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    query = select(Stock)
    if warehouse_id:
        query = query.where(Stock.warehouse_id == warehouse_id)
    if product_id:
        query = query.where(Stock.product_id == product_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/stock/movements", response_model=list[StockMovementOut])
async def list_stock_movements(
    product_id: int | None = None,
    warehouse_id: int | None = None,
    movement_type: StockMovementType | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    """The stock ledger — spec section 17: explains exactly why current stock is what it is."""
    query = select(StockMovement).order_by(StockMovement.id.desc()).limit(limit)
    if product_id:
        query = query.where(StockMovement.product_id == product_id)
    if warehouse_id:
        query = query.where(StockMovement.warehouse_id == warehouse_id)
    if movement_type:
        query = query.where(StockMovement.movement_type == movement_type)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/stock/adjustments", response_model=StockMovementOut, status_code=status.HTTP_201_CREATED)
async def create_stock_adjustment(
    payload: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    """Manual correction — always requires a reason, always logged (spec: 'never modify stock silently')."""
    if await db.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not exist")

    movement = await stock_service.apply_movement(
        db, product_id=payload.product_id, warehouse_id=payload.warehouse_id,
        movement_type=StockMovementType.ADJUSTMENT, quantity_delta=payload.quantity_delta,
        performed_by_user_id=current_user.id, notes=payload.reason,
    )
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="stock.adjustment",
        entity_type="StockMovement", entity_id=movement.id,
        new_value={"product_id": payload.product_id, "warehouse_id": payload.warehouse_id,
                   "quantity_delta": str(payload.quantity_delta), "reason": payload.reason},
    )
    await db.commit()
    await db.refresh(movement)
    return movement


@router.post("/stock/damage", response_model=StockMovementOut, status_code=status.HTTP_201_CREATED)
async def record_damage(
    payload: DamageExpiryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    if await db.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not exist")
    movement = await stock_service.apply_movement(
        db, product_id=payload.product_id, warehouse_id=payload.warehouse_id,
        movement_type=StockMovementType.DAMAGE, quantity_delta=-payload.quantity,
        performed_by_user_id=current_user.id, notes=payload.notes,
    )
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="stock.damage",
                                entity_type="StockMovement", entity_id=movement.id,
                                new_value={"product_id": payload.product_id, "quantity": str(payload.quantity)})
    await db.commit()
    await db.refresh(movement)
    return movement


@router.post("/stock/expiry", response_model=StockMovementOut, status_code=status.HTTP_201_CREATED)
async def record_expiry(
    payload: DamageExpiryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    if await db.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product does not exist")
    movement = await stock_service.apply_movement(
        db, product_id=payload.product_id, warehouse_id=payload.warehouse_id,
        movement_type=StockMovementType.EXPIRY, quantity_delta=-payload.quantity,
        performed_by_user_id=current_user.id, notes=payload.notes,
    )
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="stock.expiry",
                                entity_type="StockMovement", entity_id=movement.id,
                                new_value={"product_id": payload.product_id, "quantity": str(payload.quantity)})
    await db.commit()
    await db.refresh(movement)
    return movement


@router.get("/reports/low-stock", response_model=list[ProductOut])
async def low_stock_report(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    """Products where total stock across all warehouses is at or below their reorder level."""
    result = await db.execute(
        select(Product, func.coalesce(func.sum(Stock.quantity), 0).label("total_qty"))
        .outerjoin(Stock, Stock.product_id == Product.id)
        .where(Product.is_active.is_(True))
        .group_by(Product.id)
        .having(func.coalesce(func.sum(Stock.quantity), 0) <= Product.reorder_level)
    )
    return [row[0] for row in result.all()]


@router.get("/reports/expiring", response_model=list[ProductOut])
async def expiring_soon_report(
    within_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    cutoff = date.today() + timedelta(days=within_days)
    result = await db.execute(
        select(Product).where(
            Product.is_active.is_(True),
            Product.expiry_date.is_not(None),
            Product.expiry_date <= cutoff,
        ).order_by(Product.expiry_date)
    )
    return result.scalars().all()
