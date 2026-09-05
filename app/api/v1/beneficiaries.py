from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Beneficiary, BeneficiaryStatus
from app.models.organization import District
from app.schemas.beneficiary import MASK, BeneficiaryCreate, BeneficiaryOut, BeneficiaryUpdate
from app.schemas.common import Page, PageMeta
from app.schemas.user import CurrentUser
from app.services import audit_service
from app.services.application_service import make_code

router = APIRouter(prefix="/beneficiaries", tags=["Beneficiaries"])


def _to_beneficiary_out(beneficiary: Beneficiary, current_user: CurrentUser) -> BeneficiaryOut:
    """
    The single place sensitive-field masking happens (spec section 5: "Do not expose sensitive
    information to users who do not have permission"). Data is always stored unmasked; only the
    outbound representation changes based on the caller's permissions.
    """
    can_view_sensitive = Perm.BENEFICIARIES_VIEW_SENSITIVE in current_user.permission_codes
    return BeneficiaryOut(
        id=beneficiary.id,
        beneficiary_code=beneficiary.beneficiary_code,
        full_name=beneficiary.full_name,
        father_husband_name=beneficiary.father_husband_name,
        cnic=beneficiary.cnic if can_view_sensitive else (MASK if beneficiary.cnic else None),
        mobile_number=beneficiary.mobile_number if can_view_sensitive else (MASK if beneficiary.mobile_number else None),
        date_of_birth=beneficiary.date_of_birth,
        gender=beneficiary.gender,
        address=beneficiary.address if can_view_sensitive else None,
        province=beneficiary.province,
        tehsil=beneficiary.tehsil,
        union_council=beneficiary.union_council,
        village_area=beneficiary.village_area,
        family_size=beneficiary.family_size,
        number_of_children=beneficiary.number_of_children,
        employment_status=beneficiary.employment_status,
        household_income=beneficiary.household_income if can_view_sensitive else None,
        income_source=beneficiary.income_source,
        category_id=beneficiary.category_id,
        program_id=beneficiary.program_id,
        district_id=beneficiary.district_id,
        mart_id=beneficiary.mart_id,
        status=beneficiary.status,
        notes=beneficiary.notes,
    )


@router.get("", response_model=Page[BeneficiaryOut])
async def list_beneficiaries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[BeneficiaryStatus] = Query(None, alias="status"),
    category_id: Optional[int] = None,
    district_id: Optional[int] = None,
    mart_id: Optional[int] = None,
    search: Optional[str] = Query(None, description="Matches name, beneficiary code, or CNIC"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(Beneficiary)
    count_query = select(func.count()).select_from(Beneficiary)

    filters = []
    if status_filter:
        filters.append(Beneficiary.status == status_filter)
    if category_id:
        filters.append(Beneficiary.category_id == category_id)
    if district_id:
        filters.append(Beneficiary.district_id == district_id)
    if mart_id:
        filters.append(Beneficiary.mart_id == mart_id)
    if search:
        like = f"%{search}%"
        filters.append((Beneficiary.full_name.ilike(like)) | (Beneficiary.beneficiary_code.ilike(like)) | (Beneficiary.cnic.ilike(like)))

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total_items = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Beneficiary.id.desc()).offset((page - 1) * page_size).limit(page_size)
    beneficiaries = (await db.execute(query)).scalars().all()

    return Page(
        items=[_to_beneficiary_out(b, current_user) for b in beneficiaries],
        meta=PageMeta(page=page, page_size=page_size, total_items=total_items, total_pages=max(1, -(-total_items // page_size))),
    )


@router.get("/{beneficiary_id}", response_model=BeneficiaryOut)
async def get_beneficiary(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    beneficiary = await db.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")
    return _to_beneficiary_out(beneficiary, current_user)


@router.post("", response_model=BeneficiaryOut, status_code=status.HTTP_201_CREATED)
async def create_beneficiary(
    payload: BeneficiaryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_CREATE)),
):
    if await db.get(District, payload.district_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="District does not exist")

    if payload.cnic:
        existing = await db.execute(select(Beneficiary).where(Beneficiary.cnic == payload.cnic))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A beneficiary with this CNIC is already registered (possible duplicate identity)",
            )

    beneficiary = Beneficiary(**payload.model_dump(), beneficiary_code="PENDING", status=BeneficiaryStatus.PENDING)
    db.add(beneficiary)
    await db.flush()
    beneficiary.beneficiary_code = make_code("BEN", beneficiary.id)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="beneficiary.create",
        entity_type="Beneficiary", entity_id=beneficiary.id,
        new_value={"full_name": beneficiary.full_name, "district_id": beneficiary.district_id},
    )
    await db.commit()
    await db.refresh(beneficiary)
    return _to_beneficiary_out(beneficiary, current_user)


@router.patch("/{beneficiary_id}", response_model=BeneficiaryOut)
async def update_beneficiary(
    beneficiary_id: int,
    payload: BeneficiaryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_UPDATE)),
):
    beneficiary = await db.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(beneficiary, field, value)

    # Never log raw sensitive values in the audit trail — log which fields changed, not the values.
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="beneficiary.update",
        entity_type="Beneficiary", entity_id=beneficiary.id,
        new_value={"fields_changed": list(changes.keys())},
    )
    await db.commit()
    await db.refresh(beneficiary)
    return _to_beneficiary_out(beneficiary, current_user)


@router.post("/{beneficiary_id}/suspend", response_model=BeneficiaryOut)
async def suspend_beneficiary(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_APPROVE)),
):
    beneficiary = await db.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")

    previous_status = beneficiary.status.value
    beneficiary.status = BeneficiaryStatus.SUSPENDED
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="beneficiary.suspend",
        entity_type="Beneficiary", entity_id=beneficiary.id,
        previous_value={"status": previous_status}, new_value={"status": BeneficiaryStatus.SUSPENDED.value},
    )
    await db.commit()
    await db.refresh(beneficiary)
    return _to_beneficiary_out(beneficiary, current_user)


@router.post("/{beneficiary_id}/reactivate", response_model=BeneficiaryOut)
async def reactivate_beneficiary(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_APPROVE)),
):
    beneficiary = await db.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")
    if beneficiary.status != BeneficiaryStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only suspended beneficiaries can be reactivated")

    beneficiary.status = BeneficiaryStatus.ACTIVE
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="beneficiary.reactivate",
        entity_type="Beneficiary", entity_id=beneficiary.id,
        previous_value={"status": "suspended"}, new_value={"status": "active"},
    )
    await db.commit()
    await db.refresh(beneficiary)
    return _to_beneficiary_out(beneficiary, current_user)
