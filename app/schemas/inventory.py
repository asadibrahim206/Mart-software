from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory import (
    PurchaseOrderStatus, StockMovementType, SupplierStatus, TransferStatus,
)


# ---------------------------------------------------------------------------
# Product categories
# ---------------------------------------------------------------------------

class ProductCategoryCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class ProductCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProductCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

class SupplierCreate(BaseModel):
    company_name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    payment_terms: Optional[str] = None
    bank_info: Optional[str] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    payment_terms: Optional[str] = None
    bank_info: Optional[str] = None
    status: Optional[SupplierStatus] = None
    notes: Optional[str] = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    payment_terms: Optional[str] = None
    bank_info: Optional[str] = None
    status: SupplierStatus
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    barcode: Optional[str] = None
    sku: str
    name: str
    category_id: Optional[int] = None
    commodity_id: Optional[int] = None
    brand: Optional[str] = None
    unit: str
    purchase_price: Decimal = Decimal("0")
    selling_price: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")
    max_stock: Optional[Decimal] = None
    reorder_level: Decimal = Decimal("0")
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    default_supplier_id: Optional[int] = None


class ProductUpdate(BaseModel):
    barcode: Optional[str] = None
    name: Optional[str] = None
    category_id: Optional[int] = None
    commodity_id: Optional[int] = None
    brand: Optional[str] = None
    purchase_price: Optional[Decimal] = None
    selling_price: Optional[Decimal] = None
    min_stock: Optional[Decimal] = None
    max_stock: Optional[Decimal] = None
    reorder_level: Optional[Decimal] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    default_supplier_id: Optional[int] = None
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    barcode: Optional[str] = None
    sku: str
    name: str
    category_id: Optional[int] = None
    commodity_id: Optional[int] = None
    brand: Optional[str] = None
    unit: str
    purchase_price: Decimal
    selling_price: Decimal
    min_stock: Decimal
    max_stock: Optional[Decimal] = None
    reorder_level: Decimal
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    default_supplier_id: Optional[int] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    warehouse_id: int
    quantity: Decimal


class StockAdjustmentRequest(BaseModel):
    product_id: int
    warehouse_id: int
    quantity_delta: Decimal = Field(..., description="Signed: positive to increase, negative to decrease")
    reason: str


class DamageExpiryRequest(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: Decimal = Field(..., gt=0)
    notes: Optional[str] = None


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    warehouse_id: int
    movement_type: StockMovementType
    quantity_delta: Decimal
    resulting_balance: Decimal
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    performed_by_user_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Warehouse transfers
# ---------------------------------------------------------------------------

class TransferItemIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(..., gt=0)


class TransferCreate(BaseModel):
    source_warehouse_id: int
    destination_warehouse_id: int
    items: list[TransferItemIn]
    notes: Optional[str] = None


class TransferItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    quantity: Decimal


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    transfer_code: str
    source_warehouse_id: int
    destination_warehouse_id: int
    status: TransferStatus
    requested_by_user_id: int
    approved_by_user_id: Optional[int] = None
    dispatched_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    notes: Optional[str] = None
    items: list[TransferItemOut] = []


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrderItemIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    items: list[PurchaseOrderItemIn]
    notes: Optional[str] = None


class PurchaseOrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    po_code: str
    supplier_id: int
    warehouse_id: int
    status: PurchaseOrderStatus
    total_amount: Decimal
    requested_by_user_id: int
    approved_by_user_id: Optional[int] = None
    received_at: Optional[datetime] = None
    notes: Optional[str] = None
    items: list[PurchaseOrderItemOut] = []
