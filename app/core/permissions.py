"""
Single source of truth for permission codes.

These constants are what route handlers pass to `require_permission()` — never a raw string
scattered through the codebase, so a typo fails at import time (NameError) instead of silently
letting a request through. The actual role -> permission mapping is DB data (role_permissions
table, editable from the admin UI); this module only defines the vocabulary of possible
permissions and seeds sensible defaults for the built-in roles described in the spec.

Naming convention: "<module>.<action>"
"""


class Perm:
    # ---- Users & RBAC administration ----
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    USERS_DEACTIVATE = "users.deactivate"
    ROLES_VIEW = "roles.view"
    ROLES_MANAGE = "roles.manage"            # create/update roles + attach permissions
    PERMISSIONS_VIEW = "permissions.view"

    # ---- Organization / locations ----
    ORG_VIEW = "organizations.view"
    ORG_MANAGE = "organizations.manage"       # create/update org, regions, districts
    WAREHOUSES_VIEW = "warehouses.view"
    WAREHOUSES_MANAGE = "warehouses.manage"
    MARTS_VIEW = "marts.view"
    MARTS_MANAGE = "marts.manage"

    # ---- Beneficiaries (Phase 2) ----
    BENEFICIARIES_VIEW = "beneficiaries.view"
    BENEFICIARIES_VIEW_SENSITIVE = "beneficiaries.view_sensitive"  # unmasked CNIC/income/contact
    BENEFICIARIES_CREATE = "beneficiaries.create"
    BENEFICIARIES_UPDATE = "beneficiaries.update"
    BENEFICIARIES_APPROVE = "beneficiaries.approve"       # approve/reject/request-info decisions
    BENEFICIARIES_VERIFY = "beneficiaries.verify"          # review documents, mark verification steps
    CATEGORIES_MANAGE = "categories.manage"
    DOCUMENTS_MANAGE = "documents.manage"                   # upload/verify supporting documents
    CARDS_MANAGE = "cards.manage"

    # ---- Welfare (Phase 3) ----
    WELFARE_CONFIGURE = "welfare.configure"       # entitlement rules, commodities
    WELFARE_DISTRIBUTE = "welfare.distribute"     # perform a welfare transaction
    WELFARE_VOID = "welfare.void"                  # void/reverse a welfare transaction
    WELFARE_BUDGET_MANAGE = "welfare.budget_manage"
    WELFARE_REPORTS_VIEW = "welfare.reports.view"

    # ---- Inventory / procurement (Phase 4) ----
    INVENTORY_VIEW = "inventory.view"
    INVENTORY_MANAGE = "inventory.manage"
    PROCUREMENT_MANAGE = "procurement.manage"

    # ---- POS (Phase 5) ----
    POS_SELL = "pos.sell"
    POS_REFUND = "pos.refund"
    POS_CLOSE_SHIFT = "pos.close_shift"

    # ---- Finance (Phase 6) ----
    FINANCE_VIEW = "finance.view"
    FINANCE_MANAGE = "finance.manage"

    # ---- Reports / audit ----
    REPORTS_VIEW = "reports.view"
    AUDIT_VIEW = "audit.view"


# Descriptions + module grouping, used by the seed script to populate the permissions table.
PERMISSION_REGISTRY: dict[str, tuple[str, str]] = {
    # code: (module, description)
    Perm.USERS_VIEW: ("users", "View staff user accounts"),
    Perm.USERS_CREATE: ("users", "Create staff user accounts"),
    Perm.USERS_UPDATE: ("users", "Update staff user accounts"),
    Perm.USERS_DEACTIVATE: ("users", "Deactivate/reactivate staff user accounts"),
    Perm.ROLES_VIEW: ("rbac", "View roles"),
    Perm.ROLES_MANAGE: ("rbac", "Create/update roles and assign permissions"),
    Perm.PERMISSIONS_VIEW: ("rbac", "View the permission catalog"),
    Perm.ORG_VIEW: ("organizations", "View organization/region/district structure"),
    Perm.ORG_MANAGE: ("organizations", "Create/update organization/region/district structure"),
    Perm.WAREHOUSES_VIEW: ("locations", "View warehouses"),
    Perm.WAREHOUSES_MANAGE: ("locations", "Create/update warehouses"),
    Perm.MARTS_VIEW: ("locations", "View marts"),
    Perm.MARTS_MANAGE: ("locations", "Create/update marts"),
    Perm.BENEFICIARIES_VIEW: ("beneficiaries", "View beneficiaries and applications (sensitive fields masked)"),
    Perm.BENEFICIARIES_VIEW_SENSITIVE: ("beneficiaries", "View unmasked CNIC, income, and contact details"),
    Perm.BENEFICIARIES_CREATE: ("beneficiaries", "Register beneficiaries/applications"),
    Perm.BENEFICIARIES_UPDATE: ("beneficiaries", "Edit beneficiary/application details"),
    Perm.BENEFICIARIES_APPROVE: ("beneficiaries", "Approve, reject, or request more info on applications"),
    Perm.BENEFICIARIES_VERIFY: ("beneficiaries", "Review and verify application documents"),
    Perm.CATEGORIES_MANAGE: ("beneficiaries", "Configure beneficiary categories"),
    Perm.DOCUMENTS_MANAGE: ("beneficiaries", "Upload and verify supporting documents"),
    Perm.CARDS_MANAGE: ("beneficiaries", "Issue/block/replace welfare cards"),
    Perm.WELFARE_CONFIGURE: ("welfare", "Configure programs, commodities, and entitlement rules"),
    Perm.WELFARE_DISTRIBUTE: ("welfare", "Perform welfare distributions at POS"),
    Perm.WELFARE_VOID: ("welfare", "Void/reverse a welfare transaction"),
    Perm.WELFARE_BUDGET_MANAGE: ("welfare", "Create and manage welfare budgets"),
    Perm.WELFARE_REPORTS_VIEW: ("welfare", "View welfare reports"),
    Perm.INVENTORY_VIEW: ("inventory", "View products and stock"),
    Perm.INVENTORY_MANAGE: ("inventory", "Manage products, stock, transfers, adjustments"),
    Perm.PROCUREMENT_MANAGE: ("procurement", "Manage suppliers and purchase orders"),
    Perm.POS_SELL: ("pos", "Process normal sales at POS"),
    Perm.POS_REFUND: ("pos", "Process refunds"),
    Perm.POS_CLOSE_SHIFT: ("pos", "Perform cashier shift closing"),
    Perm.FINANCE_VIEW: ("finance", "View expenses, budgets, payables"),
    Perm.FINANCE_MANAGE: ("finance", "Manage expenses, budgets, payables"),
    Perm.REPORTS_VIEW: ("reports", "View reporting/analytics dashboards"),
    Perm.AUDIT_VIEW: ("audit", "View the audit log"),
}

# Default role -> permission mapping used by the seed script (admin can change this later
# through the Roles UI — this is only the sensible starting point from the spec).
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "Super Admin": list(PERMISSION_REGISTRY.keys()),  # everything
    "Program Director": [
        Perm.BENEFICIARIES_VIEW, Perm.BENEFICIARIES_VIEW_SENSITIVE, Perm.CATEGORIES_MANAGE,
        Perm.WELFARE_CONFIGURE, Perm.WELFARE_BUDGET_MANAGE, Perm.WELFARE_REPORTS_VIEW,
        Perm.REPORTS_VIEW, Perm.ORG_VIEW,
    ],
    "Welfare Manager": [
        Perm.BENEFICIARIES_VIEW, Perm.BENEFICIARIES_VIEW_SENSITIVE, Perm.BENEFICIARIES_CREATE,
        Perm.BENEFICIARIES_UPDATE, Perm.BENEFICIARIES_APPROVE, Perm.BENEFICIARIES_VERIFY,
        Perm.CATEGORIES_MANAGE, Perm.DOCUMENTS_MANAGE, Perm.CARDS_MANAGE,
        Perm.WELFARE_CONFIGURE, Perm.WELFARE_DISTRIBUTE, Perm.WELFARE_VOID,
        Perm.WELFARE_BUDGET_MANAGE, Perm.WELFARE_REPORTS_VIEW,
    ],
    "Finance Manager": [
        Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE, Perm.WELFARE_REPORTS_VIEW, Perm.REPORTS_VIEW,
    ],
    "Procurement Manager": [
        Perm.PROCUREMENT_MANAGE, Perm.INVENTORY_VIEW, Perm.REPORTS_VIEW,
    ],
    "Warehouse Manager": [
        Perm.INVENTORY_VIEW, Perm.INVENTORY_MANAGE, Perm.WAREHOUSES_VIEW,
    ],
    "District Manager": [
        Perm.ORG_VIEW, Perm.MARTS_VIEW, Perm.BENEFICIARIES_VIEW, Perm.BENEFICIARIES_VIEW_SENSITIVE,
        Perm.WELFARE_REPORTS_VIEW, Perm.REPORTS_VIEW,
    ],
    "Mart Manager": [
        Perm.MARTS_VIEW, Perm.INVENTORY_VIEW, Perm.POS_SELL, Perm.POS_REFUND,
        Perm.POS_CLOSE_SHIFT, Perm.WELFARE_DISTRIBUTE, Perm.BENEFICIARIES_VIEW,
        Perm.BENEFICIARIES_VIEW_SENSITIVE, Perm.REPORTS_VIEW,
    ],
    "Cashier": [
        Perm.POS_SELL, Perm.WELFARE_DISTRIBUTE, Perm.POS_CLOSE_SHIFT,
    ],
    "Data Entry Operator": [
        Perm.BENEFICIARIES_CREATE, Perm.BENEFICIARIES_VIEW, Perm.DOCUMENTS_MANAGE,
    ],
    "Auditor": [
        Perm.AUDIT_VIEW, Perm.REPORTS_VIEW, Perm.BENEFICIARIES_VIEW, Perm.BENEFICIARIES_VIEW_SENSITIVE,
        Perm.WELFARE_REPORTS_VIEW, Perm.FINANCE_VIEW,
    ],
}
