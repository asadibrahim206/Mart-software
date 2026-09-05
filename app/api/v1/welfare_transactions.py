"""
Welfare distribution endpoint — the API surface over welfare_service.create_welfare_transaction.

Also updates the matching program-level WelfareBudget's used_amount (if one exists and is
active for today) and returns a warning flag when the configured threshold is crossed, per
spec section 21 ("warn administrators when a budget approaches or exceeds its threshold").
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.welfare import WelfareBudget, WelfareTransaction, WelfareTransactionStatus
from app.schemas.common import Page, PageMeta
from app.schemas.user import CurrentUser
from app.schemas.welfare import WelfareTransactionCreate, WelfareTransactionOut
from app.services import audit_service, welfare_service

router = APIRouter(prefix="/welfare-transactions", tags=["Welfare Transactions"])


async def _apply_budget_usage(db: AsyncSession, program_id: Optional[int], amount) -> Optional[dict]:
    """Best-effort: bump the active program-level budget's used_amount, return a warning dict
    if the configured threshold is now crossed. Returns None if no matching budget or no value."""
    if program_id is None or amount == 0:
        return None
    today = date.today()
    result = await db.execute(
        select(WelfareBudget).where(
            WelfareBudget.program_id == program_id,
            WelfareBudget.is_active.is_(True),
            WelfareBudget.period_start <= today,
            (WelfareBudget.period_end.is_(None)) | (WelfareBudget.period_end >= today),
        )
    )
    budget = result.scalars().first()
    if budget is None:
        return None

    budget.used_amount += amount
    utilization = (budget.used_amount / budget.total_amount * 100) if budget.total_amount else 0
    if utilization >= budget.warning_threshold_percent:
        return {
            "budget_id": budget.id,
            "budget_name": budget.name,
            "utilization_percent": float(utilization),
            "message": f"Welfare budget '{budget.name}' is at {utilization:.1f}% utilization "
                       f"(threshold: {budget.warning_threshold_percent}%)",
        }
    return None


@router.post("", response_model=WelfareTransactionOut, status_code=status.HTTP_201_CREATED)
async def distribute_welfare(
    payload: WelfareTransactionCreate,
    response: Response,
    mart_id: Optional[int] = Query(None, description="Mart performing the distribution"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_DISTRIBUTE)),
):
    transaction = await welfare_service.create_welfare_transaction(
        db, payload, cashier_user_id=current_user.id, mart_id=mart_id or current_user.mart_id,
    )
    budget_warning = await _apply_budget_usage(db, transaction.program_id, transaction.total_value)
    await db.commit()  # persists the budget usage update regardless of whether a warning fired
    if budget_warning:
        # Surfaced as a header rather than the response body so the wire schema for a successful
        # distribution stays stable — a client that cares can check for this header, others ignore it.
        response.headers["X-Budget-Warning"] = budget_warning["message"]

    return WelfareTransactionOut.model_validate(transaction)


@router.get("", response_model=Page[WelfareTransactionOut])
async def list_welfare_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    beneficiary_id: Optional[int] = None,
    mart_id: Optional[int] = None,
    status_filter: Optional[WelfareTransactionStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    query = select(WelfareTransaction).options(selectinload(WelfareTransaction.items))
    count_query = select(func.count()).select_from(WelfareTransaction)

    filters = []
    if beneficiary_id:
        filters.append(WelfareTransaction.beneficiary_id == beneficiary_id)
    if mart_id:
        filters.append(WelfareTransaction.mart_id == mart_id)
    if status_filter:
        filters.append(WelfareTransaction.status == status_filter)

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total_items = (await db.execute(count_query)).scalar_one()
    query = query.order_by(WelfareTransaction.id.desc()).offset((page - 1) * page_size).limit(page_size)
    transactions = (await db.execute(query)).scalars().all()

    return Page(
        items=transactions,
        meta=PageMeta(page=page, page_size=page_size, total_items=total_items, total_pages=max(1, -(-total_items // page_size))),
    )


@router.get("/{transaction_id}", response_model=WelfareTransactionOut)
async def get_welfare_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    transaction = (await db.execute(
        select(WelfareTransaction).where(WelfareTransaction.id == transaction_id).options(selectinload(WelfareTransaction.items))
    )).scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Welfare transaction not found")
    return transaction


@router.post("/{transaction_id}/void", response_model=WelfareTransactionOut)
async def void_welfare_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_VOID)),
):
    """
    Reverses a transaction: restores entitlement usage for every item and marks it voided.
    The transaction row itself is kept (never deleted) — spec's "never silently delete" applies
    to welfare records just as much as applications.
    """
    from app.services.entitlement_service import get_or_create_usage
    from app.models.welfare import WelfareTransactionItem, EntitlementRule
    from app.models.beneficiary import Beneficiary

    transaction = (await db.execute(
        select(WelfareTransaction).where(WelfareTransaction.id == transaction_id).options(selectinload(WelfareTransaction.items))
    )).scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Welfare transaction not found")
    if transaction.status == WelfareTransactionStatus.VOIDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transaction is already voided")

    beneficiary = await db.get(Beneficiary, transaction.beneficiary_id)
    items_result = await db.execute(select(WelfareTransactionItem).where(WelfareTransactionItem.transaction_id == transaction.id))
    for item in items_result.scalars().all():
        if item.entitlement_rule_id and beneficiary:
            rule = await db.get(EntitlementRule, item.entitlement_rule_id)
            if rule:
                usage = await get_or_create_usage(db, beneficiary.id, rule, transaction.created_at.date())
                usage.used_quantity -= item.quantity

    transaction.status = WelfareTransactionStatus.VOIDED
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="welfare_transaction.void",
        entity_type="WelfareTransaction", entity_id=transaction.id,
        previous_value={"status": "completed"}, new_value={"status": "voided"},
    )
    await db.commit()
    return transaction
