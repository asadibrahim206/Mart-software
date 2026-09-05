"""
The only sanctioned way to write an audit entry. Every service that mutates something
sensitive (users, roles, permission grants, and — in later phases — beneficiaries, cards,
entitlements, welfare transactions, stock, expenses) should call `record()` in the SAME
DB transaction as the mutation itself, so the audit row and the change it describes either
both commit or both roll back together.
"""
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    role_name: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    previous_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        role_name=role_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        previous_value=previous_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    # Deliberately no commit() here — caller commits as part of its own transaction.
