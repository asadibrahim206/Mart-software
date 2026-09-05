"""
Immutable audit trail. Rows are only ever inserted, never updated or deleted — enforced at the
service layer (AuditLog has no update/delete helper anywhere in the codebase, only `log()`).

previous_value / new_value store JSON snapshots so an auditor can see exactly what changed,
not just that a change happened.
"""
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    role_name: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), index=True)          # e.g. "user.create", "role.permissions.update"
    entity_type: Mapped[str] = mapped_column(String(100), index=True)     # e.g. "User", "Role"
    entity_id: Mapped[Optional[str]] = mapped_column(String(50))
    previous_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
