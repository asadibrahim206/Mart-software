from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.finance import Expense, ExpenseCategory, ExpenseStatus, SupplierPayment
from app.models.inventory import PurchaseOrder, PurchaseOrderStatus, Supplier
from app.schemas.finance import (
    ExpenseCategoryCreate, ExpenseCategoryOut, ExpenseCreate, ExpenseDecision, ExpenseOut,
    SupplierPayableOut, SupplierPaymentCreate, SupplierPaymentOut,
)
from app.schemas.user import CurrentUser
from app.services import audit_service
from app.services.application_service import make_code

router = APIRouter(tags=["Finance"])


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
async def list_expense_categories(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    result = await db.execute(select(ExpenseCategory).where(ExpenseCategory.is_active.is_(True)).order_by(ExpenseCategory.name))
    return result.scalars().all()


@router.post("/expense-categories", response_model=ExpenseCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_expense_category(
    payload: ExpenseCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    existing = await db.execute(select(ExpenseCategory).where(ExpenseCategory.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category code already in use")
    category = ExpenseCategory(**payload.model_dump())
    db.add(category)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="expense_category.create",
                                entity_type="ExpenseCategory", entity_id=category.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(category)
    return category


@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(
    status_filter: Optional[ExpenseStatus] = Query(None, alias="status"),
    mart_id: Optional[int] = None,
    category_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    query = select(Expense).order_by(Expense.id.desc())
    if status_filter:
        query = query.where(Expense.status == status_filter)
    if mart_id:
        query = query.where(Expense.mart_id == mart_id)
    if category_id:
        query = query.where(Expense.category_id == category_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    if await db.get(ExpenseCategory, payload.category_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expense category does not exist")

    expense = Expense(
        expense_code="PENDING", status=ExpenseStatus.SUBMITTED, submitted_by_user_id=current_user.id,
        **payload.model_dump(),
    )
    db.add(expense)
    await db.flush()
    expense.expense_code = make_code("EXP", expense.id)

    await audit_service.record(db, user_id=current_user.id, role_name=None, action="expense.submit",
                                entity_type="Expense", entity_id=expense.id, new_value={"amount": str(payload.amount)})
    await db.commit()
    await db.refresh(expense)
    return expense


@router.post("/expenses/{expense_id}/approve", response_model=ExpenseOut)
async def approve_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    expense = await db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.status != ExpenseStatus.SUBMITTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot approve an expense in status '{expense.status.value}'")

    expense.status = ExpenseStatus.APPROVED
    expense.approved_by_user_id = current_user.id
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="expense.approve",
                                entity_type="Expense", entity_id=expense.id)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.post("/expenses/{expense_id}/reject", response_model=ExpenseOut)
async def reject_expense(
    expense_id: int,
    payload: ExpenseDecision,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    expense = await db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.status != ExpenseStatus.SUBMITTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot reject an expense in status '{expense.status.value}'")
    if not payload.reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A reason is required to reject an expense")

    expense.status = ExpenseStatus.REJECTED
    expense.rejection_reason = payload.reason
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="expense.reject",
                                entity_type="Expense", entity_id=expense.id, new_value={"reason": payload.reason})
    await db.commit()
    await db.refresh(expense)
    return expense


@router.post("/expenses/{expense_id}/pay", response_model=ExpenseOut)
async def pay_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    expense = await db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.status != ExpenseStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot pay an expense in status '{expense.status.value}' — it must be APPROVED first")

    expense.status = ExpenseStatus.PAID
    expense.paid_at = datetime.now(timezone.utc)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="expense.pay",
                                entity_type="Expense", entity_id=expense.id, new_value={"amount": str(expense.amount)})
    await db.commit()
    await db.refresh(expense)
    return expense


@router.get("/supplier-payments", response_model=list[SupplierPaymentOut])
async def list_supplier_payments(
    supplier_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    query = select(SupplierPayment).order_by(SupplierPayment.id.desc())
    if supplier_id:
        query = query.where(SupplierPayment.supplier_id == supplier_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/supplier-payments", response_model=SupplierPaymentOut, status_code=status.HTTP_201_CREATED)
async def create_supplier_payment(
    payload: SupplierPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_MANAGE)),
):
    if await db.get(Supplier, payload.supplier_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier does not exist")
    if payload.purchase_order_id and await db.get(PurchaseOrder, payload.purchase_order_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Purchase order does not exist")

    payment = SupplierPayment(recorded_by_user_id=current_user.id, **payload.model_dump())
    db.add(payment)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="supplier_payment.create",
                                entity_type="SupplierPayment", entity_id=payment.id,
                                new_value={"supplier_id": payload.supplier_id, "amount": str(payload.amount)})
    await db.commit()
    await db.refresh(payment)
    return payment


@router.get("/reports/payables", response_model=list[SupplierPayableOut])
async def payables_report(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.FINANCE_VIEW)),
):
    """What's owed to each supplier: received purchase orders minus payments made — computed fresh, never stored."""
    received_by_supplier = dict((await db.execute(
        select(PurchaseOrder.supplier_id, func.coalesce(func.sum(PurchaseOrder.total_amount), 0))
        .where(PurchaseOrder.status == PurchaseOrderStatus.RECEIVED)
        .group_by(PurchaseOrder.supplier_id)
    )).all())
    paid_by_supplier = dict((await db.execute(
        select(SupplierPayment.supplier_id, func.coalesce(func.sum(SupplierPayment.amount), 0))
        .group_by(SupplierPayment.supplier_id)
    )).all())

    suppliers = (await db.execute(select(Supplier))).scalars().all()
    results = []
    for supplier in suppliers:
        received = received_by_supplier.get(supplier.id, 0)
        paid = paid_by_supplier.get(supplier.id, 0)
        if received or paid:
            results.append(SupplierPayableOut(
                supplier_id=supplier.id, supplier_name=supplier.company_name,
                total_received=received, total_paid=paid, balance_due=received - paid,
            ))
    return results
