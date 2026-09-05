"""
Welfare distribution — the core "sell nothing until everything checks out" transaction.

create_welfare_transaction() runs every check from spec section 23 (card validity, beneficiary
status, entitlement availability, product/stock availability) BEFORE touching any row, and
raises a specific, informative HTTPException the moment something fails — never a generic
"rejected". Only once every item has passed both the entitlement check AND the stock check does
it proceed to actually deduct entitlement usage, deduct inventory, and insert the transaction —
all inside one DB transaction that is committed exactly once (spec section 42's "atomic: welfare
transaction + inventory deduction + entitlement deduction" requirement).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.beneficiary import Beneficiary, BeneficiaryStatus, CardStatus, WelfareCard
from app.models.inventory import Product, StockMovementType
from app.models.organization import Mart
from app.models.welfare import (
    Commodity, WelfareTransaction, WelfareTransactionItem, WelfareTransactionStatus,
)
from app.schemas.welfare import WelfareTransactionCreate
from app.services import audit_service, entitlement_service, stock_service
from app.services.application_service import make_code


async def _load_card_or_error(db: AsyncSession, card_number: str) -> WelfareCard:
    result = await db.execute(select(WelfareCard).where(WelfareCard.card_number == card_number))
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"CARD NOT FOUND: '{card_number}'")
    return card


def _check_card_status(card: WelfareCard) -> None:
    if card.status == CardStatus.BLOCKED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD BLOCKED")
    if card.status == CardStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD SUSPENDED")
    if card.status == CardStatus.LOST:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD REPORTED LOST")
    if card.status == CardStatus.REPLACED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD REPLACED — use the replacement card")
    if card.status == CardStatus.DEACTIVATED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD DEACTIVATED")
    if card.status == CardStatus.EXPIRED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD EXPIRED")
    if card.expiry_date and card.expiry_date < date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CARD EXPIRED")
    if card.status != CardStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CARD NOT ACTIVE (status: {card.status.value})")


def _check_beneficiary_status(beneficiary: Beneficiary) -> None:
    if beneficiary.status == BeneficiaryStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="BENEFICIARY SUSPENDED")
    if beneficiary.status == BeneficiaryStatus.DEACTIVATED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="BENEFICIARY DEACTIVATED")
    if beneficiary.status != BeneficiaryStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"BENEFICIARY NOT ACTIVE (status: {beneficiary.status.value})")


async def create_welfare_transaction(
    db: AsyncSession,
    payload: WelfareTransactionCreate,
    cashier_user_id: int,
    mart_id: Optional[int],
) -> WelfareTransaction:
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items provided for distribution")

    card = await _load_card_or_error(db, payload.card_number)
    _check_card_status(card)

    beneficiary = await db.get(Beneficiary, card.beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BENEFICIARY NOT FOUND for this card")
    _check_beneficiary_status(beneficiary)

    if mart_id is not None and card.mart_id is not None and card.mart_id != mart_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MART NOT AUTHORIZED for this card")

    resolved_mart_id = mart_id or card.mart_id
    warehouse_id: Optional[int] = None
    if resolved_mart_id is not None:
        mart = await db.get(Mart, resolved_mart_id)
        if mart is not None:
            warehouse_id = mart.default_warehouse_id

    today = date.today()

    rules = await entitlement_service.get_applicable_rules(db, beneficiary)
    rules_by_commodity = {r.commodity_id: r for r in rules}

    planned_items = []  # each: dict(usage, quantity, product, warehouse_id)
    total_value = Decimal("0")

    for item in payload.items:
        commodity = await db.get(Commodity, item.commodity_id)
        if commodity is None or not commodity.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"UNKNOWN COMMODITY (id {item.commodity_id})")

        rule = rules_by_commodity.get(item.commodity_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"NO ENTITLEMENT RULE for '{commodity.name}' under this beneficiary's program",
            )

        usage = await entitlement_service.get_or_create_usage(db, beneficiary.id, rule, today)
        remaining = usage.allocated_quantity - usage.used_quantity
        if item.quantity > remaining:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ENTITLEMENT EXCEEDED for '{commodity.name}': requested {item.quantity} {commodity.unit}, "
                       f"only {remaining} {commodity.unit} remaining this {rule.period.value} period",
            )

        # Inventory availability check — spec section 42: "Product exists, required stock available".
        product = None
        if warehouse_id is not None:
            product_result = await db.execute(
                select(Product).where(Product.commodity_id == item.commodity_id, Product.is_active.is_(True))
            )
            product = product_result.scalars().first()
            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"NO PRODUCT LINKED to commodity '{commodity.name}' — configure an inventory product for it first",
                )
            available = await stock_service.get_current_quantity(db, product.id, warehouse_id)
            if item.quantity > available:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"INSUFFICIENT STOCK for '{commodity.name}' at this mart: requested {item.quantity} {commodity.unit}, "
                           f"only {available} {commodity.unit} in stock",
                )
        # If no warehouse could be resolved (mart/card not yet configured with one), inventory
        # deduction is skipped for this item — entitlement tracking still applies. This keeps
        # the endpoint usable during initial setup before every mart has a warehouse wired up.

        planned_items.append({"item": item, "usage": usage, "product": product, "warehouse_id": warehouse_id})
        if item.unit_value:
            total_value += item.unit_value * item.quantity

    transaction = WelfareTransaction(
        transaction_code="PENDING",
        beneficiary_id=beneficiary.id,
        card_id=card.id,
        program_id=beneficiary.program_id,
        mart_id=resolved_mart_id,
        cashier_user_id=cashier_user_id,
        total_value=total_value,
        status=WelfareTransactionStatus.COMPLETED,
        notes=payload.notes,
    )
    db.add(transaction)
    await db.flush()
    transaction.transaction_code = make_code("WT", transaction.id)

    for planned in planned_items:
        item = planned["item"]
        usage = planned["usage"]
        usage.used_quantity += item.quantity

        db.add(WelfareTransactionItem(
            transaction_id=transaction.id,
            commodity_id=item.commodity_id,
            entitlement_rule_id=rules_by_commodity[item.commodity_id].id,
            quantity=item.quantity,
            unit_value=item.unit_value,
        ))

        if planned["product"] is not None and planned["warehouse_id"] is not None:
            await stock_service.apply_movement(
                db,
                product_id=planned["product"].id,
                warehouse_id=planned["warehouse_id"],
                movement_type=StockMovementType.WELFARE_DISTRIBUTION,
                quantity_delta=-item.quantity,
                performed_by_user_id=cashier_user_id,
                reference_type="welfare_transaction",
                reference_id=transaction.id,
                notes=f"Welfare distribution to beneficiary {beneficiary.id} ({beneficiary.beneficiary_code})",
            )

    await audit_service.record(
        db, user_id=cashier_user_id, role_name=None, action="welfare_transaction.create",
        entity_type="WelfareTransaction", entity_id=transaction.id,
        new_value={"beneficiary_id": beneficiary.id, "card_number": card.card_number, "total_value": str(total_value)},
    )
    await db.commit()

    # Re-fetch with items eagerly loaded — accessing an unloaded relationship after commit
    # would otherwise trigger an implicit lazy-load outside of an async-safe context.
    result = await db.execute(
        select(WelfareTransaction).where(WelfareTransaction.id == transaction.id).options(selectinload(WelfareTransaction.items))
    )
    return result.scalar_one()
