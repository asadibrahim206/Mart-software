from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.inventory import Product, Stock, StockMovement
from app.schemas.analytics import StockMovementSummaryItem, StockValuationItem
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/reports", tags=["Inventory Reports"])


@router.get("/stock-valuation", response_model=list[StockValuationItem])
async def stock_valuation(
    warehouse_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    """Current stock valued at purchase price — spec section 30's 'stock valuation' report."""
    query = (
        select(Product.id, Product.name, Stock.warehouse_id, Stock.quantity, Product.purchase_price)
        .join(Stock, Stock.product_id == Product.id)
        .where(Stock.quantity > 0)
    )
    if warehouse_id:
        query = query.where(Stock.warehouse_id == warehouse_id)

    rows = (await db.execute(query)).all()
    return [
        StockValuationItem(
            product_id=r[0], product_name=r[1], warehouse_id=r[2], quantity=r[3],
            unit_cost=r[4], total_value=r[3] * r[4],
        )
        for r in rows
    ]


@router.get("/stock-movement-summary", response_model=list[StockMovementSummaryItem])
async def stock_movement_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    warehouse_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    """Totals by movement type — explains where stock came from and where it went (spec section 30)."""
    filters = []
    if date_from:
        filters.append(StockMovement.created_at >= date_from)
    if date_to:
        filters.append(StockMovement.created_at <= date_to)
    if warehouse_id:
        filters.append(StockMovement.warehouse_id == warehouse_id)

    query = select(
        StockMovement.movement_type, func.coalesce(func.sum(StockMovement.quantity_delta), 0), func.count(),
    ).group_by(StockMovement.movement_type)
    for condition in filters:
        query = query.where(condition)

    rows = (await db.execute(query)).all()
    return [StockMovementSummaryItem(movement_type=r[0].value, total_quantity=r[1], movement_count=r[2]) for r in rows]
