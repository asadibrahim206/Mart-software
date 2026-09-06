"""
Point of Sale (Phase 5) — the "Normal Sale" side of the mart. Welfare distribution (the
"Welfare Sale" side, per spec section 14) is already fully implemented in Phase 3/4's
WelfareTransaction — deliberately a SEPARATE table from Sale, per spec section 15's hard
requirement to never mix normal commercial sales and welfare distributions in the database or
in reporting.

A cashier must have an OPEN CashierShift before any sale can be recorded — enforced in
sale_service, not just at the UI level. Every Sale is linked to the shift it happened in, so
closing a shift can reconcile exactly what that cashier rang up.
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ShiftStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class SaleStatus(str, enum.Enum):
    COMPLETED = "completed"
    REFUNDED = "refunded"
    VOIDED = "voided"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CARD = "card"
    DIGITAL = "digital"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class CashierShift(Base, TimestampMixin):
    __tablename__ = "cashier_shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    mart_id: Mapped[int] = mapped_column(ForeignKey("marts.id"), nullable=False, index=True)
    status: Mapped[ShiftStatus] = mapped_column(Enum(ShiftStatus), default=ShiftStatus.OPEN, nullable=False, index=True)

    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Snapshot totals — computed and frozen at closing time, not recomputed later, so a shift's
    # reconciliation record stays stable even if later corrections touch the underlying sales.
    cash_sales_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    card_sales_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    digital_sales_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    welfare_distribution_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    refunds_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    expected_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    actual_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    cash_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))

    notes: Mapped[Optional[str]] = mapped_column(Text)


class Sale(Base, TimestampMixin):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    mart_id: Mapped[int] = mapped_column(ForeignKey("marts.id"), nullable=False, index=True)
    cashier_shift_id: Mapped[int] = mapped_column(ForeignKey("cashier_shifts.id"), nullable=False, index=True)
    cashier_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[SaleStatus] = mapped_column(Enum(SaleStatus), default=SaleStatus.COMPLETED, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base, TimestampMixin):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    sale: Mapped["Sale"] = relationship(back_populates="items")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.COMPLETED, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100))   # external gateway/txn reference, never a raw card number

    sale: Mapped["Sale"] = relationship(back_populates="payments")


class Refund(Base, TimestampMixin):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    refunded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
