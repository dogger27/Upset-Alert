from typing import Optional
from pydantic import BaseModel, EmailStr


class UserRegister(BaseModel):
    email: EmailStr
    username: str
    full_name: str
    display_name: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: str
    is_admin: bool = False

    model_config = {"from_attributes": True}


class UserPublicOut(BaseModel):
    id: int
    display_name: str
    username: Optional[str] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None


class UserAdminOut(BaseModel):
    id: int
    email: str
    username: Optional[str] = None
    display_name: str
    email_verified: bool
    is_admin: bool
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
