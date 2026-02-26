"""Case-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field

from .user import Role


class CaseStatus(str, Enum):
    """Case status enum."""
    NEW = "NEW"
    WAITING_CONSULTANT = "WAITING_CONSULTANT"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


class AssignmentStatus(str, Enum):
    """Assignment status enum."""
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REASSIGNED = "REASSIGNED"


class CaseBase(BaseModel):
    """Base case schema."""
    title: str = Field(..., min_length=1, max_length=500)
    description: str
    budget_min: float = Field(..., alias="budgetMin", ge=0)
    budget_max: float = Field(..., alias="budgetMax", ge=0)


class CaseCreate(CaseBase):
    """Schema for creating a case."""
    client_email: Optional[str] = Field(None, alias="clientEmail")


class CaseResponse(CaseBase):
    """Schema for case response."""
    id: str
    client_id: str = Field(alias="clientId")
    client_email: Optional[str] = Field(None, alias="clientEmail")
    status: CaseStatus
    is_review_required: bool = Field(alias="isReviewRequired")
    use_email_delivery: bool = Field(alias="useEmailDelivery")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class CaseListResponse(BaseModel):
    """Schema for paginated case list."""
    cases: List[CaseResponse]
    total: int
    page: int
    per_page: int = Field(alias="perPage")
    
    class Config:
        populate_by_name = True


class CaseAssignmentResponse(BaseModel):
    """Schema for case assignment response."""
    id: str
    case_id: str = Field(alias="caseId")
    consultant_id: str = Field(alias="consultantId")
    status: AssignmentStatus
    assigned_at: datetime = Field(alias="assignedAt")
    responded_at: Optional[datetime] = Field(None, alias="respondedAt")
    offer_expires_at: Optional[datetime] = Field(None, alias="offerExpiresAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class CaseWithAssignment(CaseResponse):
    """Case with assignment info for consultant."""
    assignment: Optional[CaseAssignmentResponse] = None


class AssignConsultantRequest(BaseModel):
    """Schema for assigning consultant to case."""
    consultant_id: str = Field(alias="consultantId")
    
    class Config:
        populate_by_name = True


class CaseStatusUpdate(BaseModel):
    """Schema for updating case status."""
    status: CaseStatus
