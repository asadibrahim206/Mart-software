"""
The only sanctioned way to change a stock quantity. Every mutation (purchase receipt, transfer,
adjustment, damage, expiry, sale, welfare distribution) must go through apply_movement() — this
is what makes stock explainable (spec section 17: "must be able to explain exactly why current
stock has its current quantity") and guarantees StockMovement (history) and Stock (current
balance) never drift apart, since both are written in the same call.
"""
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Stock, StockMovement, StockMovementType


async def _get_or_create_stock_row(db: AsyncSession, product_id: int, warehouse_id: int) -> Stock:
    result = await db.execute(
        select(Stock).where(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id)
    )
    stock = result.scalar_one_or_none()
    if stock is None:
        stock = Stock(product_id=product_id, warehouse_id=warehouse_id, quantity=Decimal("0"))
        db.add(stock)
        await db.flush()
    return stock


async def apply_movement(
    db: AsyncSession,
    *,
    product_id: int,
    warehouse_id: int,
    movement_type: StockMovementType,
    quantity_delta: Decimal,
    performed_by_user_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    notes: Optional[str] = None,
    allow_negative: bool = False,
) -> StockMovement:
    """
    quantity_delta is signed: positive increases stock, negative decreases it. Raises if a
    decrease would take the balance below zero, unless allow_negative=True (e.g. for correcting
    a known-bad historical record — never used by normal distribution/sale paths).
    """
    stock = await _get_or_create_stock_row(db, product_id, warehouse_id)
    new_balance = stock.quantity + quantity_delta

    if new_balance < 0 and not allow_negative:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"INSUFFICIENT STOCK: movement would result in a negative balance "
                   f"(current: {stock.quantity}, requested change: {quantity_delta})",
        )

    stock.quantity = new_balance

    movement = StockMovement(
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=movement_type,
        quantity_delta=quantity_delta,
        resulting_balance=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        performed_by_user_id=performed_by_user_id,
        notes=notes,
    )
    db.add(movement)
    await db.flush()
    return movement


async def get_current_quantity(db: AsyncSession, product_id: int, warehouse_id: int) -> Decimal:
    result = await db.execute(
        select(Stock.quantity).where(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id)
    )
    quantity = result.scalar_one_or_none()
    return quantity if quantity is not None else Decimal("0")
