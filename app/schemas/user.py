from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserStatus
from app.schemas.rbac import RoleOut, UserRoleAssign


class UserCreate(BaseModel):
    organization_id: int
    region_id: Optional[int] = None
    district_id: Optional[int] = None
    mart_id: Optional[int] = None
    warehouse_id: Optional[int] = None

    username: str = Field(..., min_length=3, max_length=60)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str
    phone: Optional[str] = None

    role_assignments: List[UserRoleAssign] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    region_id: Optional[int] = None
    district_id: Optional[int] = None
    mart_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    status: Optional[UserStatus] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    region_id: Optional[int] = None
    district_id: Optional[int] = None
    mart_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    username: str
    email: str
    full_name: str
    phone: Optional[str] = None
    status: UserStatus
    must_change_password: bool
    roles: List[RoleOut] = []


class CurrentUser(BaseModel):
    """Lightweight representation attached to request.state / returned by /auth/me."""
    id: int
    username: str
    full_name: str
    email: str
    organization_id: int
    mart_id: Optional[int] = None
    district_id: Optional[int] = None
    permission_codes: List[str]
    role_names: List[str]
