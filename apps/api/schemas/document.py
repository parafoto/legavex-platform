"""Document-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Document type enum."""
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    ATTACHMENT = "ATTACHMENT"


class DocumentStatus(str, Enum):
    """Document status enum."""
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocumentCreate(BaseModel):
    """Schema for creating a document."""
    type: DocumentType = DocumentType.DRAFT
    file_name: str = Field(..., alias="fileName")
    file_url: str = Field(..., alias="fileUrl")
    file_size: Optional[int] = Field(None, alias="fileSize")
    
    class Config:
        populate_by_name = True


class DocumentResponse(BaseModel):
    """Schema for document response."""
    id: str
    case_id: str = Field(alias="caseId")
    consultant_id: str = Field(alias="consultantId")
    type: DocumentType
    status: DocumentStatus
    file_name: str = Field(alias="fileName")
    file_url: str = Field(alias="fileUrl")
    file_size: Optional[int] = Field(None, alias="fileSize")
    review_comment: Optional[str] = Field(None, alias="reviewComment")
    uploaded_at: datetime = Field(alias="uploadedAt")
    reviewed_at: Optional[datetime] = Field(None, alias="reviewedAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class DocumentListResponse(BaseModel):
    """Schema for document list."""
    documents: List[DocumentResponse]
    total: int


class DocumentReviewRequest(BaseModel):
    """Schema for reviewing a document."""
    comment: Optional[str] = None


class PayoutStatus(str, Enum):
    """Payout status enum."""
    PLANNED = "PLANNED"
    PAID = "PAID"


class PayoutResponse(BaseModel):
    """Schema for payout response."""
    id: str
    consultant_id: str = Field(alias="consultantId")
    case_id: str = Field(alias="caseId")
    amount_rub: float = Field(alias="amountRub")
    status: PayoutStatus
    description: Optional[str] = None
    due_date: Optional[datetime] = Field(None, alias="dueDate")
    paid_at: Optional[datetime] = Field(None, alias="paidAt")
    created_at: datetime = Field(alias="createdAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class PayoutListResponse(BaseModel):
    """Schema for payout list."""
    payouts: List[PayoutResponse]
    total: int
    total_amount: float = Field(alias="totalAmount")
    
    class Config:
        populate_by_name = True


class GlobalSettingsResponse(BaseModel):
    """Schema for global settings response."""
    id: str
    is_review_required: bool = Field(alias="isReviewRequired")
    use_email_delivery: bool = Field(alias="useEmailDelivery")
    offer_timeout_hours: int = Field(alias="offerTimeoutHours")
    updated_at: datetime = Field(alias="updatedAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class GlobalSettingsUpdate(BaseModel):
    """Schema for updating global settings."""
    is_review_required: Optional[bool] = Field(None, alias="isReviewRequired")
    use_email_delivery: Optional[bool] = Field(None, alias="useEmailDelivery")
    offer_timeout_hours: Optional[int] = Field(None, alias="offerTimeoutHours")
    
    class Config:
        populate_by_name = True
