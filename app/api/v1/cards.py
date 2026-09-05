"""
Welfare card lifecycle (spec section 10).

A card can only be issued for an APPROVED application, and issuing it moves the application to
CARD_ISSUED — this coupling is enforced here rather than left to the caller. Replacing a lost
card blocks the old card and issues a brand new row (new card_number, new qr_token) linked via
replaced_from_card_id, so the full history survives (spec: "preserving the complete historical
record").
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Application, ApplicationStatus, CardStatus, WelfareCard
from app.schemas.beneficiary import CardIssueRequest, CardOut, CardStatusUpdate
from app.schemas.user import CurrentUser
from app.services import audit_service
from app.services.application_service import make_code

router = APIRouter(tags=["Welfare Cards"])


@router.get("/beneficiaries/{beneficiary_id}/cards", response_model=list[CardOut])
async def list_cards_for_beneficiary(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    result = await db.execute(select(WelfareCard).where(WelfareCard.beneficiary_id == beneficiary_id).order_by(WelfareCard.id.desc()))
    return result.scalars().all()


@router.post("/applications/{application_id}/issue-card", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def issue_card(
    application_id: int,
    payload: CardIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.CARDS_MANAGE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if application.status != ApplicationStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot issue a card for an application in status '{application.status.value}' — it must be APPROVED first",
        )

    card = WelfareCard(
        beneficiary_id=application.beneficiary_id,
        card_number="PENDING",
        qr_token=uuid.uuid4().hex,
        issue_date=date.today(),
        expiry_date=payload.expiry_date,
        status=CardStatus.ACTIVE,
        program_id=application.program_id,
        mart_id=payload.mart_id or application.mart_id,
    )
    db.add(card)
    await db.flush()
    card.card_number = make_code("WC", card.id)

    application.status = ApplicationStatus.CARD_ISSUED

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="card.issue",
        entity_type="WelfareCard", entity_id=card.id,
        new_value={"beneficiary_id": card.beneficiary_id, "application_id": application_id},
    )
    await db.commit()
    await db.refresh(card)
    return card


@router.post("/cards/{card_id}/status", response_model=CardOut)
async def update_card_status(
    card_id: int,
    payload: CardStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.CARDS_MANAGE)),
):
    """Block, suspend, mark lost, expire, or deactivate a card. Use /cards/{id}/replace for lost cards."""
    card = await db.get(WelfareCard, card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    if payload.status == CardStatus.REPLACED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use /cards/{id}/replace to replace a card, not this endpoint")

    previous_status = card.status.value
    card.status = payload.status

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="card.status_change",
        entity_type="WelfareCard", entity_id=card.id,
        previous_value={"status": previous_status}, new_value={"status": payload.status.value, "reason": payload.reason},
    )
    await db.commit()
    await db.refresh(card)
    return card


@router.post("/cards/{card_id}/replace", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def replace_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.CARDS_MANAGE)),
):
    old_card = await db.get(WelfareCard, card_id)
    if old_card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    if old_card.status == CardStatus.REPLACED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This card has already been replaced")

    old_card.status = CardStatus.REPLACED

    new_card = WelfareCard(
        beneficiary_id=old_card.beneficiary_id,
        card_number="PENDING",
        qr_token=uuid.uuid4().hex,
        issue_date=date.today(),
        expiry_date=old_card.expiry_date,
        status=CardStatus.ACTIVE,
        program_id=old_card.program_id,
        mart_id=old_card.mart_id,
        replaced_from_card_id=old_card.id,
    )
    db.add(new_card)
    await db.flush()
    new_card.card_number = make_code("WC", new_card.id)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="card.replace",
        entity_type="WelfareCard", entity_id=new_card.id,
        previous_value={"replaced_card_id": old_card.id, "replaced_card_number": old_card.card_number},
        new_value={"beneficiary_id": new_card.beneficiary_id},
    )
    await db.commit()
    await db.refresh(new_card)
    return new_card
