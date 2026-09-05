from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.permissions import Perm
from app.models.inventory import Product, ProductCategory
from app.schemas.inventory import (
    ProductCategoryCreate, ProductCategoryOut, ProductCategoryUpdate, ProductCreate,
    ProductOut, ProductUpdate,
)
from app.schemas.user import CurrentUser
from app.services import audit_service

router = APIRouter(tags=["Products & Categories"])


@router.get("/product-categories", response_model=list[ProductCategoryOut])
async def list_product_categories(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    query = select(ProductCategory).order_by(ProductCategory.name)
    if not include_inactive:
        query = query.where(ProductCategory.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/product-categories", response_model=ProductCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_product_category(
    payload: ProductCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    existing = await db.execute(select(ProductCategory).where(ProductCategory.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category code already in use")
    category = ProductCategory(**payload.model_dump())
    db.add(category)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="product_category.create",
                                entity_type="ProductCategory", entity_id=category.id, new_value=payload.model_dump())
    await db.commit()
    await db.refresh(category)
    return category


@router.patch("/product-categories/{category_id}", response_model=ProductCategoryOut)
async def update_product_category(
    category_id: int,
    payload: ProductCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(category, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="product_category.update",
                                entity_type="ProductCategory", entity_id=category.id, new_value=changes)
    await db.commit()
    await db.refresh(category)
    return category


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    search: str | None = Query(None, description="Matches name, SKU, or barcode"),
    category_id: int | None = None,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    query = select(Product).order_by(Product.name)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    if category_id:
        query = query.where(Product.category_id == category_id)
    if search:
        like = f"%{search}%"
        query = query.where((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.barcode.ilike(like)))
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_VIEW)),
):
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    existing = await db.execute(select(Product).where(Product.sku == payload.sku))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SKU already in use")

    product = Product(**payload.model_dump())
    db.add(product)
    await db.flush()
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="product.create",
                                entity_type="Product", entity_id=product.id, new_value=payload.model_dump(mode="json"))
    await db.commit()
    await db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Perm.INVENTORY_MANAGE)),
):
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await audit_service.record(db, user_id=current_user.id, role_name=None, action="product.update",
                                entity_type="Product", entity_id=product.id, new_value=changes)
    await db.commit()
    await db.refresh(product)
    return product
