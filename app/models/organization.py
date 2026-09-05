"""
Organizational hierarchy:

    Organization (head office)
        -> Region / Province
            -> District
                -> Warehouse   (stock source)
                -> Mart        (point of sale / distribution point, belongs to a district
                                 and optionally has a default supplying warehouse)

Every transaction elsewhere in the system is traceable up this chain, which is why every
downstream table (users, beneficiaries, sales, welfare_transactions, stock movements ...)
carries an explicit mart_id / warehouse_id / district_id rather than relying on joins alone.
"""
from typing import List, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(String(150))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))
    address: Mapped[Optional[str]] = mapped_column(String(500))

    regions: Mapped[List["Region"]] = relationship(back_populates="organization")


class Region(Base, TimestampMixin, SoftDeleteMixin):
    """Province / Region — first administrative subdivision under an organization."""
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="regions")
    districts: Mapped[List["District"]] = relationship(back_populates="region")

    __table_args__ = ({"mysql_charset": "utf8mb4"},)


class District(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)

    region: Mapped["Region"] = relationship(back_populates="districts")
    warehouses: Mapped[List["Warehouse"]] = relationship(back_populates="district")
    marts: Mapped[List["Mart"]] = relationship(back_populates="district")


class Warehouse(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    is_central: Mapped[bool] = mapped_column(default=False)  # marks the top-level/central warehouse

    district: Mapped["District"] = relationship(back_populates="warehouses")
    marts: Mapped[List["Mart"]] = relationship(back_populates="default_warehouse")


class Mart(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "marts"

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), nullable=False, index=True)
    default_warehouse_id: Mapped[Optional[int]] = mapped_column(ForeignKey("warehouses.id"), index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    accepts_welfare: Mapped[bool] = mapped_column(default=True)  # some marts may be commercial-only

    district: Mapped["District"] = relationship(back_populates="marts")
    default_warehouse: Mapped[Optional["Warehouse"]] = relationship(back_populates="marts")
