"""
Application workflow state machine + code generation.

Centralizing ALLOWED_TRANSITIONS here (rather than scattering `if status == X` checks across
route handlers) means the workflow diagram in the spec (section 7) is enforced in exactly one
place, and adding a new transition later is a one-line change to this dict, not a hunt through
the API layer.
"""
from typing import Optional

from fastapi import HTTPException, status as http_status

from app.models.beneficiary import ApplicationStatus

# from_status -> set of statuses it may move to
ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: {ApplicationStatus.SUBMITTED},
    ApplicationStatus.SUBMITTED: {ApplicationStatus.UNDER_REVIEW},
    ApplicationStatus.UNDER_REVIEW: {
        ApplicationStatus.VERIFICATION, ApplicationStatus.REJECTED, ApplicationStatus.REQUEST_MORE_INFO,
    },
    ApplicationStatus.VERIFICATION: {
        ApplicationStatus.APPROVED, ApplicationStatus.REJECTED, ApplicationStatus.REQUEST_MORE_INFO,
    },
    ApplicationStatus.REQUEST_MORE_INFO: {ApplicationStatus.UNDER_REVIEW},
    ApplicationStatus.APPROVED: {ApplicationStatus.CARD_ISSUED, ApplicationStatus.SUSPENDED, ApplicationStatus.DEACTIVATED},
    ApplicationStatus.CARD_ISSUED: {ApplicationStatus.SUSPENDED, ApplicationStatus.EXPIRED, ApplicationStatus.DEACTIVATED},
    ApplicationStatus.SUSPENDED: {ApplicationStatus.APPROVED, ApplicationStatus.CARD_ISSUED, ApplicationStatus.DEACTIVATED},
    # REJECTED, EXPIRED, DEACTIVATED are terminal — no outbound transitions.
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.EXPIRED: set(),
    ApplicationStatus.DEACTIVATED: set(),
}

# Transitions that require a reason (rejection, request-more-info, suspension) per spec section 7.
REASON_REQUIRED_FOR = {
    ApplicationStatus.REJECTED, ApplicationStatus.REQUEST_MORE_INFO, ApplicationStatus.SUSPENDED,
}


def validate_transition(current: ApplicationStatus, target: ApplicationStatus, reason: Optional[str]) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot move application from '{current.value}' to '{target.value}'. "
                   f"Allowed next states: {sorted(s.value for s in allowed) or 'none (terminal state)'}",
        )
    if target in REASON_REQUIRED_FOR and not reason:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"A reason is required when moving an application to '{target.value}'",
        )


def make_code(prefix: str, entity_id: int) -> str:
    """Human-friendly sequential code, e.g. BEN-000123. Generated AFTER flush so id is known."""
    return f"{prefix}-{entity_id:06d}"
