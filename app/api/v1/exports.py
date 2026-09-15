"""
CSV export (spec section 44). Kept as dedicated endpoints (rather than a `?format=csv` flag
bolted onto every list endpoint) so sensitive-field masking and permission checks are identical
to their JSON counterparts, just re-serialized as rows.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Beneficiary
from app.models.welfare import WelfareTransaction
from app.schemas.user import CurrentUser
from app.services.export_service import rows_to_csv_response

router = APIRouter(prefix="/exports", tags=["Data Export"])


@router.get("/beneficiaries.csv")
async def export_beneficiaries_csv(
    district_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
) -> StreamingResponse:
    can_view_sensitive = Perm.BENEFICIARIES_VIEW_SENSITIVE in current_user.permission_codes

    query = select(Beneficiary)
    if district_id:
        query = query.where(Beneficiary.district_id == district_id)
    beneficiaries = (await db.execute(query)).scalars().all()

    rows = []
    for b in beneficiaries:
        rows.append({
            "beneficiary_code": b.beneficiary_code,
            "full_name": b.full_name,
            "cnic": b.cnic if can_view_sensitive else "••••••••",
            "gender": b.gender or "",
            "family_size": b.family_size or "",
            "category_id": b.category_id or "",
            "program_id": b.program_id or "",
            "district_id": b.district_id,
            "status": b.status.value,
        })

    return rows_to_csv_response(rows, "beneficiaries.csv")


@router.get("/welfare-transactions.csv")
async def export_welfare_transactions_csv(
    mart_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.WELFARE_REPORTS_VIEW)),
) -> StreamingResponse:
    query = select(WelfareTransaction)
    if mart_id:
        query = query.where(WelfareTransaction.mart_id == mart_id)
    transactions = (await db.execute(query)).scalars().all()

    rows = [{
        "transaction_code": t.transaction_code,
        "beneficiary_id": t.beneficiary_id,
        "card_id": t.card_id,
        "program_id": t.program_id or "",
        "mart_id": t.mart_id or "",
        "total_value": str(t.total_value),
        "status": t.status.value,
        "created_at": t.created_at.isoformat(),
    } for t in transactions]

    return rows_to_csv_response(rows, "welfare_transactions.csv")
