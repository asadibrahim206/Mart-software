"""
Beneficiary system (Phase 2).

Key modeling decision: a Beneficiary (the person) is distinct from an Application (a request
event). A beneficiary record is created the moment someone starts an application (status=DRAFT)
and persists for their whole relationship with the program — they may submit multiple
applications over time (e.g. re-applying after a card expires). This mirrors the real-world
spec: "maintain complete history", "never silently delete rejected applications".

Sensitive fields (cnic, mobile_number, household_income) are stored in full here — masking for
users without Perm.BENEFICIARIES_VIEW_SENSITIVE happens at the schema/serialization layer
(app/api/v1/beneficiaries.py), never by omitting data from the database.

WelfareProgram is intentionally lightweight in this phase (name/code/description only) — the
full entitlement engine (rules, allocations, usage tracking) is Phase 3. Beneficiaries and
Applications already reference program_id so Phase 3 can attach entitlement rules without a
schema change here.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date, DateTime, Enum, ForeignKey, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


# ---------------------------------------------------------------------------
# Configuration tables
# ---------------------------------------------------------------------------

class BeneficiaryCategory(Base, TimestampMixin):
    """Configurable eligibility category (Widow, Elderly, Orphan, ...) — never hardcoded."""
    __tablename__ = "beneficiary_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)


class WelfareProgram(Base, TimestampMixin):
    """Lightweight in Phase 2 — entitlement rules attach to this in Phase 3."""
    __tablename__ = "welfare_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BeneficiaryStatus(str, enum.Enum):
    PENDING = "pending"       # has an application in progress, not yet approved
    ACTIVE = "active"         # approved and in good standing
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class ApplicationStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    VERIFICATION = "verification"
    APPROVED = "approved"
    CARD_ISSUED = "card_issued"
    REJECTED = "rejected"
    REQUEST_MORE_INFO = "request_more_info"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    DEACTIVATED = "deactivated"


class DocumentVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class CardStatus(str, enum.Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    LOST = "lost"
    REPLACED = "replaced"
    DEACTIVATED = "deactivated"


# ---------------------------------------------------------------------------
# Core tables
# ---------------------------------------------------------------------------

class Beneficiary(Base, TimestampMixin):
    __tablename__ = "beneficiaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    beneficiary_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Identity — cnic, mobile_number, household_income are masked for non-privileged users
    # at the API layer (see app/api/v1/beneficiaries.py) but always stored unmasked here.
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    father_husband_name: Mapped[Optional[str]] = mapped_column(String(150))
    cnic: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    mobile_number: Mapped[Optional[str]] = mapped_column(String(30))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    gender: Mapped[Optional[str]] = mapped_column(String(20))

    # Address (applicant's home address — administrative subdivisions as the applicant states
    # them, independent of the internal Region/District operational hierarchy below)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    province: Mapped[Optional[str]] = mapped_column(String(100))
    tehsil: Mapped[Optional[str]] = mapped_column(String(100))
    union_council: Mapped[Optional[str]] = mapped_column(String(100))
    village_area: Mapped[Optional[str]] = mapped_column(String(150))

    # Household
    family_size: Mapped[Optional[int]] = mapped_column()
    number_of_children: Mapped[Optional[int]] = mapped_column()
    employment_status: Mapped[Optional[str]] = mapped_column(String(50))
    household_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    income_source: Mapped[Optional[str]] = mapped_column(String(150))

    # Program assignment — which district/mart serves this beneficiary, which category/program
    # they're currently approved under (nullable until approval)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beneficiary_categories.id"), index=True)
    program_id: Mapped[Optional[int]] = mapped_column(ForeignKey("welfare_programs.id"), index=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), nullable=False, index=True)
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"), index=True)

    status: Mapped[BeneficiaryStatus] = mapped_column(Enum(BeneficiaryStatus), default=BeneficiaryStatus.PENDING, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    applications: Mapped[list["Application"]] = relationship(back_populates="beneficiary", order_by="Application.id.desc()")
    cards: Mapped[list["WelfareCard"]] = relationship(back_populates="beneficiary", order_by="WelfareCard.id.desc()")


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    beneficiary_id: Mapped[int] = mapped_column(ForeignKey("beneficiaries.id"), nullable=False, index=True)

    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beneficiary_categories.id"), index=True)
    program_id: Mapped[Optional[int]] = mapped_column(ForeignKey("welfare_programs.id"), index=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), nullable=False, index=True)
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"), index=True)

    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus), default=ApplicationStatus.DRAFT, nullable=False, index=True)

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    beneficiary: Mapped["Beneficiary"] = relationship(back_populates="applications")
    documents: Mapped[list["ApplicationDocument"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    verification_records: Mapped[list["VerificationRecord"]] = relationship(back_populates="application", cascade="all, delete-orphan", order_by="VerificationRecord.id")


class ApplicationDocument(Base, TimestampMixin):
    __tablename__ = "application_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)

    document_type: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. "cnic", "proof_of_address"
    document_number: Mapped[Optional[str]] = mapped_column(String(100))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)        # relative path under storage root
    original_filename: Mapped[Optional[str]] = mapped_column(String(255))

    verification_status: Mapped[DocumentVerificationStatus] = mapped_column(
        Enum(DocumentVerificationStatus), default=DocumentVerificationStatus.PENDING, nullable=False
    )
    verified_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    verification_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    application: Mapped["Application"] = relationship(back_populates="documents")


class VerificationRecord(Base, TimestampMixin):
    """Who / what / when / decision / reason — one row per verification action taken."""
    __tablename__ = "verification_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)   # reviewed | verified | request_more_info | approved | rejected
    decision: Mapped[Optional[str]] = mapped_column(String(50))
    reason: Mapped[Optional[str]] = mapped_column(String(500))

    application: Mapped["Application"] = relationship(back_populates="verification_records")


class WelfareCard(Base, TimestampMixin):
    __tablename__ = "welfare_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    beneficiary_id: Mapped[int] = mapped_column(ForeignKey("beneficiaries.id"), nullable=False, index=True)
    card_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # qr_token is an opaque random identifier — deliberately NOT the CNIC or any PII, per spec
    # section 10 ("Do not encode sensitive personal information directly inside the QR code").
    # The QR code itself (rendered image) is a client-side concern; this is just the encoded value.
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)

    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[CardStatus] = mapped_column(Enum(CardStatus), default=CardStatus.ACTIVE, nullable=False)

    program_id: Mapped[Optional[int]] = mapped_column(ForeignKey("welfare_programs.id"))
    mart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("marts.id"))
    replaced_from_card_id: Mapped[Optional[int]] = mapped_column(ForeignKey("welfare_cards.id"))

    beneficiary: Mapped["Beneficiary"] = relationship(back_populates="cards")
