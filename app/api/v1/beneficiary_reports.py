from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import (
    Application, ApplicationStatus, Beneficiary, BeneficiaryCategory, BeneficiaryStatus,
)
from app.models.organization import District
from app.schemas.analytics import (
    ApplicationFunnelOut, BeneficiaryReportOut, CategoryDistributionItem,
    DistrictDistributionItem, FamilySizeBucketItem,
)
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/reports", tags=["Beneficiary Reports"])


@router.get("/beneficiaries", response_model=BeneficiaryReportOut)
async def beneficiary_report(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    total = (await db.execute(select(func.count()).select_from(Beneficiary))).scalar_one()
    active = (await db.execute(select(func.count()).select_from(Beneficiary).where(Beneficiary.status == BeneficiaryStatus.ACTIVE))).scalar_one()
    suspended = (await db.execute(select(func.count()).select_from(Beneficiary).where(Beneficiary.status == BeneficiaryStatus.SUSPENDED))).scalar_one()

    category_rows = (await db.execute(
        select(BeneficiaryCategory.id, BeneficiaryCategory.name, func.count(Beneficiary.id))
        .outerjoin(Beneficiary, Beneficiary.category_id == BeneficiaryCategory.id)
        .group_by(BeneficiaryCategory.id, BeneficiaryCategory.name)
    )).all()
    by_category = [CategoryDistributionItem(category_id=r[0], category_name=r[1], count=r[2]) for r in category_rows]

    district_rows = (await db.execute(
        select(District.id, District.name, func.count(Beneficiary.id))
        .join(Beneficiary, Beneficiary.district_id == District.id)
        .group_by(District.id, District.name)
    )).all()
    by_district = [DistrictDistributionItem(district_id=r[0], district_name=r[1], count=r[2]) for r in district_rows]

    bucket_case = case(
        (Beneficiary.family_size.is_(None), "Unknown"),
        (Beneficiary.family_size <= 2, "1-2"),
        (Beneficiary.family_size <= 4, "3-4"),
        (Beneficiary.family_size <= 6, "5-6"),
        else_="7+",
    )
    bucket_rows = (await db.execute(
        select(bucket_case.label("bucket"), func.count()).group_by(bucket_case)
    )).all()
    by_family_size = [FamilySizeBucketItem(bucket=r[0], count=r[1]) for r in bucket_rows]

    status_counts = dict((await db.execute(
        select(Application.status, func.count()).group_by(Application.status)
    )).all())
    funnel = ApplicationFunnelOut(**{
        status.value: status_counts.get(status, 0) for status in ApplicationStatus
    })

    return BeneficiaryReportOut(
        total_beneficiaries=total, active_beneficiaries=active, suspended_beneficiaries=suspended,
        by_category=by_category, by_district=by_district, by_family_size=by_family_size,
        application_funnel=funnel,
    )
