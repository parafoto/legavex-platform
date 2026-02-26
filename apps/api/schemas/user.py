"""User-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class Role(str, Enum):
    """User roles."""
    CLIENT = "CLIENT"
    CONSULTANT = "CONSULTANT"
    ADMIN = "ADMIN"


class UserBase(BaseModel):
    """Base user schema."""
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = None


class UserCreate(UserBase):
    """Schema for creating a user."""
    password: str = Field(..., min_length=6)
    role: Role = Role.CLIENT


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class UserResponse(UserBase):
    """Schema for user response."""
    id: str
    role: Role
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class UserWithToken(BaseModel):
    """Schema for user with JWT token."""
    user: UserResponse
    access_token: str
    token_type: str = "bearer"


class ConsultantProfileBase(BaseModel):
    """Base consultant profile schema."""
    specialization: Optional[str] = None
    region: Optional[str] = None
    seniority_level: Optional[str] = Field(None, alias="seniorityLevel")
    max_parallel_cases: int = Field(3, alias="maxParallelCases")


class ConsultantProfileResponse(ConsultantProfileBase):
    """Schema for consultant profile response."""
    id: str
    user_id: str = Field(alias="userId")
    is_active: bool = Field(alias="isActive")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class ConsultantWithProfile(UserResponse):
    """User with consultant profile."""
    profile: Optional[ConsultantProfileResponse] = None
