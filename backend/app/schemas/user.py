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
    # Echoed back so the client can tell whether the browser's zone already
    # matches what we hold, and skip the write when it does.
    timezone: Optional[str] = None
    # Drives which palette the client paints on load. NULL = light.
    theme: Optional[str] = None

    model_config = {"from_attributes": True}


class UserPublicOut(BaseModel):
    id: int
    display_name: str
    username: Optional[str] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    timezone: Optional[str] = None
    theme: Optional[str] = None


class UserAdminOut(BaseModel):
    id: int
    email: str
    username: Optional[str] = None
    display_name: str
    email_verified: bool
    is_admin: bool
    is_bot: bool = False
    created_at: Optional[str] = None
    # True when at least one registered push device looks like a phone or
    # tablet. Counted from the stored user_agent rather than from "has any
    # subscription", so a desktop-only registration doesn't read as mobile.
    has_mobile_device: bool = False
    # When the installed app was last opened on a phone; None when the tick
    # comes from a push registration rather than an observed app launch.
    mobile_app_seen_at: Optional[str] = None

    model_config = {"from_attributes": True}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
