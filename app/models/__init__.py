"""
Import every model module here so that Base.metadata is fully populated for Alembic
autogenerate and for relationship string-resolution at mapper configuration time.
As new modules (beneficiaries, welfare, inventory, ...) are added in later phases,
import them here too.
"""
from app.models.organization import District, Mart, Organization, Region, Warehouse  # noqa: F401
from app.models.rbac import Permission, Role, RolePermission, UserRole  # noqa: F401
from app.models.user import User, UserStatus  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.beneficiary import (  # noqa: F401
    Application, ApplicationDocument, ApplicationStatus, Beneficiary, BeneficiaryCategory,
    BeneficiaryStatus, CardStatus, DocumentVerificationStatus, VerificationRecord, WelfareCard,
    WelfareProgram,
)
from app.models.welfare import (  # noqa: F401
    BeneficiaryEntitlementUsage, Commodity, EntitlementPeriod, EntitlementRule, WelfareBudget,
    WelfareTransaction, WelfareTransactionItem, WelfareTransactionStatus,
)
from app.models.inventory import (  # noqa: F401
    ProductCategory, PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, Product, Stock,
    StockMovement, StockMovementType, Supplier, SupplierStatus, TransferStatus,
    WarehouseTransfer, WarehouseTransferItem,
)
from app.models.pos import (  # noqa: F401
    CashierShift, Payment, PaymentMethod, PaymentStatus, Refund, Sale, SaleItem, SaleStatus,
    ShiftStatus,
)
from app.models.finance import (  # noqa: F401
    Expense, ExpenseCategory, ExpenseStatus, SupplierPayment,
)
