"""Message-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field

from .user import Role


class MessageType(str, Enum):
    """Message type enum."""
    TEXT = "TEXT"
    FILE = "FILE"
    SYSTEM = "SYSTEM"


class MessageCreate(BaseModel):
    """Schema for creating a message."""
    body: Optional[str] = None
    message_type: MessageType = Field(MessageType.TEXT, alias="messageType")
    file_url: Optional[str] = Field(None, alias="fileUrl")
    
    class Config:
        populate_by_name = True


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: str
    case_id: str = Field(alias="caseId")
    sender_id: str = Field(alias="senderId")
    sender_role: Role = Field(alias="senderRole")
    message_type: MessageType = Field(alias="messageType")
    body: Optional[str] = None
    file_url: Optional[str] = Field(None, alias="fileUrl")
    created_at: datetime = Field(alias="createdAt")
    
    # Optional sender info
    sender_name: Optional[str] = Field(None, alias="senderName")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class MessageListResponse(BaseModel):
    """Schema for paginated message list."""
    messages: List[MessageResponse]
    total: int
    page: int
    per_page: int = Field(alias="perPage")
    
    class Config:
        populate_by_name = True
