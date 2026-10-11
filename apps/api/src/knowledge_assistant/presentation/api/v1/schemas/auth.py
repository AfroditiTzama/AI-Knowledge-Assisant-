from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    full_name: str = Field(min_length=2, max_length=255)


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_verified: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_verified: bool
    preferred_language: str
    theme_preference: str
    assistant_behavior: str
    created_at: datetime
    email_verified_at: datetime | None


class AuthSessionResponse(BaseModel):
    user: CurrentUserResponse
    csrf_token: str
    expires_in: int


class MessageResponse(BaseModel):
    message: str


class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    preferred_language: str = Field(pattern="^(en|el)$")
    theme_preference: str = Field(pattern="^(system|light|dark)$")
    assistant_behavior: str = Field(
        pattern="^(concise|balanced|detailed)$"
    )


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=10, max_length=256)


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class ActionDispatchResponse(BaseModel):
    message: str
    delivery: str


class SessionResponse(BaseModel):
    id: UUID
    current: bool
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str
    ip_address: str


class SecurityEventResponse(BaseModel):
    id: UUID
    event_type: str
    ip_address: str
    user_agent: str
    metadata: dict[str, object]
    created_at: datetime


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(min_length=6, max_length=6)
