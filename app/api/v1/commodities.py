from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.welfare import Commodity, EntitlementRule
from app.schemas.user import CurrentUser
from app.schemas.welfare import (
    CommodityCreate, CommodityOut, CommodityUpdate, EntitlementRuleCreate, EntitlementRuleOut,
    EntitlementRuleUpdate,
)
from app.services import audit_service

router = APIRouter(tags=["Commodities & Entitlement Rules"])


@router.get("/commodities", response_model=list[CommodityOut])
async def list_commodities(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(Commodity).order_by(Commodity.name)
    if not include_inactive:
        query = query.where(Commodity.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/commodities", response_model=CommodityOut, status_code=status.HTTP_201_CREATED)
async def create_commodity(
    payload: CommodityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    existing = await db.execute(select(Commodity).where(Commodity.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Commodity code already in use")

    commodity = Commodity(**payload.model_dump())
    db.add(commodity)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="commodity.create",
                                entity_type="Commodity", entity_id=commodity.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(commodity)
    return commodity


@router.patch("/commodities/{commodity_id}", response_model=CommodityOut)
async def update_commodity(
    commodity_id: int,
    payload: CommodityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    commodity = await db.get(Commodity, commodity_id)
    if commodity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commodity not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(commodity, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="commodity.update",
                                entity_type="Commodity", entity_id=commodity.id, new_value=changes)
    await db.commit()
    await db.refresh(commodity)
    return commodity


@router.get("/entitlement-rules", response_model=list[EntitlementRuleOut])
async def list_entitlement_rules(
    program_id: int | None = None,
    category_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(EntitlementRule).where(EntitlementRule.is_active.is_(True))
    if program_id:
        query = query.where(EntitlementRule.program_id == program_id)
    if category_id:
        query = query.where(EntitlementRule.category_id == category_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/entitlement-rules", response_model=EntitlementRuleOut, status_code=status.HTTP_201_CREATED)
async def create_entitlement_rule(
    payload: EntitlementRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    existing = await db.execute(
        select(EntitlementRule).where(
            EntitlementRule.program_id == payload.program_id,
            EntitlementRule.category_id == payload.category_id,
            EntitlementRule.commodity_id == payload.commodity_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An entitlement rule already exists for this program/category/commodity combination — update it instead",
        )

    rule = EntitlementRule(**payload.model_dump())
    db.add(rule)
    await db.flush()
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="entitlement_rule.create",
        entity_type="EntitlementRule", entity_id=rule.id, new_value=payload.model_dump(mode="json"),
    )
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/entitlement-rules/{rule_id}", response_model=EntitlementRuleOut)
async def update_entitlement_rule(
    rule_id: int,
    payload: EntitlementRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    rule = await db.get(EntitlementRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entitlement rule not found")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="entitlement_rule.update",
        entity_type="EntitlementRule", entity_id=rule.id, new_value=changes,
    )
    await db.commit()
    await db.refresh(rule)
    return rule
