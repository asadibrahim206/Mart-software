from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.beneficiary import (
    ApplicationStatus, BeneficiaryStatus, CardStatus, DocumentVerificationStatus,
)

MASK = "••••••••"


# ---------------------------------------------------------------------------
# Categories & Programs
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool


class ProgramCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProgramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Beneficiaries
# ---------------------------------------------------------------------------

class BeneficiaryCreate(BaseModel):
    full_name: str
    father_husband_name: Optional[str] = None
    cnic: Optional[str] = None
    mobile_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = None
    tehsil: Optional[str] = None
    union_council: Optional[str] = None
    village_area: Optional[str] = None
    family_size: Optional[int] = None
    number_of_children: Optional[int] = None
    employment_status: Optional[str] = None
    household_income: Optional[Decimal] = None
    income_source: Optional[str] = None
    category_id: Optional[int] = None
    district_id: int
    mart_id: Optional[int] = None
    notes: Optional[str] = None


class BeneficiaryUpdate(BaseModel):
    full_name: Optional[str] = None
    father_husband_name: Optional[str] = None
    cnic: Optional[str] = None
    mobile_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = None
    tehsil: Optional[str] = None
    union_council: Optional[str] = None
    village_area: Optional[str] = None
    family_size: Optional[int] = None
    number_of_children: Optional[int] = None
    employment_status: Optional[str] = None
    household_income: Optional[Decimal] = None
    income_source: Optional[str] = None
    category_id: Optional[int] = None
    mart_id: Optional[int] = None
    notes: Optional[str] = None


class BeneficiaryOut(BaseModel):
    """
    Sensitive fields (cnic, mobile_number, household_income) are masked unless the caller has
    Perm.BENEFICIARIES_VIEW_SENSITIVE — the router decides this, not the schema itself, so the
    mask/unmask logic lives in one place (see _to_beneficiary_out in beneficiaries.py).
    """
    id: int
    beneficiary_code: str
    full_name: str
    father_husband_name: Optional[str] = None
    cnic: Optional[str] = None
    mobile_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = None
    tehsil: Optional[str] = None
    union_council: Optional[str] = None
    village_area: Optional[str] = None
    family_size: Optional[int] = None
    number_of_children: Optional[int] = None
    employment_status: Optional[str] = None
    household_income: Optional[Decimal] = None
    income_source: Optional[str] = None
    category_id: Optional[int] = None
    program_id: Optional[int] = None
    district_id: int
    mart_id: Optional[int] = None
    status: BeneficiaryStatus
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

class ApplicationCreate(BaseModel):
    """Starts a new application for an existing beneficiary (or one just created alongside it)."""
    beneficiary_id: int
    category_id: Optional[int] = None
    program_id: Optional[int] = None
    district_id: int
    mart_id: Optional[int] = None
    notes: Optional[str] = None


class ApplicationDecision(BaseModel):
    reason: Optional[str] = Field(None, description="Required for reject / request-more-info")


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_code: str
    beneficiary_id: int
    category_id: Optional[int] = None
    program_id: Optional[int] = None
    district_id: int
    mart_id: Optional[int] = None
    status: ApplicationStatus
    submitted_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by_user_id: Optional[int] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentVerify(BaseModel):
    verification_status: DocumentVerificationStatus
    notes: Optional[str] = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: int
    document_type: str
    document_number: Optional[str] = None
    original_filename: Optional[str] = None
    verification_status: DocumentVerificationStatus
    verified_by_user_id: Optional[int] = None
    verification_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Verification records (read-only — created internally by workflow actions)
# ---------------------------------------------------------------------------

class VerificationRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: int
    user_id: int
    action: str
    decision: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Welfare cards
# ---------------------------------------------------------------------------

class CardIssueRequest(BaseModel):
    expiry_date: Optional[date] = None
    mart_id: Optional[int] = None


class CardStatusUpdate(BaseModel):
    status: CardStatus
    reason: Optional[str] = None


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    beneficiary_id: int
    card_number: str
    qr_token: str
    issue_date: date
    expiry_date: Optional[date] = None
    status: CardStatus
    program_id: Optional[int] = None
    mart_id: Optional[int] = None
    replaced_from_card_id: Optional[int] = None
