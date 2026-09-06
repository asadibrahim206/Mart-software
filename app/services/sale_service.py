"""
Normal commercial sale — the counterpart to welfare_service.create_welfare_transaction, but for
paying customers. Same discipline: validate everything (open shift, stock availability) before
mutating anything, then deduct stock and record the sale atomically in one commit.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inventory import Product, StockMovementType
from app.models.organization import Mart
from app.models.pos import (
    CashierShift, Payment, PaymentMethod, PaymentStatus, Refund, Sale, SaleItem, SaleStatus,
    ShiftStatus,
)
from app.models.welfare import WelfareTransaction
from app.schemas.pos import SaleCreate
from app.services import audit_service, stock_service
from app.services.application_service import make_code


async def _get_open_shift_or_error(db: AsyncSession, cashier_user_id: int, mart_id: int) -> CashierShift:
    result = await db.execute(
        select(CashierShift).where(
            CashierShift.user_id == cashier_user_id,
            CashierShift.mart_id == mart_id,
            CashierShift.status == ShiftStatus.OPEN,
        )
    )
    shift = result.scalar_one_or_none()
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NO OPEN CASHIER SHIFT — open a shift at this mart before recording sales",
        )
    return shift


async def create_sale(db: AsyncSession, payload: SaleCreate, cashier_user_id: int) -> tuple[Sale, Optional[Decimal]]:
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items provided for this sale")

    shift = await _get_open_shift_or_error(db, cashier_user_id, payload.mart_id)

    mart = await db.get(Mart, payload.mart_id)
    if mart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mart not found")
    warehouse_id = mart.default_warehouse_id

    planned_items = []
    subtotal = Decimal("0")
    for item in payload.items:
        product = await db.get(Product, item.product_id)
        if product is None or not product.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Product {item.product_id} not found or inactive")

        unit_price = item.unit_price if item.unit_price is not None else product.selling_price
        line_total = (unit_price * item.quantity) - item.discount_amount

        if warehouse_id is not None:
            available = await stock_service.get_current_quantity(db, product.id, warehouse_id)
            if item.quantity > available:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"INSUFFICIENT STOCK for '{product.name}': requested {item.quantity} {product.unit}, "
                           f"only {available} {product.unit} in stock",
                )

        planned_items.append({"item": item, "product": product, "unit_price": unit_price, "line_total": line_total})
        subtotal += unit_price * item.quantity

    total_amount = subtotal - payload.discount_amount
    if total_amount < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Discount exceeds subtotal")

    if payload.payment_method == PaymentMethod.CASH and payload.cash_tendered is not None and payload.cash_tendered < total_amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cash tendered is less than the total amount due")

    sale = Sale(
        sale_code="PENDING", mart_id=payload.mart_id, cashier_shift_id=shift.id, cashier_user_id=cashier_user_id,
        subtotal=subtotal, discount_amount=payload.discount_amount, total_amount=total_amount,
        status=SaleStatus.COMPLETED, notes=payload.notes,
    )
    db.add(sale)
    await db.flush()
    sale.sale_code = make_code("SALE", sale.id)

    for planned in planned_items:
        item = planned["item"]
        db.add(SaleItem(
            sale_id=sale.id, product_id=item.product_id, quantity=item.quantity,
            unit_price=planned["unit_price"], discount_amount=item.discount_amount, line_total=planned["line_total"],
        ))
        if warehouse_id is not None:
            await stock_service.apply_movement(
                db, product_id=item.product_id, warehouse_id=warehouse_id,
                movement_type=StockMovementType.NORMAL_SALE, quantity_delta=-item.quantity,
                performed_by_user_id=cashier_user_id, reference_type="sale", reference_id=sale.id,
            )

    db.add(Payment(sale_id=sale.id, method=payload.payment_method, amount=total_amount, status=PaymentStatus.COMPLETED))

    await audit_service.record(
        db, user_id=cashier_user_id, role_name=None, action="sale.create",
        entity_type="Sale", entity_id=sale.id, new_value={"total_amount": str(total_amount), "mart_id": payload.mart_id},
    )
    await db.commit()

    change_due = None
    if payload.payment_method == PaymentMethod.CASH and payload.cash_tendered is not None:
        change_due = payload.cash_tendered - total_amount

    result = await db.execute(
        select(Sale).where(Sale.id == sale.id).options(selectinload(Sale.items), selectinload(Sale.payments))
    )
    return result.scalar_one(), change_due


async def refund_sale(db: AsyncSession, sale_id: int, reason: str, refunded_by_user_id: int) -> Sale:
    """Full-sale refund only (no partial/line-level refunds in this phase). Restores stock."""
    sale = (await db.execute(
        select(Sale).where(Sale.id == sale_id).options(selectinload(Sale.items), selectinload(Sale.payments))
    )).scalar_one_or_none()
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if sale.status != SaleStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot refund a sale in status '{sale.status.value}'")

    mart = await db.get(Mart, sale.mart_id)
    warehouse_id = mart.default_warehouse_id if mart else None

    for item in sale.items:
        if warehouse_id is not None:
            await stock_service.apply_movement(
                db, product_id=item.product_id, warehouse_id=warehouse_id,
                movement_type=StockMovementType.RETURN, quantity_delta=item.quantity,
                performed_by_user_id=refunded_by_user_id, reference_type="sale_refund", reference_id=sale.id,
            )

    db.add(Refund(sale_id=sale.id, refunded_by_user_id=refunded_by_user_id, amount=sale.total_amount, reason=reason))
    sale.status = SaleStatus.REFUNDED

    await audit_service.record(
        db, user_id=refunded_by_user_id, role_name=None, action="sale.refund",
        entity_type="Sale", entity_id=sale.id, new_value={"amount": str(sale.total_amount), "reason": reason},
    )
    await db.commit()

    result = await db.execute(
        select(Sale).where(Sale.id == sale.id).options(selectinload(Sale.items), selectinload(Sale.payments))
    )
    return result.scalar_one()


async def close_shift(
    db: AsyncSession, shift: CashierShift, actual_cash: Decimal, notes: Optional[str], closed_by_user_id: int,
) -> CashierShift:
    """Sums this shift's sales by payment method + this cashier's welfare distributions during
    the shift window, freezes those totals onto the shift row, and computes the cash difference."""
    if shift.status != ShiftStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This shift is already closed")

    totals_by_method = dict((await db.execute(
        select(Payment.method, func.coalesce(func.sum(Payment.amount), 0))
        .join(Sale, Sale.id == Payment.sale_id)
        .where(Sale.cashier_shift_id == shift.id, Payment.status == PaymentStatus.COMPLETED)
        .group_by(Payment.method)
    )).all())

    refunds_total = (await db.execute(
        select(func.coalesce(func.sum(Sale.total_amount), 0))
        .where(Sale.cashier_shift_id == shift.id, Sale.status == SaleStatus.REFUNDED)
    )).scalar_one()

    now = datetime.now(timezone.utc)
    welfare_total = (await db.execute(
        select(func.coalesce(func.sum(WelfareTransaction.total_value), 0))
        .where(
            WelfareTransaction.cashier_user_id == shift.user_id,
            WelfareTransaction.mart_id == shift.mart_id,
            WelfareTransaction.created_at >= shift.opened_at,
            WelfareTransaction.created_at <= now,
        )
    )).scalar_one()

    shift.cash_sales_total = totals_by_method.get(PaymentMethod.CASH, Decimal("0"))
    shift.card_sales_total = totals_by_method.get(PaymentMethod.CARD, Decimal("0"))
    shift.digital_sales_total = totals_by_method.get(PaymentMethod.DIGITAL, Decimal("0"))
    shift.refunds_total = refunds_total
    shift.welfare_distribution_value = welfare_total

    shift.expected_cash = shift.opening_cash + shift.cash_sales_total - shift.refunds_total
    shift.actual_cash = actual_cash
    shift.cash_difference = actual_cash - shift.expected_cash
    shift.status = ShiftStatus.CLOSED
    shift.closed_at = now
    if notes:
        shift.notes = notes

    await audit_service.record(
        db, user_id=closed_by_user_id, role_name=None, action="cashier_shift.close",
        entity_type="CashierShift", entity_id=shift.id,
        new_value={"actual_cash": str(actual_cash), "cash_difference": str(shift.cash_difference)},
    )
    await db.commit()
    await db.refresh(shift)
    return shift
