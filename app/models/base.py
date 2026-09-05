"""
Shared mixins for all ORM models.

TimestampMixin: created_at / updated_at on every table — needed for audit trails and reporting.
SoftDeleteMixin: nothing in this system is ever hard-deleted (beneficiaries, users, cards, products
all have history that must be preserved for audit purposes) — rows are deactivated, not dropped.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
