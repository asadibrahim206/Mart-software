"""
Dashboard (spec section 27): answers "how is the organization performing" in one call.
Deliberately kept as plain sequential queries rather than one giant join — each metric comes
from a different module's tables, and clarity here matters more than shaving a few queries.
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import (
    Application, ApplicationStatus, Beneficiary, BeneficiaryStatus, CardStatus, WelfareCard,
)
from app.models.finance import Expense, ExpenseStatus, SupplierPayment
from app.models.inventory import Product, PurchaseOrder, PurchaseOrderStatus, Stock
from app.models.pos import Sale, SaleStatus
from app.models.welfare import WelfareBudget, WelfareTransaction, WelfareTransactionStatus
from app.schemas.analytics import DashboardOut
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/reports", tags=["Dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.REPORTS_VIEW)),
):
    today = date.today()
    month_start = today.replace(day=1)

    total_sales = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(Sale.status == SaleStatus.COMPLETED)
    )).scalar_one()
    today_sales = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= today)
    )).scalar_one()
    monthly_sales = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= month_start)
    )).scalar_one()

    welfare_value, welfare_count = (await db.execute(
        select(func.coalesce(func.sum(WelfareTransaction.total_value), 0), func.count())
        .where(WelfareTransaction.status == WelfareTransactionStatus.COMPLETED)
    )).first()

    active_beneficiaries = (await db.execute(
        select(func.count()).select_from(Beneficiary).where(Beneficiary.status == BeneficiaryStatus.ACTIVE)
    )).scalar_one()
    active_cards = (await db.execute(
        select(func.count()).select_from(WelfareCard).where(WelfareCard.status == CardStatus.ACTIVE)
    )).scalar_one()

    pending_statuses = [
        ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW,
        ApplicationStatus.VERIFICATION, ApplicationStatus.REQUEST_MORE_INFO,
    ]
    pending_applications = (await db.execute(
        select(func.count()).select_from(Application).where(Application.status.in_(pending_statuses))
    )).scalar_one()
    approved_applications = (await db.execute(
        select(func.count()).select_from(Application).where(Application.status.in_([ApplicationStatus.APPROVED, ApplicationStatus.CARD_ISSUED]))
    )).scalar_one()
    rejected_applications = (await db.execute(
        select(func.count()).select_from(Application).where(Application.status == ApplicationStatus.REJECTED)
    )).scalar_one()

    low_stock_count = (await db.execute(
        select(func.count()).select_from(
            select(Product.id)
            .outerjoin(Stock, Stock.product_id == Product.id)
            .where(Product.is_active.is_(True))
            .group_by(Product.id)
            .having(func.coalesce(func.sum(Stock.quantity), 0) <= Product.reorder_level)
            .subquery()
        )
    )).scalar_one()

    expiring_cutoff = today + timedelta(days=30)
    expiring_count = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_active.is_(True), Product.expiry_date.is_not(None), Product.expiry_date <= expiring_cutoff,
        )
    )).scalar_one()

    received_by_supplier = dict((await db.execute(
        select(PurchaseOrder.supplier_id, func.coalesce(func.sum(PurchaseOrder.total_amount), 0))
        .where(PurchaseOrder.status == PurchaseOrderStatus.RECEIVED).group_by(PurchaseOrder.supplier_id)
    )).all())
    paid_by_supplier = dict((await db.execute(
        select(SupplierPayment.supplier_id, func.coalesce(func.sum(SupplierPayment.amount), 0)).group_by(SupplierPayment.supplier_id)
    )).all())
    payables_total = sum(
        (received_by_supplier.get(sid, Decimal("0")) - paid_by_supplier.get(sid, Decimal("0")) for sid in received_by_supplier),
        Decimal("0"),
    )

    pending_expenses_total = (await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.status == ExpenseStatus.SUBMITTED)
    )).scalar_one()

    budget_rows = (await db.execute(
        select(WelfareBudget.total_amount, WelfareBudget.used_amount).where(
            WelfareBudget.is_active.is_(True), WelfareBudget.period_start <= today,
            (WelfareBudget.period_end.is_(None)) | (WelfareBudget.period_end >= today),
        )
    )).all()
    budget_remaining = sum((row[0] - row[1] for row in budget_rows), Decimal("0"))

    return DashboardOut(
        total_sales=total_sales, today_sales=today_sales, monthly_sales=monthly_sales,
        welfare_distributed_value=welfare_value, welfare_transaction_count=welfare_count,
        active_beneficiaries=active_beneficiaries, active_cards=active_cards,
        pending_applications=pending_applications, approved_applications=approved_applications,
        rejected_applications=rejected_applications, low_stock_product_count=low_stock_count,
        expiring_soon_product_count=expiring_count, supplier_payables_total=payables_total,
        pending_expenses_total=pending_expenses_total, welfare_budget_remaining=budget_remaining,
    )
