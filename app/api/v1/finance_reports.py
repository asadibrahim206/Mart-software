"""
Financial reports (spec section 31). Commercial sales and welfare expenditure are always
reported SEPARATELY — never combined into one number — per the platform's core rule that normal
and welfare activity must never mix in reporting.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.finance import Expense, ExpenseCategory, ExpenseStatus
from app.models.inventory import PurchaseOrder, PurchaseOrderStatus
from app.models.pos import CashierShift, Payment, PaymentMethod, PaymentStatus, Sale, SaleStatus, ShiftStatus
from app.models.welfare import WelfareTransaction, WelfareTransactionStatus
from app.schemas.finance import (
    CashReconciliationItem, ExpenseSummaryItem, ExpenseSummaryOut, PurchaseSummaryOut,
    SalesSummaryOut, WelfareExpenditureOut,
)
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/reports", tags=["Financial Reports"])


@router.get("/sales-summary", response_model=SalesSummaryOut)
async def sales_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    mart_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    sale_filters = [Sale.status == SaleStatus.COMPLETED]
    refund_filters = [Sale.status == SaleStatus.REFUNDED]
    if date_from:
        sale_filters.append(Sale.created_at >= date_from)
        refund_filters.append(Sale.created_at >= date_from)
    if date_to:
        sale_filters.append(Sale.created_at <= date_to)
        refund_filters.append(Sale.created_at <= date_to)
    if mart_id:
        sale_filters.append(Sale.mart_id == mart_id)
        refund_filters.append(Sale.mart_id == mart_id)

    total_sales, count = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0), func.count()).where(*sale_filters)
    )).first()
    total_refunds = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(*refund_filters)
    )).scalar_one()

    method_totals = dict((await db.execute(
        select(Payment.method, func.coalesce(func.sum(Payment.amount), 0))
        .join(Sale, Sale.id == Payment.sale_id)
        .where(*sale_filters, Payment.status == PaymentStatus.COMPLETED)
        .group_by(Payment.method)
    )).all())

    return SalesSummaryOut(
        period_start=date_from, period_end=date_to,
        total_sales=total_sales, total_refunds=total_refunds, net_sales=total_sales - total_refunds,
        cash_total=method_totals.get(PaymentMethod.CASH, Decimal("0")), card_total=method_totals.get(PaymentMethod.CARD, Decimal("0")),
        digital_total=method_totals.get(PaymentMethod.DIGITAL, Decimal("0")), transaction_count=count,
    )


@router.get("/purchase-summary", response_model=PurchaseSummaryOut)
async def purchase_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    filters = [PurchaseOrder.status == PurchaseOrderStatus.RECEIVED]
    if date_from:
        filters.append(PurchaseOrder.received_at >= date_from)
    if date_to:
        filters.append(PurchaseOrder.received_at <= date_to)

    total_amount, count = (await db.execute(
        select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0), func.count()).where(*filters)
    )).first()

    return PurchaseSummaryOut(period_start=date_from, period_end=date_to, total_purchase_orders=count, total_amount_received=total_amount)


@router.get("/expenses-summary", response_model=ExpenseSummaryOut)
async def expenses_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    filters = [Expense.status == ExpenseStatus.PAID]
    if date_from:
        filters.append(Expense.expense_date >= date_from)
    if date_to:
        filters.append(Expense.expense_date <= date_to)

    rows = (await db.execute(
        select(ExpenseCategory.id, ExpenseCategory.name, func.coalesce(func.sum(Expense.amount), 0), func.count())
        .join(Expense, Expense.category_id == ExpenseCategory.id)
        .where(*filters)
        .group_by(ExpenseCategory.id, ExpenseCategory.name)
    )).all()

    by_category = [ExpenseSummaryItem(category_id=r[0], category_name=r[1], total_amount=r[2], count=r[3]) for r in rows]
    total = sum((item.total_amount for item in by_category), Decimal("0"))

    return ExpenseSummaryOut(period_start=date_from, period_end=date_to, by_category=by_category, total_amount=total)


@router.get("/welfare-expenditure", response_model=WelfareExpenditureOut)
async def welfare_expenditure_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    program_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    filters = [WelfareTransaction.status == WelfareTransactionStatus.COMPLETED]
    if date_from:
        filters.append(WelfareTransaction.created_at >= date_from)
    if date_to:
        filters.append(WelfareTransaction.created_at <= date_to)
    if program_id:
        filters.append(WelfareTransaction.program_id == program_id)

    total_value, count = (await db.execute(
        select(func.coalesce(func.sum(WelfareTransaction.total_value), 0), func.count()).where(*filters)
    )).first()

    return WelfareExpenditureOut(period_start=date_from, period_end=date_to, total_transactions=count, total_value=total_value)


@router.get("/cash-reconciliation", response_model=list[CashReconciliationItem])
async def cash_reconciliation_report(
    mart_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    """Every closed shift's expected-vs-actual cash — the reconciliation record from spec section 25."""
    query = select(CashierShift).where(CashierShift.status == ShiftStatus.CLOSED).order_by(CashierShift.closed_at.desc())
    if mart_id:
        query = query.where(CashierShift.mart_id == mart_id)
    if date_from:
        query = query.where(CashierShift.closed_at >= date_from)
    if date_to:
        query = query.where(CashierShift.closed_at <= date_to)

    shifts = (await db.execute(query)).scalars().all()
    return [
        CashReconciliationItem(
            shift_id=s.id, shift_code=s.shift_code, user_id=s.user_id, mart_id=s.mart_id,
            opened_at=s.opened_at, closed_at=s.closed_at, opening_cash=s.opening_cash,
            expected_cash=s.expected_cash, actual_cash=s.actual_cash, cash_difference=s.cash_difference,
        )
        for s in shifts
    ]
