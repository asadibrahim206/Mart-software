from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrganizationCreate(BaseModel):
    name: str
    code: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    is_active: bool


class RegionCreate(BaseModel):
    organization_id: int
    name: str
    code: str


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    name: str
    code: str
    is_active: bool


class DistrictCreate(BaseModel):
    region_id: int
    name: str
    code: str


class DistrictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    region_id: int
    name: str
    code: str
    is_active: bool


class WarehouseCreate(BaseModel):
    district_id: int
    name: str
    code: str
    address: Optional[str] = None
    is_central: bool = False


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    district_id: int
    name: str
    code: str
    address: Optional[str] = None
    is_central: bool
    is_active: bool


class MartCreate(BaseModel):
    district_id: int
    default_warehouse_id: Optional[int] = None
    name: str
    code: str
    address: Optional[str] = None
    phone: Optional[str] = None
    accepts_welfare: bool = True


class MartUpdate(BaseModel):
    name: Optional[str] = None
    default_warehouse_id: Optional[int] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    accepts_welfare: Optional[bool] = None
    is_active: Optional[bool] = None


class MartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    district_id: int
    default_warehouse_id: Optional[int] = None
    name: str
    code: str
    address: Optional[str] = None
    phone: Optional[str] = None
    accepts_welfare: bool
    is_active: bool
