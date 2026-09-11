from fastapi import APIRouter

from app.api.v1 import (
    applications, audit, auth, beneficiaries, budgets, cards, categories, commodities,
    documents, entitlements, expenses, finance_reports, locations, organizations, products,
    roles, sales, shifts, stock, suppliers, users, warehouse_transfers, welfare_transactions,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(organizations.router)
api_router.include_router(locations.router)
api_router.include_router(categories.router)
api_router.include_router(beneficiaries.router)
api_router.include_router(applications.router)
api_router.include_router(documents.router)
api_router.include_router(cards.router)
api_router.include_router(commodities.router)
api_router.include_router(entitlements.router)
api_router.include_router(budgets.router)
api_router.include_router(welfare_transactions.router)
api_router.include_router(products.router)
api_router.include_router(stock.router)
api_router.include_router(suppliers.router)
api_router.include_router(warehouse_transfers.router)
api_router.include_router(shifts.router)
api_router.include_router(sales.router)
api_router.include_router(expenses.router)
api_router.include_router(finance_reports.router)
api_router.include_router(audit.router)
