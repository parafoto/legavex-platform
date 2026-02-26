"""Pydantic schemas module."""

from .user import (
    Role,
    UserBase,
    UserCreate,
    UserLogin,
    UserResponse,
    UserWithToken,
    ConsultantProfileBase,
    ConsultantProfileResponse,
    ConsultantWithProfile,
)
from .case import (
    CaseStatus,
    AssignmentStatus,
    CaseBase,
    CaseCreate,
    CaseResponse,
    CaseListResponse,
    CaseAssignmentResponse,
    CaseWithAssignment,
    AssignConsultantRequest,
    CaseStatusUpdate,
)
from .message import (
    MessageType,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
)
from .document import (
    DocumentType,
    DocumentStatus,
    DocumentCreate,
    DocumentResponse,
    DocumentListResponse,
    DocumentReviewRequest,
    PayoutStatus,
    PayoutResponse,
    PayoutListResponse,
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
)

__all__ = [
    # User
    "Role",
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "UserWithToken",
    "ConsultantProfileBase",
    "ConsultantProfileResponse",
    "ConsultantWithProfile",
    # Case
    "CaseStatus",
    "AssignmentStatus",
    "CaseBase",
    "CaseCreate",
    "CaseResponse",
    "CaseListResponse",
    "CaseAssignmentResponse",
    "CaseWithAssignment",
    "AssignConsultantRequest",
    "CaseStatusUpdate",
    # Message
    "MessageType",
    "MessageCreate",
    "MessageResponse",
    "MessageListResponse",
    # Document
    "DocumentType",
    "DocumentStatus",
    "DocumentCreate",
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentReviewRequest",
    "PayoutStatus",
    "PayoutResponse",
    "PayoutListResponse",
    "GlobalSettingsResponse",
    "GlobalSettingsUpdate",
]
