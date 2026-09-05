from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.welfare import EntitlementPeriod, WelfareTransactionStatus


# ---------------------------------------------------------------------------
# Commodities
# ---------------------------------------------------------------------------

class CommodityCreate(BaseModel):
    name: str
    code: str
    unit: str
    description: Optional[str] = None


class CommodityUpdate(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CommodityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    unit: str
    description: Optional[str] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Entitlement rules
# ---------------------------------------------------------------------------

class EntitlementRuleCreate(BaseModel):
    program_id: int
    category_id: Optional[int] = None
    commodity_id: int
    period: EntitlementPeriod
    max_quantity: Decimal
    monetary_limit: Optional[Decimal] = None


class EntitlementRuleUpdate(BaseModel):
    max_quantity: Optional[Decimal] = None
    monetary_limit: Optional[Decimal] = None
    is_active: Optional[bool] = None


class EntitlementRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    program_id: int
    category_id: Optional[int] = None
    commodity_id: int
    period: EntitlementPeriod
    max_quantity: Decimal
    monetary_limit: Optional[Decimal] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Entitlement summary (computed — allocated / used / remaining)
# ---------------------------------------------------------------------------

class EntitlementSummaryItem(BaseModel):
    entitlement_rule_id: int
    commodity_id: int
    commodity_name: str
    unit: str
    period: EntitlementPeriod
    period_key: str
    allocated: Decimal
    used: Decimal
    remaining: Decimal


class EntitlementSummaryOut(BaseModel):
    beneficiary_id: int
    items: list[EntitlementSummaryItem]


# ---------------------------------------------------------------------------
# Welfare budgets
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    name: str
    program_id: int
    district_id: Optional[int] = None
    mart_id: Optional[int] = None
    category_id: Optional[int] = None
    period_start: date
    period_end: Optional[date] = None
    total_amount: Decimal
    warning_threshold_percent: Decimal = Decimal("80.00")


class BudgetUpdate(BaseModel):
    total_amount: Optional[Decimal] = None
    period_end: Optional[date] = None
    warning_threshold_percent: Optional[Decimal] = None
    is_active: Optional[bool] = None


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    program_id: int
    district_id: Optional[int] = None
    mart_id: Optional[int] = None
    category_id: Optional[int] = None
    period_start: date
    period_end: Optional[date] = None
    total_amount: Decimal
    used_amount: Decimal
    warning_threshold_percent: Decimal
    is_active: bool

    @computed_field
    @property
    def remaining_amount(self) -> Decimal:
        return self.total_amount - self.used_amount

    @computed_field
    @property
    def utilization_percent(self) -> Decimal:
        if self.total_amount == 0:
            return Decimal("0.00")
        return (self.used_amount / self.total_amount * 100).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Welfare transactions
# ---------------------------------------------------------------------------

class WelfareTransactionItemIn(BaseModel):
    commodity_id: int
    quantity: Decimal = Field(..., gt=0)
    unit_value: Optional[Decimal] = None


class WelfareTransactionCreate(BaseModel):
    card_number: str = Field(..., description="Scanned/entered welfare card number, e.g. WC-000001")
    items: list[WelfareTransactionItemIn]
    notes: Optional[str] = None


class WelfareTransactionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    commodity_id: int
    entitlement_rule_id: Optional[int] = None
    quantity: Decimal
    unit_value: Optional[Decimal] = None


class WelfareTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    transaction_code: str
    beneficiary_id: int
    card_id: int
    program_id: Optional[int] = None
    mart_id: Optional[int] = None
    cashier_user_id: int
    total_value: Decimal
    status: WelfareTransactionStatus
    notes: Optional[str] = None
    created_at: datetime
    items: list[WelfareTransactionItemOut] = []
