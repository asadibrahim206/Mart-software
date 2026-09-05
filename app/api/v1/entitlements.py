from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Beneficiary
from app.schemas.user import CurrentUser
from app.schemas.welfare import EntitlementSummaryOut
from app.services import entitlement_service

router = APIRouter(tags=["Entitlements"])


@router.get("/beneficiaries/{beneficiary_id}/entitlements", response_model=EntitlementSummaryOut)
async def get_entitlement_summary(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    beneficiary = await db.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")

    items = await entitlement_service.compute_summary(db, beneficiary)
    await db.commit()  # persists any usage rows lazily created by compute_summary
    return EntitlementSummaryOut(beneficiary_id=beneficiary_id, items=items)
