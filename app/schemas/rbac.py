from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    module: str
    description: str


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permission_codes: List[str] = []


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permission_codes: Optional[List[str]] = None  # if provided, replaces the full set


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    is_system: bool
    is_active: bool
    permissions: List[PermissionOut] = []


class UserRoleAssign(BaseModel):
    role_id: int
    scope_type: Optional[str] = None  # organization | region | district | mart | warehouse
    scope_id: Optional[int] = None
