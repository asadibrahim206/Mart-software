"""
System users (staff) — NOT beneficiaries. Beneficiaries are modeled separately in Phase 2
since they have a completely different lifecycle (applications, cards, entitlements) and must
never share a table or an auth mechanism with staff accounts.

A user's "home" organizational assignment (organization/region/district/mart/warehouse) is
informational/default-context for the UI. Actual access control is enforced by the roles the
user holds via UserRole, each of which may carry its own scope.
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.rbac import UserRole


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    region_id: Mapped[Optional[int]] = mapped_column(ForeignKey("regions.id"), index=True)
    district_id: Mapped[Optional[int]] = mapped_column(ForeignKey("districts.id"), index=True)
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"), index=True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(ForeignKey("warehouses.id"), index=True)

    username: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30))

    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    role_links: Mapped[List["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_locked(self) -> bool:
        from datetime import datetime, timezone
        return bool(self.locked_until and self.locked_until > datetime.now(timezone.utc))
