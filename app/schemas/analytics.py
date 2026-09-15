from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardOut(BaseModel):
    total_sales: Decimal
    today_sales: Decimal
    monthly_sales: Decimal
    welfare_distributed_value: Decimal
    welfare_transaction_count: int
    active_beneficiaries: int
    active_cards: int
    pending_applications: int
    approved_applications: int
    rejected_applications: int
    low_stock_product_count: int
    expiring_soon_product_count: int
    supplier_payables_total: Decimal
    pending_expenses_total: Decimal
    welfare_budget_remaining: Decimal


# ---------------------------------------------------------------------------
# Beneficiary reports
# ---------------------------------------------------------------------------

class CategoryDistributionItem(BaseModel):
    category_id: Optional[int] = None
    category_name: str
    count: int


class DistrictDistributionItem(BaseModel):
    district_id: int
    district_name: str
    count: int


class FamilySizeBucketItem(BaseModel):
    bucket: str
    count: int


class ApplicationFunnelOut(BaseModel):
    draft: int
    submitted: int
    under_review: int
    verification: int
    approved: int
    card_issued: int
    rejected: int
    request_more_info: int
    suspended: int
    expired: int
    deactivated: int


class BeneficiaryReportOut(BaseModel):
    total_beneficiaries: int
    active_beneficiaries: int
    suspended_beneficiaries: int
    by_category: list[CategoryDistributionItem]
    by_district: list[DistrictDistributionItem]
    by_family_size: list[FamilySizeBucketItem]
    application_funnel: ApplicationFunnelOut


# ---------------------------------------------------------------------------
# Welfare reports
# ---------------------------------------------------------------------------

class WelfareByPeriodItem(BaseModel):
    period_key: str   # date or "YYYY-MM"
    transaction_count: int
    total_value: Decimal


class WelfareByDimensionItem(BaseModel):
    key: str
    label: str
    transaction_count: int
    total_value: Decimal
    total_quantity: Decimal


class EntitlementUtilizationItem(BaseModel):
    commodity_id: int
    commodity_name: str
    total_allocated: Decimal
    total_used: Decimal
    total_remaining: Decimal
    utilization_percent: Decimal


# ---------------------------------------------------------------------------
# Inventory reports
# ---------------------------------------------------------------------------

class StockValuationItem(BaseModel):
    product_id: int
    product_name: str
    warehouse_id: int
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal


class StockMovementSummaryItem(BaseModel):
    movement_type: str
    total_quantity: Decimal
    movement_count: int
