"""
Document upload/verification.

Files are saved to a local `storage/documents/` directory (created on first use) with a
randomized filename to avoid collisions and path traversal from user-supplied names — the
original filename is preserved separately in the DB for display purposes only. In production
this should point at proper object storage (S3-compatible) rather than local disk; swapping the
`_save_upload` function is the only change needed since callers only see `file_path`.
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.beneficiary import Application, ApplicationDocument, DocumentVerificationStatus
from app.schemas.beneficiary import DocumentOut, DocumentVerify
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Application Documents"])

STORAGE_ROOT = Path("storage/documents")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


def _save_upload(file: UploadFile, contents: bytes) -> str:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = STORAGE_ROOT / safe_name
    with open(dest, "wb") as f:
        f.write(contents)
    return str(dest)


@router.post("/applications/{application_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    application_id: int,
    document_type: str = Form(...),
    document_number: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.DOCUMENTS_MANAGE)),
):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 10MB limit")

    file_path = _save_upload(file, contents)

    document = ApplicationDocument(
        application_id=application_id,
        document_type=document_type,
        document_number=document_number,
        file_path=file_path,
        original_filename=file.filename,
    )
    db.add(document)
    await db.flush()

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="document.upload",
        entity_type="ApplicationDocument", entity_id=document.id,
        new_value={"application_id": application_id, "document_type": document_type, "filename": file.filename},
    )
    await db.commit()
    await db.refresh(document)
    return document


@router.get("/applications/{application_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VIEW)),
):
    result = await db.execute(
        select(ApplicationDocument).where(ApplicationDocument.application_id == application_id).order_by(ApplicationDocument.id)
    )
    return result.scalars().all()


@router.post("/documents/{document_id}/verify", response_model=DocumentOut)
async def verify_document(
    document_id: int,
    payload: DocumentVerify,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.BENEFICIARIES_VERIFY)),
):
    document = await db.get(ApplicationDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    previous_status = document.verification_status.value
    document.verification_status = payload.verification_status
    document.verified_by_user_id = current_user.id
    document.verification_date = datetime.now(timezone.utc)
    document.notes = payload.notes

    await audit_service.record(
        db, user_id=current_user.id, role_name=None, action="document.verify",
        entity_type="ApplicationDocument", entity_id=document.id,
        previous_value={"verification_status": previous_status},
        new_value={"verification_status": payload.verification_status.value},
    )
    await db.commit()
    await db.refresh(document)
    return document
