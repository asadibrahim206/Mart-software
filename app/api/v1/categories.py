from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import BeneficiaryCategory, WelfareProgram
from app.schemas.beneficiary import (
    CategoryCreate, CategoryOut, CategoryUpdate, ProgramCreate, ProgramOut, ProgramUpdate,
)
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Beneficiary Categories & Programs"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(BeneficiaryCategory).order_by(BeneficiaryCategory.name)
    if not include_inactive:
        query = query.where(BeneficiaryCategory.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.CATEGORIES_MANAGE)),
):
    existing = await db.execute(select(BeneficiaryCategory).where(BeneficiaryCategory.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category code already in use")

    category = BeneficiaryCategory(**payload.model_dump())
    db.add(category)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="category.create",
                                entity_type="BeneficiaryCategory", entity_id=category.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.CATEGORIES_MANAGE)),
):
    category = await db.get(BeneficiaryCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(category, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="category.update",
                                entity_type="BeneficiaryCategory", entity_id=category.id, new_value=changes)
    await db.commit()
    await db.refresh(category)
    return category


@router.get("/programs", response_model=list[ProgramOut])
async def list_programs(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(WelfareProgram).order_by(WelfareProgram.name)
    if not include_inactive:
        query = query.where(WelfareProgram.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/programs", response_model=ProgramOut, status_code=status.HTTP_201_CREATED)
async def create_program(
    payload: ProgramCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    existing = await db.execute(select(WelfareProgram).where(WelfareProgram.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Program code already in use")

    program = WelfareProgram(**payload.model_dump())
    db.add(program)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="program.create",
                                entity_type="WelfareProgram", entity_id=program.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(program)
    return program


@router.patch("/programs/{program_id}", response_model=ProgramOut)
async def update_program(
    program_id: int,
    payload: ProgramUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_CONFIGURE)),
):
    program = await db.get(WelfareProgram, program_id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(program, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="program.update",
                                entity_type="WelfareProgram", entity_id=program.id, new_value=changes)
    await db.commit()
    await db.refresh(program)
    return program
