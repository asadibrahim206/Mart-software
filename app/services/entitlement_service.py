"""
Entitlement calculation engine.

The central rule (spec section 12): for every beneficiary/commodity, always be able to answer
ALLOCATED / USED / REMAINING. This module is the only place that computes those numbers — the
welfare transaction service (welfare_service.py) calls into it to check availability before
deducting, and the API layer calls it to display a beneficiary's current entitlement summary.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.beneficiary import Beneficiary
from app.models.welfare import (
    BeneficiaryEntitlementUsage, Commodity, EntitlementPeriod, EntitlementRule,
)


def get_period_key(period: EntitlementPeriod, on_date: date) -> str:
    """The identifier for 'which period instance' a usage row belongs to."""
    if period == EntitlementPeriod.MONTHLY:
        return f"{on_date.year:04d}-{on_date.month:02d}"
    if period == EntitlementPeriod.QUARTERLY:
        quarter = (on_date.month - 1) // 3 + 1
        return f"{on_date.year:04d}-Q{quarter}"
    if period == EntitlementPeriod.YEARLY:
        return f"{on_date.year:04d}"
    return "ONE_TIME"


async def get_applicable_rules(db: AsyncSession, beneficiary: Beneficiary) -> list[EntitlementRule]:
    """Rules that apply to this beneficiary: matching program, and matching category OR a
    category-agnostic rule (category_id IS NULL) for that program."""
    if beneficiary.program_id is None:
        return []
    query = select(EntitlementRule).where(
        EntitlementRule.program_id == beneficiary.program_id,
        EntitlementRule.is_active.is_(True),
        (EntitlementRule.category_id == beneficiary.category_id) | (EntitlementRule.category_id.is_(None)),
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_or_create_usage(
    db: AsyncSession, beneficiary_id: int, rule: EntitlementRule, on_date: date,
) -> BeneficiaryEntitlementUsage:
    """
    Fetches this beneficiary's usage row for the rule's current period, creating it (with
    allocated_quantity = rule.max_quantity) if this is the first time it's been touched.
    """
    period_key = get_period_key(rule.period, on_date)
    result = await db.execute(
        select(BeneficiaryEntitlementUsage).where(
            BeneficiaryEntitlementUsage.beneficiary_id == beneficiary_id,
            BeneficiaryEntitlementUsage.entitlement_rule_id == rule.id,
            BeneficiaryEntitlementUsage.period_key == period_key,
        )
    )
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = BeneficiaryEntitlementUsage(
            beneficiary_id=beneficiary_id,
            entitlement_rule_id=rule.id,
            period_key=period_key,
            allocated_quantity=rule.max_quantity,
            used_quantity=Decimal("0"),
        )
        db.add(usage)
        await db.flush()
    return usage


async def compute_summary(db: AsyncSession, beneficiary: Beneficiary, on_date: Optional[date] = None) -> list[dict]:
    """Returns allocated/used/remaining for every commodity this beneficiary is entitled to."""
    on_date = on_date or date.today()
    rules = await get_applicable_rules(db, beneficiary)
    items = []
    for rule in rules:
        usage = await get_or_create_usage(db, beneficiary.id, rule, on_date)
        commodity = await db.get(Commodity, rule.commodity_id)
        items.append({
            "entitlement_rule_id": rule.id,
            "commodity_id": rule.commodity_id,
            "commodity_name": commodity.name if commodity else "Unknown",
            "unit": commodity.unit if commodity else "",
            "period": rule.period,
            "period_key": usage.period_key,
            "allocated": usage.allocated_quantity,
            "used": usage.used_quantity,
            "remaining": usage.allocated_quantity - usage.used_quantity,
        })
    return items
