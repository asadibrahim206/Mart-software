# Ramzan Mart — Welfare Mart Management Platform

**Phase 1: Foundation** — Authentication, RBAC, Organizational structure (Organization → Region →
District → Warehouse/Mart), Audit logging groundwork.

This is a real, runnable slice — not a mockup. Every endpoint reads/writes PostgreSQL, enforces
permissions, and writes to the audit log.

## Stack
FastAPI (async) · SQLAlchemy 2.0 (async, PostgreSQL via `asyncpg`) · Alembic · Pydantic v2 · JWT auth (python-jose) · bcrypt password hashing

## Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set DATABASE_URL to your PostgreSQL instance,
# generate a real SECRET_KEY (e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
```

Create the database itself first (Alembic won't create the database, only the tables). Using `psql`:

```sql
CREATE DATABASE ramzan_mart;
CREATE USER ramzan_user WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE ramzan_mart TO ramzan_user;
-- PostgreSQL 15+ also needs schema-level grants:
\c ramzan_mart
GRANT ALL ON SCHEMA public TO ramzan_user;
```

Generate and apply the first migration:

```bash
alembic revision --autogenerate -m "phase 1: auth, rbac, organization structure"
alembic upgrade head
```

Bootstrap default roles, permissions, a root organization, and the first Super Admin account:

```bash
python -m app.seed.seed_data
```

This prints the super admin username — the password is whatever `SUPER_ADMIN_PASSWORD` was set
to in `.env`. **Log in and change it immediately** (`must_change_password` is set to `true`, so
build the frontend to force a password-change screen on first login using that flag).

Run the API:

```bash
uvicorn app.main:app --reload
```

Interactive API docs: `http://localhost:8000/api/v1/docs`

## What's implemented in this phase

- **Auth**: `/auth/login`, `/auth/refresh`, `/auth/me`, `/auth/change-password`. Account
  lockout after 5 failed attempts (15 min), account status enforcement (active/inactive/suspended).
- **RBAC**: `/roles`, `/permissions`, and per-user role assignment (`/users/{id}/roles`), each
  optionally scoped to a node in the org hierarchy (organization/region/district/mart/warehouse).
  Permissions are pure DB data — see `app/core/permissions.py` for the vocabulary and the
  sensible defaults seeded for each of the spec's named roles (Super Admin, Program Director,
  Welfare Manager, Finance Manager, Procurement Manager, Warehouse Manager, District Manager,
  Mart Manager, Cashier, Data Entry Operator, Auditor).
- **Organization structure**: `/organizations`, `/regions`, `/districts`, `/warehouses`, `/marts`
  — full hierarchy CRUD, everything traceable up the chain.
- **Users**: `/users` CRUD, search/filter/pagination, deactivation (never hard-deleted).
- **Audit log**: `/audit` (read-only, permission-gated). Every mutation above writes an audit
  row in the *same* DB transaction as the change it describes.

## What's implemented — Phase 2 (Beneficiaries)

- **Categories & Programs**: `/categories`, `/programs` — configurable, not hardcoded (spec section 6).
- **Beneficiaries**: `/beneficiaries` CRUD, search/filter/pagination, suspend/reactivate.
  Sensitive fields (CNIC, mobile number, address, household income) are masked in every response
  unless the caller holds `beneficiaries.view_sensitive` — masking happens server-side in
  `_to_beneficiary_out()`, never by the client hiding fields. Duplicate CNIC registration is blocked.
- **Applications**: `/applications` — full workflow state machine (draft → submitted → under_review
  → verification → approved/rejected/request_more_info → card_issued, plus suspend/expire/deactivate).
  Every transition is validated against `ALLOWED_TRANSITIONS` (`app/services/application_service.py`),
  requires a reason where the spec mandates one (reject, request-more-info, suspend), and writes both
  an audit log row and a `VerificationRecord` (who/what/when/decision/reason) automatically. Approving
  an application activates the beneficiary and assigns their category/program.
- **Documents**: `/applications/{id}/documents` — real file upload (10MB limit, image/PDF only) saved
  to `storage/documents/` with randomized filenames; `/documents/{id}/verify` for the review workflow.
- **Welfare Cards**: `/applications/{id}/issue-card` (only from an APPROVED application, moves it to
  CARD_ISSUED), `/cards/{id}/status` (block/suspend/expire/deactivate), `/cards/{id}/replace` (for lost
  cards — blocks the old card, issues a new card_number + qr_token, keeps full lineage via
  `replaced_from_card_id`). QR tokens are opaque random values, never CNIC or other PII.

### Trying the beneficiary flow end-to-end

1. `POST /categories` — create a category (e.g. "Widow")
2. `POST /beneficiaries` — register a person (needs a `district_id` from Phase 1 data)
3. `POST /applications` — start an application for that beneficiary
4. `POST /applications/{id}/submit` → `/start-review` → `/send-for-verification` → `/approve`
5. `POST /applications/{id}/issue-card` — issues their first welfare card

## What's deliberately NOT in this phase

Entitlement rules/allocation tracking, welfare transactions (POS distribution), inventory, POS
sales, procurement, finance, and reporting are Phases 3–7. `WelfareProgram` already exists as a
lightweight table so Phase 3 can attach entitlement rules to it without a schema change.

## What's implemented — Phase 5 (POS: Normal Sales)

- **Cashier Shifts**: `/cashier-shifts/open`, `/{id}/close`, `/my-open-shift`. A cashier must have
  an open shift at a mart before any sale can be recorded there — enforced in `sale_service`,
  not just the UI. Closing a shift freezes cash/card/digital sales totals, refunds, and this
  cashier's welfare distribution value for that window, then computes `expected_cash` vs
  `actual_cash` and the `cash_difference` (spec section 25).
- **Sales**: `/sales` — real stock deduction per line item (via the same `stock_service` used
  everywhere else), computed change due for cash payments, and `GET /sales/{id}` doubles as the
  receipt data endpoint. Refunds (`/sales/{id}/refund`) restore stock and are logged, never
  silently deleted.
- **Welfare Sale** (the other POS mode) is unchanged from Phase 3/4 — `/welfare-transactions` —
  intentionally a completely separate table and code path from `Sale`, per spec section 15's
  requirement to never mix normal and welfare transactions.



## Design notes worth knowing before you extend this

- **Permissions are checked fresh from the DB on every request**, not baked into the JWT. A
  revoked role or a suspended account takes effect on the user's very next request. This is a
  few extra ms of DB work per request; keep it that way — don't "optimize" it into the token.
- **Nothing is ever hard-deleted.** Every org-hierarchy table has `is_active`; users are
  deactivated, not dropped. When you add beneficiaries/cards/products in later phases, follow
  the same pattern — the audit trail requirement (section 32 of the spec) depends on it.
- **A user can hold multiple roles, each independently scoped** (`UserRole.scope_type` +
  `scope_id`). This is how "District Manager for District X" and "District Manager for
  District Y" work without creating a role per district — but scope enforcement (filtering
  query results down to a user's assigned district/mart) still needs to be added per-endpoint
  as those modules are built; Phase 1 only models the assignment, later phases must apply it.
