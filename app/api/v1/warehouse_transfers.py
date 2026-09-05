"""
Warehouse-to-warehouse stock transfers (spec section 18): request -> approve -> dispatch -> receive.
Stock leaves the source warehouse at dispatch time and lands in the destination at receive time —
both via stock_service so every movement is ledgered, and a transfer "in transit" between those
two events is correctly reflected as reduced source stock with no matching destination stock yet.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.inventory import (
    Product, StockMovementType, TransferStatus, WarehouseTransfer, WarehouseTransferItem,
)
from app.schemas.inventory import TransferCreate, TransferOut
from app.schemas.user import CurrentUser
from app.services import audit_service, stock_service
from app.services.application_service import make_code

router = APIRouter(prefix="/warehouse-transfers", tags=["Warehouse Transfers"])

_LOAD_OPTS = selectinload(WarehouseTransfer.items)


@router.get("", response_model=list[TransferOut])
async def list_transfers(
    status_filter: TransferStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    query = select(WarehouseTransfer).options(_LOAD_OPTS).order_by(WarehouseTransfer.id.desc())
    if status_filter:
        query = query.where(WarehouseTransfer.status == status_filter)
    result = await db.execute(query)
    return result.scalars().unique().all()


@router.post("", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    if payload.source_warehouse_id == payload.destination_warehouse_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source and destination warehouse must differ")
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transfer needs at least one item")

    transfer = WarehouseTransfer(
        transfer_code="PENDING", source_warehouse_id=payload.source_warehouse_id,
        destination_warehouse_id=payload.destination_warehouse_id, status=TransferStatus.PENDING,
        requested_by_user_id=current_user.id, notes=payload.notes,
    )
    db.add(transfer)
    await db.flush()
    transfer.transfer_code = make_code("WT", transfer.id)

    for item in payload.items:
        if await db.get(Product, item.product_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Product {item.product_id} does not exist")
        db.add(WarehouseTransferItem(transfer_id=transfer.id, product_id=item.product_id, quantity=item.quantity))

    await audit_service.record(db, user_id=current_user.id, role_name=None, action="warehouse_transfer.create",
                                entity_type="WarehouseTransfer", entity_id=transfer.id,
                                new_value={"source": payload.source_warehouse_id, "destination": payload.destination_warehouse_id})
    await db.commit()
    result = await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer.id).options(_LOAD_OPTS))
    return result.scalar_one()


@router.post("/{transfer_id}/approve", response_model=TransferOut)
async def approve_transfer(
    transfer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    transfer = await db.get(WarehouseTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot approve a transfer in status '{transfer.status.value}'")
    transfer.status = TransferStatus.APPROVED
    transfer.approved_by_user_id = current_user.id
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="warehouse_transfer.approve",
                                entity_type="WarehouseTransfer", entity_id=transfer.id)
    await db.commit()
    result = await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer.id).options(_LOAD_OPTS))
    return result.scalar_one()


@router.post("/{transfer_id}/dispatch", response_model=TransferOut)
async def dispatch_transfer(
    transfer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    """Deducts stock from the source warehouse — the goods are now considered in transit."""
    transfer = (await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer_id).options(_LOAD_OPTS))).scalar_one_or_none()
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    if transfer.status != TransferStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot dispatch a transfer in status '{transfer.status.value}' — it must be APPROVED first")

    for item in transfer.items:
        await stock_service.apply_movement(
            db, product_id=item.product_id, warehouse_id=transfer.source_warehouse_id,
            movement_type=StockMovementType.TRANSFER_OUT, quantity_delta=-item.quantity,
            performed_by_user_id=current_user.id, reference_type="warehouse_transfer", reference_id=transfer.id,
            notes=f"Dispatched on transfer {transfer.transfer_code}",
        )

    transfer.status = TransferStatus.DISPATCHED
    transfer.dispatched_at = datetime.now(timezone.utc)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="warehouse_transfer.dispatch",
                                entity_type="WarehouseTransfer", entity_id=transfer.id)
    await db.commit()
    result = await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer.id).options(_LOAD_OPTS))
    return result.scalar_one()


@router.post("/{transfer_id}/receive", response_model=TransferOut)
async def receive_transfer(
    transfer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    """Adds stock to the destination warehouse — completes the transfer."""
    transfer = (await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer_id).options(_LOAD_OPTS))).scalar_one_or_none()
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    if transfer.status != TransferStatus.DISPATCHED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot receive a transfer in status '{transfer.status.value}' — it must be DISPATCHED first")

    for item in transfer.items:
        await stock_service.apply_movement(
            db, product_id=item.product_id, warehouse_id=transfer.destination_warehouse_id,
            movement_type=StockMovementType.TRANSFER_IN, quantity_delta=item.quantity,
            performed_by_user_id=current_user.id, reference_type="warehouse_transfer", reference_id=transfer.id,
            notes=f"Received from transfer {transfer.transfer_code}",
        )

    transfer.status = TransferStatus.RECEIVED
    transfer.received_at = datetime.now(timezone.utc)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="warehouse_transfer.receive",
                                entity_type="WarehouseTransfer", entity_id=transfer.id)
    await db.commit()
    result = await db.execute(select(WarehouseTransfer).where(WarehouseTransfer.id == transfer.id).options(_LOAD_OPTS))
    return result.scalar_one()
