from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.pos import CashierShift, ShiftStatus
from app.schemas.pos import ShiftCloseRequest, ShiftOpenRequest, ShiftOut
from app.schemas.user import CurrentUser
from app.services import audit_service, sale_service
from app.services.application_service import make_code

router = APIRouter(prefix="/cashier-shifts", tags=["Cashier Shifts"])


@router.get("", response_model=list[ShiftOut])
async def list_shifts(
    mart_id: Optional[int] = None,
    status_filter: Optional[ShiftStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    query = select(CashierShift).order_by(CashierShift.id.desc())
    if mart_id:
        query = query.where(CashierShift.mart_id == mart_id)
    if status_filter:
        query = query.where(CashierShift.status == status_filter)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/my-open-shift", response_model=Optional[ShiftOut])
async def get_my_open_shift(
    mart_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    """Convenience lookup for a POS UI to check whether the current cashier already has a shift open."""
    result = await db.execute(
        select(CashierShift).where(
            CashierShift.user_id == current_user.id, CashierShift.mart_id == mart_id, CashierShift.status == ShiftStatus.OPEN,
        )
    )
    return result.scalar_one_or_none()


@router.post("/open", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(
    payload: ShiftOpenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_SELL)),
):
    existing = await db.execute(
        select(CashierShift).where(
            CashierShift.user_id == current_user.id, CashierShift.mart_id == payload.mart_id, CashierShift.status == ShiftStatus.OPEN,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have an open shift at this mart — close it before opening a new one")

    shift = CashierShift(
        shift_code="PENDING", user_id=current_user.id, mart_id=payload.mart_id,
        status=ShiftStatus.OPEN, opening_cash=payload.opening_cash, opened_at=datetime.now(timezone.utc),
    )
    db.add(shift)
    await db.flush()
    shift.shift_code = make_code("SHIFT", shift.id)

    await audit_service.record(db, user_id=current_user.id, role_name=None, action="cashier_shift.open",
                                entity_type="CashierShift", entity_id=shift.id, new_value={"mart_id": payload.mart_id})
    await db.commit()
    await db.refresh(shift)
    return shift


@router.post("/{shift_id}/close", response_model=ShiftOut)
async def close_shift_endpoint(
    shift_id: int,
    payload: ShiftCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.POS_CLOSE_SHIFT)),
):
    shift = await db.get(CashierShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    updated = await sale_service.close_shift(db, shift, payload.actual_cash, payload.notes, current_user.id)
    return updated
