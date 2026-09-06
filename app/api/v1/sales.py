from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.pos import Refund, Sale, SaleStatus
from app.schemas.common import Page, PageMeta
from app.schemas.pos import RefundOut, RefundRequest, SaleCreate, SaleOut
from app.schemas.user import CurrentUser
from app.services import sale_service

router = APIRouter(prefix="/sales", tags=["Sales"])

_LOAD_OPTS = (selectinload(Sale.items), selectinload(Sale.payments))


@router.get("", response_model=Page[SaleOut])
async def list_sales(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mart_id: Optional[int] = None,
    status_filter: Optional[SaleStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    query = select(Sale).options(*_LOAD_OPTS)
    count_query = select(func.count()).select_from(Sale)

    filters = []
    if mart_id:
        filters.append(Sale.mart_id == mart_id)
    if status_filter:
        filters.append(Sale.status == status_filter)
    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total_items = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Sale.id.desc()).offset((page - 1) * page_size).limit(page_size)
    sales = (await db.execute(query)).scalars().unique().all()

    return Page(
        items=sales,
        meta=PageMeta(page=page, page_size=page_size, total_items=total_items, total_pages=max(1, -(-total_items // page_size))),
    )


@router.get("/{sale_id}", response_model=SaleOut)
async def get_sale(
    sale_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    """Doubles as the receipt endpoint — everything needed to print/display a receipt is here."""
    sale = (await db.execute(select(Sale).where(Sale.id == sale_id).options(*_LOAD_OPTS))).scalar_one_or_none()
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return sale


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
async def create_sale(
    payload: SaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    sale, change_due = await sale_service.create_sale(db, payload, cashier_user_id=current_user.id)
    result = SaleOut.model_validate(sale)
    result.change_due = change_due
    return result


@router.post("/{sale_id}/refund", response_model=RefundOut, status_code=status.HTTP_201_CREATED)
async def refund_sale(
    sale_id: int,
    payload: RefundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_REFUND)),
):
    sale = await sale_service.refund_sale(db, sale_id, payload.reason, refunded_by_user_id=current_user.id)
    refund = (await db.execute(select(Refund).where(Refund.sale_id == sale.id).order_by(Refund.id.desc()))).scalars().first()
    return refund
