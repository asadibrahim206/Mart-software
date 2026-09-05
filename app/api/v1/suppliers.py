"""
Suppliers + procurement workflow (spec section 19):
Purchase Request/Order (draft) -> Approval -> Goods Received -> Inventory Increased.
Receiving a PO is the point where stock actually increases — via stock_service.apply_movement,
so it's ledgered like every other stock change.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.inventory import (
    Product, PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, StockMovementType, Supplier,
)
from app.schemas.inventory import (
    PurchaseOrderCreate, PurchaseOrderOut, SupplierCreate, SupplierOut, SupplierUpdate,
)
from app.schemas.user import CurrentUser
from app.services import audit_service, stock_service
from app.services.application_service import make_code

router = APIRouter(tags=["Suppliers & Procurement"])

_PO_LOAD_OPTS = selectinload(PurchaseOrder.items)


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    result = await db.execute(select(Supplier).order_by(Supplier.company_name))
    return result.scalars().all()


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="supplier.create",
                                entity_type="Supplier", entity_id=supplier.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    supplier = await db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="supplier.update",
                                entity_type="Supplier", entity_id=supplier.id, new_value=changes)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    status_filter: PurchaseOrderStatus | None = None,
    supplier_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    query = select(PurchaseOrder).options(_PO_LOAD_OPTS).order_by(PurchaseOrder.id.desc())
    if status_filter:
        query = query.where(PurchaseOrder.status == status_filter)
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    result = await db.execute(query)
    return result.scalars().unique().all()


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
async def get_purchase_order(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id).options(_PO_LOAD_OPTS))).scalar_one_or_none()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return po


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    if await db.get(Supplier, payload.supplier_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier does not exist")
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Purchase order needs at least one item")

    total = sum((item.quantity * item.unit_price for item in payload.items), Decimal("0"))
    po = PurchaseOrder(
        po_code="PENDING", supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id,
        status=PurchaseOrderStatus.DRAFT, total_amount=total,
        requested_by_user_id=current_user.id, notes=payload.notes,
    )
    db.add(po)
    await db.flush()
    po.po_code = make_code("PO", po.id)

    for item in payload.items:
        if await db.get(Product, item.product_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Product {item.product_id} does not exist")
        db.add(PurchaseOrderItem(purchase_order_id=po.id, product_id=item.product_id, quantity=item.quantity, unit_price=item.unit_price))

    await audit_service.record(db, user_id=current_user.id, role_name=None, action="purchase_order.create",
                                entity_type="PurchaseOrder", entity_id=po.id, new_value={"supplier_id": payload.supplier_id, "total_amount": str(total)})
    await db.commit()
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po.id).options(_PO_LOAD_OPTS))
    return result.scalar_one()


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderOut)
async def approve_purchase_order(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    if po.status != PurchaseOrderStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot approve a PO in status '{po.status.value}'")

    po.status = PurchaseOrderStatus.APPROVED
    po.approved_by_user_id = current_user.id
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="purchase_order.approve",
                                entity_type="PurchaseOrder", entity_id=po.id)
    await db.commit()
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po.id).options(_PO_LOAD_OPTS))
    return result.scalar_one()


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
async def receive_purchase_order(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.PROCUREMENT_MANAGE)),
):
    """Marks goods received AND increases stock for every line item — atomically."""
    from datetime import datetime, timezone

    po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id).options(_PO_LOAD_OPTS))).scalar_one_or_none()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    if po.status != PurchaseOrderStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot receive a PO in status '{po.status.value}' — it must be APPROVED first")

    for item in po.items:
        await stock_service.apply_movement(
            db, product_id=item.product_id, warehouse_id=po.warehouse_id,
            movement_type=StockMovementType.IN, quantity_delta=item.quantity,
            performed_by_user_id=current_user.id, reference_type="purchase_order", reference_id=po.id,
            notes=f"Received against {po.po_code}",
        )

    po.status = PurchaseOrderStatus.RECEIVED
    po.received_at = datetime.now(timezone.utc)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="purchase_order.receive",
                                entity_type="PurchaseOrder", entity_id=po.id)
    await db.commit()
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po.id).options(_PO_LOAD_OPTS))
    return result.scalar_one()
