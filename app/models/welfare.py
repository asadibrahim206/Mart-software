"""
Welfare entitlement engine (Phase 3).

Key modeling decision: entitlement rules reference a lightweight Commodity catalog ("Flour",
"Rice", "Sugar" — conceptual goods), NOT a specific purchasable SKU. Real inventory Products
(Phase 4) will each link to a Commodity (e.g. "Flour 10kg Bag — Brand X" -> commodity "Flour"),
so a beneficiary's entitlement is tracked in commodity units (KG, L, PCS) regardless of which
specific product/brand/package-size a mart happens to distribute it as. This avoids entitlement
rules needing to know about inventory SKUs that don't exist until Phase 4, and matches how
welfare orgs actually think about allocations ("20kg of flour/month", not "bag #4471/month").

WelfareTransaction records a distribution event. It deducts entitlement usage atomically in
this phase; the inventory stock deduction hook (spec section 42's "atomic: welfare transaction +
inventory deduction + entitlement deduction + financial record") gets wired in once Phase 4
inventory exists — the transaction/item structure here is already shaped for that addition.
"""
import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EntitlementPeriod(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ONE_TIME = "one_time"   # a single lifetime allocation, never resets


class WelfareTransactionStatus(str, enum.Enum):
    COMPLETED = "completed"
    VOIDED = "voided"


class Commodity(Base, TimestampMixin):
    __tablename__ = "commodities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)   # KG, L, PCS, ...
    description: Mapped[Optional[str]] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)


class EntitlementRule(Base, TimestampMixin):
    """
    A configurable allocation: "under Program X, category Y gets N units of commodity Z per
    period P". category_id=None means the rule applies to every category under the program.
    Admins create/edit these through the API — never hardcoded (spec section 11).
    """
    __tablename__ = "entitlement_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("welfare_programs.id"), nullable=False, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beneficiary_categories.id"), index=True)
    commodity_id: Mapped[int] = mapped_column(ForeignKey("commodities.id"), nullable=False, index=True)

    period: Mapped[EntitlementPeriod] = mapped_column(Enum(EntitlementPeriod), nullable=False)
    max_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    monetary_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        UniqueConstraint("program_id", "category_id", "commodity_id", name="uq_entitlement_rule_scope"),
    )


class BeneficiaryEntitlementUsage(Base, TimestampMixin):
    """
    Allocated/used ledger for one beneficiary, one rule, one period instance (e.g. "2026-08" for
    a monthly rule). Created lazily the first time it's needed (see entitlement_service). Never
    modified except by welfare_service when a distribution is confirmed or voided.
    """
    __tablename__ = "beneficiary_entitlement_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    beneficiary_id: Mapped[int] = mapped_column(ForeignKey("beneficiaries.id"), nullable=False, index=True)
    entitlement_rule_id: Mapped[int] = mapped_column(ForeignKey("entitlement_rules.id"), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)   # "2026-08", "2026-Q3", "2026", or "ONE_TIME"

    allocated_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    used_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("beneficiary_id", "entitlement_rule_id", "period_key", name="uq_beneficiary_rule_period"),
    )


class WelfareBudget(Base, TimestampMixin):
    """
    Budget scoped to a program (mandatory) and optionally narrowed to a district/mart/category —
    those narrower fields are stored for filtering/reporting now; matching a transaction against
    the single most-specific applicable budget is a Phase 6+ finance refinement. For now, budget
    consumption is tracked at the program level.
    """
    __tablename__ = "welfare_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    program_id: Mapped[int] = mapped_column(ForeignKey("welfare_programs.id"), nullable=False, index=True)
    district_id: Mapped[Optional[int]] = mapped_column(ForeignKey("districts.id"))
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beneficiary_categories.id"))

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[Optional[date]] = mapped_column(Date)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    used_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    warning_threshold_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("80.00"))
    is_active: Mapped[bool] = mapped_column(default=True)


class WelfareTransaction(Base, TimestampMixin):
    __tablename__ = "welfare_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    beneficiary_id: Mapped[int] = mapped_column(ForeignKey("beneficiaries.id"), nullable=False, index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("welfare_cards.id"), nullable=False, index=True)
    program_id: Mapped[Optional[int]] = mapped_column(ForeignKey("welfare_programs.id"))
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"), index=True)
    cashier_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    total_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    status: Mapped[WelfareTransactionStatus] = mapped_column(Enum(WelfareTransactionStatus), default=WelfareTransactionStatus.COMPLETED, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list["WelfareTransactionItem"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")


class WelfareTransactionItem(Base, TimestampMixin):
    __tablename__ = "welfare_transaction_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("welfare_transactions.id"), nullable=False, index=True)
    commodity_id: Mapped[int] = mapped_column(ForeignKey("commodities.id"), nullable=False)
    entitlement_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entitlement_rules.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))   # monetary value of this line, if priced

    transaction: Mapped["WelfareTransaction"] = relationship(back_populates="items")
