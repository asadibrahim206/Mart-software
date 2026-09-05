"""
Role-based access control.

Permissions are DATA, not code — an admin can create a new role and attach any combination of
permissions to it through the /roles and /permissions APIs, with zero deploys. `Permission.code`
is the only thing route handlers check (via the `require_permission()` dependency), so adding a
new permission is a migration + seed row, never a code change to existing endpoints.

A user can hold multiple roles (e.g. a District Manager who is also acting Finance Manager for
their district), and each role can be scoped to a level of the org hierarchy — see
UserRole.scope_type / scope_id.
"""
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)  # e.g. "beneficiaries.approve"
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # e.g. "beneficiaries"
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    role_links: Mapped[List["RolePermission"]] = relationship(back_populates="permission")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # system roles can't be deleted (e.g. Super Admin)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    permission_links: Mapped[List["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    user_links: Mapped[List["UserRole"]] = relationship(back_populates="role")


class RolePermission(Base):
    """Join table: which permissions a role grants. Editable via the admin Roles screen."""
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)

    role: Mapped["Role"] = relationship(back_populates="permission_links")
    permission: Mapped["Permission"] = relationship(back_populates="role_links")


class UserRole(Base, TimestampMixin):
    """
    Join table: which role(s) a user holds, optionally scoped to one node of the org hierarchy.

    scope_type / scope_id let the same role mean "district manager for District X" vs
    "district manager for District Y" without creating a role per district. scope_type is one
    of: organization, region, district, mart, warehouse — enforced at the service layer.
    scope_type=None (with scope_id=None) means the role applies organization-wide (e.g. Super Admin).
    """
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    scope_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    scope_id: Mapped[Optional[int]] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="role_links")
    role: Mapped["Role"] = relationship(back_populates="user_links")

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope_type", "scope_id", name="uq_user_role_scope"),
    )
