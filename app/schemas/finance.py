from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.finance import ExpenseStatus
from app.models.pos import PaymentMethod


# ---------------------------------------------------------------------------
# Expense categories
# ---------------------------------------------------------------------------

class ExpenseCategoryCreate(BaseModel):
    name: str
    code: str


class ExpenseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    is_active: bool


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

class ExpenseCreate(BaseModel):
    category_id: int
    mart_id: Optional[int] = None
    department: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    expense_date: date
    description: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None


class ExpenseDecision(BaseModel):
    reason: Optional[str] = Field(None, description="Required when rejecting")


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    expense_code: str
    category_id: int
    mart_id: Optional[int] = None
    department: Optional[str] = None
    amount: Decimal
    expense_date: date
    description: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    status: ExpenseStatus
    submitted_by_user_id: int
    approved_by_user_id: Optional[int] = None
    rejection_reason: Optional[str] = None
    paid_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Supplier payments / payables
# ---------------------------------------------------------------------------

class SupplierPaymentCreate(BaseModel):
    supplier_id: int
    purchase_order_id: Optional[int] = None
    amount: Decimal = Field(..., gt=0)
    payment_date: date
    method: PaymentMethod
    reference: Optional[str] = None
    notes: Optional[str] = None


class SupplierPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    purchase_order_id: Optional[int] = None
    amount: Decimal
    payment_date: date
    method: PaymentMethod
    reference: Optional[str] = None
    notes: Optional[str] = None
    recorded_by_user_id: int


class SupplierPayableOut(BaseModel):
    supplier_id: int
    supplier_name: str
    total_received: Decimal
    total_paid: Decimal
    balance_due: Decimal


# ---------------------------------------------------------------------------
# Financial reports
# ---------------------------------------------------------------------------

class SalesSummaryOut(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_sales: Decimal
    total_refunds: Decimal
    net_sales: Decimal
    cash_total: Decimal
    card_total: Decimal
    digital_total: Decimal
    transaction_count: int


class PurchaseSummaryOut(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_purchase_orders: int
    total_amount_received: Decimal


class ExpenseSummaryItem(BaseModel):
    category_id: int
    category_name: str
    total_amount: Decimal
    count: int


class ExpenseSummaryOut(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    by_category: list[ExpenseSummaryItem]
    total_amount: Decimal


class WelfareExpenditureOut(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_transactions: int
    total_value: Decimal


class CashReconciliationItem(BaseModel):
    shift_id: int
    shift_code: str
    user_id: int
    mart_id: int
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opening_cash: Decimal
    expected_cash: Optional[Decimal] = None
    actual_cash: Optional[Decimal] = None
    cash_difference: Optional[Decimal] = None
