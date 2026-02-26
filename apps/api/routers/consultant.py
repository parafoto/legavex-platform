"""Consultant routes."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from prisma import Prisma

from ..models import get_prisma_client
from ..schemas import (
    CaseStatus,
    CaseResponse,
    CaseListResponse,
    CaseWithAssignment,
    CaseAssignmentResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
    DocumentCreate,
    DocumentResponse,
    DocumentListResponse,
    PayoutResponse,
    PayoutListResponse,
    Role,
)
from ..middleware import require_consultant, TokenData, verify_case_access
from ..dependencies import get_case_service, get_client_ip
from ..services import CaseService, AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consultant", tags=["Consultant"])


@router.get(
    "/cases",
    response_model=CaseListResponse,
    summary="Get consultant's cases",
)
async def get_cases(
    status_filter: Optional[List[CaseStatus]] = Query(
        None, 
        alias="status",
        description="Filter by case status"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100, alias="perPage"),
    current_user: TokenData = Depends(require_consultant),
):
    """Get list of cases assigned to the consultant.
    
    Args:
        status_filter: Optional status filter
        page: Page number
        per_page: Items per page
        
    Returns:
        Paginated list of cases
    """
    case_service = await get_case_service()
    cases, total = await case_service.get_consultant_cases(
        consultant_id=current_user.user_id,
        status_filter=status_filter,
        page=page,
        per_page=per_page,
    )
    
    return CaseListResponse(
        cases=[CaseResponse(
            id=c.id,
            clientId=c.clientId,
            clientEmail=c.clientEmail,
            title=c.title,
            description=c.description,
            budgetMin=c.budgetMin,
            budgetMax=c.budgetMax,
            status=CaseStatus(c.status),
            isReviewRequired=c.isReviewRequired,
            useEmailDelivery=c.useEmailDelivery,
            createdAt=c.createdAt,
            updatedAt=c.updatedAt,
        ) for c in cases],
        total=total,
        page=page,
        perPage=per_page,
    )


@router.get(
    "/cases/{case_id}",
    response_model=CaseWithAssignment,
    summary="Get case details",
)
async def get_case(
    case_id: str,
    current_user: TokenData = Depends(require_consultant),
):
    """Get detailed information about a specific case.
    
    Args:
        case_id: ID of the case
        
    Returns:
        Case details with assignment info
    """
    case_service = await get_case_service()
    case = await case_service.get_case_details(
        case_id=case_id,
        user_id=current_user.user_id,
        user_role=current_user.role.value,
    )
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found or access denied",
        )
    
    # Find consultant's assignment
    assignment = None
    for a in case.assignments:
        if a.consultantId == current_user.user_id:
            assignment = CaseAssignmentResponse(
                id=a.id,
                caseId=a.caseId,
                consultantId=a.consultantId,
                status=a.status,
                assignedAt=a.assignedAt,
                respondedAt=a.respondedAt,
                offerExpiresAt=a.offerExpiresAt,
            )
            break
    
    return CaseWithAssignment(
        id=case.id,
        clientId=case.clientId,
        clientEmail=case.clientEmail,
        title=case.title,
        description=case.description,
        budgetMin=case.budgetMin,
        budgetMax=case.budgetMax,
        status=CaseStatus(case.status),
        isReviewRequired=case.isReviewRequired,
        useEmailDelivery=case.useEmailDelivery,
        createdAt=case.createdAt,
        updatedAt=case.updatedAt,
        assignment=assignment,
    )


@router.post(
    "/cases/{case_id}/accept",
    summary="Accept a case",
)
async def accept_case(
    case_id: str,
    request: Request,
    current_user: TokenData = Depends(require_consultant),
):
    """Accept an offered case.
    
    Args:
        case_id: ID of the case to accept
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.accept_case(
        case_id=case_id,
        consultant_id=current_user.user_id,
        ip_address=get_client_ip(request),
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    
    return {"status": "success", "message": message}


@router.post(
    "/cases/{case_id}/decline",
    summary="Decline a case",
)
async def decline_case(
    case_id: str,
    request: Request,
    current_user: TokenData = Depends(require_consultant),
):
    """Decline an offered case.
    
    Args:
        case_id: ID of the case to decline
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.decline_case(
        case_id=case_id,
        consultant_id=current_user.user_id,
        ip_address=get_client_ip(request),
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    
    return {"status": "success", "message": message}


@router.get(
    "/cases/{case_id}/messages",
    response_model=MessageListResponse,
    summary="Get case messages",
)
async def get_messages(
    case_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100, alias="perPage"),
    current_user: TokenData = Depends(require_consultant),
):
    """Get chat messages for a case.
    
    Args:
        case_id: ID of the case
        page: Page number
        per_page: Items per page
        
    Returns:
        Paginated list of messages
    """
    # Verify access
    await verify_case_access(case_id, current_user)
    
    db = await get_prisma_client()
    
    # Get total count
    total = await db.casemessage.count(
        where={"caseId": case_id}
    )
    
    # Get messages with sender info
    messages = await db.casemessage.find_many(
        where={"caseId": case_id},
        include={"sender": True},
        order={"createdAt": "asc"},
        skip=(page - 1) * per_page,
        take=per_page,
    )
    
    return MessageListResponse(
        messages=[MessageResponse(
            id=m.id,
            caseId=m.caseId,
            senderId=m.senderId,
            senderRole=Role(m.senderRole),
            messageType=m.messageType,
            body=m.body,
            fileUrl=m.fileUrl,
            createdAt=m.createdAt,
            senderName=m.sender.name if m.sender else None,
        ) for m in messages],
        total=total,
        page=page,
        perPage=per_page,
    )


@router.post(
    "/cases/{case_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message",
)
async def send_message(
    case_id: str,
    message_data: MessageCreate,
    request: Request,
    current_user: TokenData = Depends(require_consultant),
):
    """Send a message in case chat.
    
    Args:
        case_id: ID of the case
        message_data: Message content
        
    Returns:
        Created message
    """
    # Verify access
    await verify_case_access(case_id, current_user)
    
    db = await get_prisma_client()
    
    # Create message
    message = await db.casemessage.create(
        data={
            "caseId": case_id,
            "senderId": current_user.user_id,
            "senderRole": current_user.role.value,
            "messageType": message_data.message_type.value,
            "body": message_data.body,
            "fileUrl": message_data.file_url,
        },
        include={"sender": True},
    )
    
    # Log audit
    audit = AuditService(db)
    await audit.log(
        action=AuditService.ACTION_SEND_MESSAGE,
        entity_type=AuditService.ENTITY_MESSAGE,
        entity_id=message.id,
        user_id=current_user.user_id,
        new_value={"caseId": case_id, "messageType": message_data.message_type.value},
        ip_address=get_client_ip(request),
    )
    
    return MessageResponse(
        id=message.id,
        caseId=message.caseId,
        senderId=message.senderId,
        senderRole=Role(message.senderRole),
        messageType=message.messageType,
        body=message.body,
        fileUrl=message.fileUrl,
        createdAt=message.createdAt,
        senderName=message.sender.name if message.sender else None,
    )


@router.get(
    "/cases/{case_id}/documents",
    response_model=DocumentListResponse,
    summary="Get case documents",
)
async def get_documents(
    case_id: str,
    current_user: TokenData = Depends(require_consultant),
):
    """Get documents for a case.
    
    Args:
        case_id: ID of the case
        
    Returns:
        List of documents
    """
    # Verify access
    await verify_case_access(case_id, current_user)
    
    db = await get_prisma_client()
    
    documents = await db.casedocument.find_many(
        where={"caseId": case_id},
        order={"uploadedAt": "desc"},
    )
    
    return DocumentListResponse(
        documents=[DocumentResponse(
            id=d.id,
            caseId=d.caseId,
            consultantId=d.consultantId,
            type=d.type,
            status=d.status,
            fileName=d.fileName,
            fileUrl=d.fileUrl,
            fileSize=d.fileSize,
            reviewComment=d.reviewComment,
            uploadedAt=d.uploadedAt,
            reviewedAt=d.reviewedAt,
        ) for d in documents],
        total=len(documents),
    )


@router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
async def upload_document(
    case_id: str,
    document_data: DocumentCreate,
    request: Request,
    current_user: TokenData = Depends(require_consultant),
):
    """Upload a document to a case.
    
    Args:
        case_id: ID of the case
        document_data: Document metadata
        
    Returns:
        Created document
    """
    # Verify access
    await verify_case_access(case_id, current_user)
    
    db = await get_prisma_client()
    
    # Create document
    document = await db.casedocument.create(
        data={
            "caseId": case_id,
            "consultantId": current_user.user_id,
            "type": document_data.type.value,
            "status": "DRAFT",
            "fileName": document_data.file_name,
            "fileUrl": document_data.file_url,
            "fileSize": document_data.file_size,
        }
    )
    
    # Log audit
    audit = AuditService(db)
    await audit.log(
        action=AuditService.ACTION_UPLOAD_DOCUMENT,
        entity_type=AuditService.ENTITY_DOCUMENT,
        entity_id=document.id,
        user_id=current_user.user_id,
        new_value={"caseId": case_id, "fileName": document_data.file_name},
        ip_address=get_client_ip(request),
    )
    
    return DocumentResponse(
        id=document.id,
        caseId=document.caseId,
        consultantId=document.consultantId,
        type=document.type,
        status=document.status,
        fileName=document.fileName,
        fileUrl=document.fileUrl,
        fileSize=document.fileSize,
        reviewComment=document.reviewComment,
        uploadedAt=document.uploadedAt,
        reviewedAt=document.reviewedAt,
    )


@router.post(
    "/cases/{case_id}/documents/{document_id}/submit",
    summary="Submit document for review or delivery",
)
async def submit_document(
    case_id: str,
    document_id: str,
    request: Request,
    current_user: TokenData = Depends(require_consultant),
):
    """Submit a document for review or delivery to client.
    
    Based on case settings:
    - If review required: sends to senior for approval
    - If email delivery: sends directly to client email
    - Otherwise: makes available in platform
    
    Args:
        case_id: ID of the case
        document_id: ID of the document
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.submit_document(
        case_id=case_id,
        consultant_id=current_user.user_id,
        document_id=document_id,
        ip_address=get_client_ip(request),
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    
    return {"status": "success", "message": message}


@router.get(
    "/payouts",
    response_model=PayoutListResponse,
    summary="Get consultant's payouts",
)
async def get_payouts(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: TokenData = Depends(require_consultant),
):
    """Get list of payouts for the consultant.
    
    Args:
        status_filter: Optional filter by status (PLANNED/PAID)
        
    Returns:
        List of payouts with totals
    """
    db = await get_prisma_client()
    
    where = {"consultantId": current_user.user_id}
    if status_filter:
        where["status"] = status_filter
    
    payouts = await db.payout.find_many(
        where=where,
        order={"createdAt": "desc"},
    )
    
    total_amount = sum(p.amountRub for p in payouts)
    
    return PayoutListResponse(
        payouts=[PayoutResponse(
            id=p.id,
            consultantId=p.consultantId,
            caseId=p.caseId,
            amountRub=p.amountRub,
            status=p.status,
            description=p.description,
            dueDate=p.dueDate,
            paidAt=p.paidAt,
            createdAt=p.createdAt,
        ) for p in payouts],
        total=len(payouts),
        totalAmount=total_amount,
    )
