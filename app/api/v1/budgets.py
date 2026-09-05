from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.welfare import WelfareBudget
from app.schemas.user import CurrentUser
from app.schemas.welfare import BudgetCreate, BudgetOut, BudgetUpdate
from app.services import audit_service

router = APIRouter(prefix="/welfare-budgets", tags=["Welfare Budget"])


@router.get("", response_model=list[BudgetOut])
async def list_budgets(
    program_id: int | None = None,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    query = select(WelfareBudget).order_by(WelfareBudget.period_start.desc())
    if program_id:
        query = query.where(WelfareBudget.program_id == program_id)
    if not include_inactive:
        query = query.where(WelfareBudget.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{budget_id}", response_model=BudgetOut)
async def get_budget(
    budget_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
):
    budget = await db.get(WelfareBudget, budget_id)
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: BudgetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_BUDGET_MANAGE)),
):
    budget = WelfareBudget(**payload.model_dump())
    db.add(budget)
    await db.flush()
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="welfare_budget.create",
        entity_type="WelfareBudget", entity_id=budget.id, new_value=payload.model_dump(mode="json"),
    )
    await db.commit()
    await db.refresh(budget)
    return budget


@router.patch("/{budget_id}", response_model=BudgetOut)
async def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_BUDGET_MANAGE)),
):
    budget = await db.get(WelfareBudget, budget_id)
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="welfare_budget.update",
        entity_type="WelfareBudget", entity_id=budget.id, new_value=changes,
    )
    await db.commit()
    await db.refresh(budget)
    return budget
