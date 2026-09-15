"""
Welfare reports (spec section 29): distribution over time and by dimension, plus aggregate
entitlement utilization across every beneficiary — the org-wide view, as opposed to
/beneficiaries/{id}/entitlements which is the per-beneficiary view from Phase 3.
"""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Beneficiary, BeneficiaryCategory
from app.models.organization import District, Mart
from app.models.welfare import (
    BeneficiaryEntitlementUsage, Commodity, EntitlementRule, WelfareTransaction,
    WelfareTransactionItem, WelfareTransactionStatus,
)
from app.schemas.analytics import (
    EntitlementUtilizationItem, WelfareByDimensionItem, WelfareByPeriodItem,
)
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/reports", tags=["Welfare Reports"])


@router.get("/welfare-distribution-by-period", response_model=list[WelfareByPeriodItem])
async def welfare_by_period(
    granularity: Literal["day", "month"] = "day",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    date_trunc_format = "YYYY-MM" if granularity == "month" else "YYYY-MM-DD"
    period_expr = func.to_char(WelfareTransaction.created_at, date_trunc_format)

    filters = [WelfareTransaction.status == WelfareTransactionStatus.COMPLETED]
    if date_from:
        filters.append(WelfareTransaction.created_at >= date_from)
    if date_to:
        filters.append(WelfareTransaction.created_at <= date_to)

    rows = (await db.execute(
        select(period_expr.label("period_key"), func.count(), func.coalesce(func.sum(WelfareTransaction.total_value), 0))
        .where(*filters).group_by(period_expr).order_by(period_expr)
    )).all()

    return [WelfareByPeriodItem(period_key=r[0], transaction_count=r[1], total_value=r[2]) for r in rows]


@router.get("/welfare-distribution-by-dimension", response_model=list[WelfareByDimensionItem])
async def welfare_by_dimension(
    dimension: Literal["category", "district", "mart", "commodity"],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    filters = [WelfareTransaction.status == WelfareTransactionStatus.COMPLETED]
    if date_from:
        filters.append(WelfareTransaction.created_at >= date_from)
    if date_to:
        filters.append(WelfareTransaction.created_at <= date_to)

    if dimension == "commodity":
        rows = (await db.execute(
            select(Commodity.id, Commodity.name, func.count(func.distinct(WelfareTransaction.id)),
                   func.coalesce(func.sum(WelfareTransactionItem.quantity * func.coalesce(WelfareTransactionItem.unit_value, 0)), 0),
                   func.coalesce(func.sum(WelfareTransactionItem.quantity), 0))
            .select_from(WelfareTransactionItem)
            .join(WelfareTransaction, WelfareTransaction.id == WelfareTransactionItem.transaction_id)
            .join(Commodity, Commodity.id == WelfareTransactionItem.commodity_id)
            .where(*filters)
            .group_by(Commodity.id, Commodity.name)
        )).all()
        return [WelfareByDimensionItem(key=str(r[0]), label=r[1], transaction_count=r[2], total_value=r[3], total_quantity=r[4]) for r in rows]

    if dimension == "mart":
        rows = (await db.execute(
            select(Mart.id, Mart.name, func.count(), func.coalesce(func.sum(WelfareTransaction.total_value), 0))
            .join(Mart, Mart.id == WelfareTransaction.mart_id).where(*filters).group_by(Mart.id, Mart.name)
        )).all()
        return [WelfareByDimensionItem(key=str(r[0]), label=r[1], transaction_count=r[2], total_value=r[3], total_quantity=Decimal("0")) for r in rows]

    if dimension == "district":
        rows = (await db.execute(
            select(District.id, District.name, func.count(), func.coalesce(func.sum(WelfareTransaction.total_value), 0))
            .select_from(WelfareTransaction)
            .join(Beneficiary, Beneficiary.id == WelfareTransaction.beneficiary_id)
            .join(District, District.id == Beneficiary.district_id)
            .where(*filters).group_by(District.id, District.name)
        )).all()
        return [WelfareByDimensionItem(key=str(r[0]), label=r[1], transaction_count=r[2], total_value=r[3], total_quantity=Decimal("0")) for r in rows]

    # category
    rows = (await db.execute(
        select(BeneficiaryCategory.id, BeneficiaryCategory.name, func.count(), func.coalesce(func.sum(WelfareTransaction.total_value), 0))
        .select_from(WelfareTransaction)
        .join(Beneficiary, Beneficiary.id == WelfareTransaction.beneficiary_id)
        .join(BeneficiaryCategory, BeneficiaryCategory.id == Beneficiary.category_id)
        .where(*filters).group_by(BeneficiaryCategory.id, BeneficiaryCategory.name)
    )).all()
    return [WelfareByDimensionItem(key=str(r[0]), label=r[1], transaction_count=r[2], total_value=r[3], total_quantity=Decimal("0")) for r in rows]


@router.get("/entitlement-utilization", response_model=list[EntitlementUtilizationItem])
async def entitlement_utilization(
    program_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    """Org-wide: how much of what's been allocated has actually been used, per commodity."""
    query = (
        select(
            Commodity.id, Commodity.name,
            func.coalesce(func.sum(BeneficiaryEntitlementUsage.allocated_quantity), 0),
            func.coalesce(func.sum(BeneficiaryEntitlementUsage.used_quantity), 0),
        )
        .select_from(BeneficiaryEntitlementUsage)
        .join(EntitlementRule, EntitlementRule.id == BeneficiaryEntitlementUsage.entitlement_rule_id)
        .join(Commodity, Commodity.id == EntitlementRule.commodity_id)
        .group_by(Commodity.id, Commodity.name)
    )
    if program_id:
        query = query.where(EntitlementRule.program_id == program_id)

    rows = (await db.execute(query)).all()
    results = []
    for commodity_id, name, allocated, used in rows:
        remaining = allocated - used
        utilization = (used / allocated * 100).quantize(Decimal("0.01")) if allocated else Decimal("0.00")
        results.append(EntitlementUtilizationItem(
            commodity_id=commodity_id, commodity_name=name, total_allocated=allocated,
            total_used=used, total_remaining=remaining, utilization_percent=utilization,
        ))
    return results
