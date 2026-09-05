"""
Inventory & procurement (Phase 4).

Stock ledger design (spec section 17 — "must be able to explain exactly why current stock has
its current quantity"): every quantity change is an immutable StockMovement row (IN/OUT/
ADJUSTMENT/TRANSFER/RETURN/DAMAGE/EXPIRY/NORMAL_SALE/WELFARE_DISTRIBUTION), signed
(+ for increases, - for decreases). Stock itself is a materialized current-balance cache per
(product, warehouse) — always derivable by summing its StockMovement rows, kept in sync by
stock_service.apply_movement() being the ONLY code path allowed to write to either table. This
is what fulfills "never modify stock silently" (section 16): there is no other way to change a
quantity.

Product.commodity_id links a purchasable SKU to a Phase 3 Commodity (e.g. "Flour 10kg Bag —
Brand X" -> commodity "Flour"), which is what finally lets welfare_service deduct real stock
when a welfare distribution happens — the hook promised in that file's comment from Phase 3.
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


class SupplierStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class StockMovementType(str, enum.Enum):
    IN = "in"
    OUT = "out"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RETURN = "return"
    DAMAGE = "damage"
    EXPIRY = "expiry"
    NORMAL_SALE = "normal_sale"
    WELFARE_DISTRIBUTION = "welfare_distribution"


class TransferStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ORDERED = "ordered"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ProductCategory(Base, TimestampMixin):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    tax_number: Mapped[Optional[str]] = mapped_column(String(50))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(200))
    bank_info: Mapped[Optional[str]] = mapped_column(String(300))
    status: Mapped[SupplierStatus] = mapped_column(Enum(SupplierStatus), default=SupplierStatus.ACTIVE, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_categories.id"), index=True)
    commodity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("commodities.id"), index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)

    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    max_stock: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    batch_number: Mapped[Optional[str]] = mapped_column(String(50))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    default_supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"))

    is_active: Mapped[bool] = mapped_column(default=True)


class Stock(Base, TimestampMixin):
    """Materialized current balance per (product, warehouse). Written ONLY by stock_service."""
    __tablename__ = "stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", name="uq_stock_product_warehouse"),)


class StockMovement(Base, TimestampMixin):
    """Immutable ledger row. quantity_delta is signed: positive = stock increased, negative = decreased."""
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    movement_type: Mapped[StockMovementType] = mapped_column(Enum(StockMovementType), nullable=False, index=True)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    resulting_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    reference_type: Mapped[Optional[str]] = mapped_column(String(50))   # "purchase_order", "welfare_transaction", ...
    reference_id: Mapped[Optional[int]] = mapped_column()
    performed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[Optional[str]] = mapped_column(String(300))


class WarehouseTransfer(Base, TimestampMixin):
    __tablename__ = "warehouse_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    source_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    destination_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    status: Mapped[TransferStatus] = mapped_column(Enum(TransferStatus), default=TransferStatus.PENDING, nullable=False)

    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list["WarehouseTransferItem"]] = relationship(back_populates="transfer", cascade="all, delete-orphan")


class WarehouseTransferItem(Base, TimestampMixin):
    __tablename__ = "warehouse_transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("warehouse_transfers.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    transfer: Mapped["WarehouseTransfer"] = relationship(back_populates="items")


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(Enum(PurchaseOrderStatus), default=PurchaseOrderStatus.DRAFT, nullable=False)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list["PurchaseOrderItem"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base, TimestampMixin):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
