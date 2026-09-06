from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.pos import PaymentMethod, PaymentStatus, SaleStatus, ShiftStatus


# ---------------------------------------------------------------------------
# Cashier shifts
# ---------------------------------------------------------------------------

class ShiftOpenRequest(BaseModel):
    mart_id: int
    opening_cash: Decimal = Decimal("0")


class ShiftCloseRequest(BaseModel):
    actual_cash: Decimal = Field(..., description="Physically counted cash at close")
    notes: Optional[str] = None


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shift_code: str
    user_id: int
    mart_id: int
    status: ShiftStatus
    opening_cash: Decimal
    opened_at: datetime
    closed_at: Optional[datetime] = None
    cash_sales_total: Decimal
    card_sales_total: Decimal
    digital_sales_total: Decimal
    welfare_distribution_value: Decimal
    refunds_total: Decimal
    expected_cash: Optional[Decimal] = None
    actual_cash: Optional[Decimal] = None
    cash_difference: Optional[Decimal] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

class SaleItemIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(..., gt=0)
    unit_price: Optional[Decimal] = Field(None, description="Defaults to the product's selling_price if omitted")
    discount_amount: Decimal = Decimal("0")


class SaleCreate(BaseModel):
    mart_id: int
    items: list[SaleItemIn]
    payment_method: PaymentMethod
    cash_tendered: Optional[Decimal] = Field(None, description="For cash payments — used to compute change due")
    discount_amount: Decimal = Decimal("0")
    notes: Optional[str] = None


class SaleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    method: PaymentMethod
    amount: Decimal
    status: PaymentStatus
    reference: Optional[str] = None


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sale_code: str
    mart_id: int
    cashier_shift_id: int
    cashier_user_id: int
    subtotal: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    status: SaleStatus
    notes: Optional[str] = None
    created_at: datetime
    items: list[SaleItemOut] = []
    payments: list[PaymentOut] = []
    change_due: Optional[Decimal] = None   # computed, not persisted — only present right after creation


class RefundRequest(BaseModel):
    reason: str


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sale_id: int
    refunded_by_user_id: int
    amount: Decimal
    reason: str
