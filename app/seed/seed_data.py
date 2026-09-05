"""
Idempotent bootstrap script — safe to run multiple times (skips anything that already exists).
Run with:  python -m app.seed.seed_data

This creates:
  - The full permission catalog (from PERMISSION_REGISTRY)
  - The default roles from the spec, with their default permission grants
  - One root Organization (edit SUPER_ADMIN_* / org fields in .env before running in a real deployment)
  - One Super Admin user who can log in and configure everything else through the API

Nothing here is meant to be the ONLY data path — all of this is also manageable later through
the /roles, /permissions, and /organizations admin endpoints. This script just avoids the
chicken-and-egg problem of needing an admin account to create the first admin account.
"""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS, PERMISSION_REGISTRY
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.rbac import Permission, Role, RolePermission
from app.models.user import User, UserStatus
from app.models.rbac import UserRole
from app.models.welfare import Commodity

STARTER_COMMODITIES = [
    # (name, code, unit) — matches the example in the spec's entitlement section.
    ("Flour", "FLOUR", "KG"),
    ("Rice", "RICE", "KG"),
    ("Sugar", "SUGAR", "KG"),
    ("Pulses", "PULSES", "KG"),
    ("Cooking Oil", "OIL", "L"),
]


async def seed_permissions(db) -> dict[str, Permission]:
    result = await db.execute(select(Permission))
    existing = {p.code: p for p in result.scalars().all()}

    for code, (module, description) in PERMISSION_REGISTRY.items():
        if code not in existing:
            perm = Permission(code=code, module=module, description=description)
            db.add(perm)
            existing[code] = perm
    await db.flush()
    return existing


async def seed_roles(db, permissions_by_code: dict[str, Permission]) -> dict[str, Role]:
    result = await db.execute(select(Role))
    existing = {r.name: r for r in result.scalars().all()}

    for role_name, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
        role = existing.get(role_name)
        if role is None:
            role = Role(name=role_name, is_system=(role_name == "Super Admin"))
            db.add(role)
            await db.flush()
            existing[role_name] = role

        current_codes = {link.permission_id for link in (await db.execute(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )).scalars().all()}

        for code in perm_codes:
            perm = permissions_by_code[code]
            if perm.id not in current_codes:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.flush()
    return existing


async def seed_organization(db) -> Organization:
    result = await db.execute(select(Organization).where(Organization.code == "HQ"))
    org = result.scalar_one_or_none()
    if org is None:
        org = Organization(name="Welfare Organization Head Office", code="HQ")
        db.add(org)
        await db.flush()
    return org


async def seed_super_admin(db, org: Organization, roles_by_name: dict[str, Role]) -> None:
    result = await db.execute(select(User).where(User.username == settings.SUPER_ADMIN_USERNAME))
    if result.scalar_one_or_none() is not None:
        print(f"Super admin '{settings.SUPER_ADMIN_USERNAME}' already exists — skipping.")
        return

    admin = User(
        organization_id=org.id,
        username=settings.SUPER_ADMIN_USERNAME,
        email=settings.SUPER_ADMIN_EMAIL,
        hashed_password=hash_password(settings.SUPER_ADMIN_PASSWORD),
        full_name="System Administrator",
        status=UserStatus.ACTIVE,
        must_change_password=True,
    )
    db.add(admin)
    await db.flush()

    db.add(UserRole(user_id=admin.id, role_id=roles_by_name["Super Admin"].id, scope_type=None, scope_id=None))
    print(f"Created super admin '{settings.SUPER_ADMIN_USERNAME}' — CHANGE THE DEFAULT PASSWORD IMMEDIATELY.")


async def seed_commodities(db) -> None:
    result = await db.execute(select(Commodity))
    existing_codes = {c.code for c in result.scalars().all()}
    for name, code, unit in STARTER_COMMODITIES:
        if code not in existing_codes:
            db.add(Commodity(name=name, code=code, unit=unit))
    await db.flush()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        permissions_by_code = await seed_permissions(db)
        roles_by_name = await seed_roles(db, permissions_by_code)
        org = await seed_organization(db)
        await seed_super_admin(db, org, roles_by_name)
        await seed_commodities(db)
        await db.commit()
    await engine.dispose()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
