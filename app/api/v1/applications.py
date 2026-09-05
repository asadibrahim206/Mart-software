from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import (
    Application, ApplicationStatus, Beneficiary, BeneficiaryStatus, VerificationRecord,
)
from app.models.organization import District
from app.schemas.beneficiary import ApplicationCreate, ApplicationDecision, ApplicationOut
from app.schemas.common import Page, PageMeta
from app.schemas.user import CurrentUser
from app.services import audit_service
from app.services.application_service import make_code, validate_transition

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.get("", response_model=Page[ApplicationOut])
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[ApplicationStatus] = Query(None, alias="status"),
    beneficiary_id: Optional[int] = None,
    district_id: Optional[int] = None,
    mart_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    query = select(Application)
    count_query = select(func.count()).select_from(Application)

    filters = []
    if status_filter:
        filters.append(Application.status == status_filter)
    if beneficiary_id:
        filters.append(Application.beneficiary_id == beneficiary_id)
    if district_id:
        filters.append(Application.district_id == district_id)
    if mart_id:
        filters.append(Application.mart_id == mart_id)

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total_items = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Application.id.desc()).offset((page - 1) * page_size).limit(page_size)
    applications = (await db.execute(query)).scalars().all()

    return Page(
        items=applications,
        meta=PageMeta(page=page, page_size=page_size, total_items=total_items, total_pages=max(1, -(-total_items // page_size))),
    )


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_CREATE)),
):
    beneficiary = await db.get(Beneficiary, payload.beneficiary_id)
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Beneficiary does not exist")
    if await db.get(District, payload.district_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="District does not exist")

    application = Application(
        application_code="PENDING",
        beneficiary_id=payload.beneficiary_id,
        category_id=payload.category_id,
        program_id=payload.program_id,
        district_id=payload.district_id,
        mart_id=payload.mart_id,
        notes=payload.notes,
        status=ApplicationStatus.DRAFT,
    )
    db.add(application)
    await db.flush()
    application.application_code = make_code("APP", application.id)

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="application.create",
        entity_type="Application", entity_id=application.id,
        new_value={"beneficiary_id": application.beneficiary_id},
    )
    await db.commit()
    await db.refresh(application)
    return application


async def _transition(
    db: AsyncSession,
    application: Application,
    target: ApplicationStatus,
    action_label: str,
    current_user: CurrentUser,
    reason: Optional[str] = None,
) -> Application:
    validate_transition(application.status, target, reason)
    previous_status = application.status.value
    application.status = target

    if target == ApplicationStatus.SUBMITTED and application.submitted_at is None:
        application.submitted_at = datetime.now(timezone.utc)
    if target in (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED):
        application.decided_at = datetime.now(timezone.utc)
        application.decided_by_user_id = current_user.id
    if target == ApplicationStatus.REJECTED:
        application.rejection_reason = reason

    db.add(VerificationRecord(
        application_id=application.id, user_id=current_user.id,
        action=action_label, decision=target.value, reason=reason,
    ))
    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action=f"application.{action_label}",
        entity_type="Application", entity_id=application.id,
        previous_value={"status": previous_status}, new_value={"status": target.value, "reason": reason},
    )

    # Approval activates the beneficiary and assigns the applied-for category/program.
    if target == ApplicationStatus.APPROVED:
        beneficiary = await db.get(Beneficiary, application.beneficiary_id)
        if beneficiary is not None:
            beneficiary.status = BeneficiaryStatus.ACTIVE
            if application.category_id:
                beneficiary.category_id = application.category_id
            if application.program_id:
                beneficiary.program_id = application.program_id
            if application.mart_id:
                beneficiary.mart_id = application.mart_id

    await db.commit()
    await db.refresh(application)
    return application


@router.post("/{application_id}/submit", response_model=ApplicationOut)
async def submit_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_CREATE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.SUBMITTED, "submitted", current_user)


@router.post("/{application_id}/start-review", response_model=ApplicationOut)
async def start_review(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VERIFY)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.UNDER_REVIEW, "reviewed", current_user)


@router.post("/{application_id}/send-for-verification", response_model=ApplicationOut)
async def send_for_verification(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VERIFY)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.VERIFICATION, "sent_for_verification", current_user)


@router.post("/{application_id}/approve", response_model=ApplicationOut)
async def approve_application(
    application_id: int,
    payload: ApplicationDecision,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_APPROVE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.APPROVED, "approved", current_user, payload.reason)


@router.post("/{application_id}/reject", response_model=ApplicationOut)
async def reject_application(
    application_id: int,
    payload: ApplicationDecision,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_APPROVE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.REJECTED, "rejected", current_user, payload.reason)


@router.post("/{application_id}/request-more-info", response_model=ApplicationOut)
async def request_more_info(
    application_id: int,
    payload: ApplicationDecision,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VERIFY)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.REQUEST_MORE_INFO, "requested_more_info", current_user, payload.reason)


@router.post("/{application_id}/resubmit", response_model=ApplicationOut)
async def resubmit_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_CREATE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await _transition(db, application, ApplicationStatus.UNDER_REVIEW, "resubmitted", current_user)
