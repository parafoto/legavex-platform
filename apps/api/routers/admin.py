"""Admin routes."""

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
    AssignConsultantRequest,
    DocumentReviewRequest,
    DocumentResponse,
    PayoutResponse,
    PayoutListResponse,
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
    UserResponse,
    ConsultantWithProfile,
    Role,
)
from ..middleware import require_admin, TokenData
from ..dependencies import get_case_service, get_client_ip
from ..services import CaseService, AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/cases",
    response_model=CaseListResponse,
    summary="Get all cases",
)
async def get_all_cases(
    status_filter: Optional[List[CaseStatus]] = Query(
        None,
        alias="status",
        description="Filter by case status"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100, alias="perPage"),
    current_user: TokenData = Depends(require_admin),
):
    """Get all cases in the system.
    
    Args:
        status_filter: Optional status filter
        page: Page number
        per_page: Items per page
        
    Returns:
        Paginated list of all cases
    """
    db = await get_prisma_client()
    
    where = {}
    if status_filter:
        where["status"] = {"in": [s.value for s in status_filter]}
    
    total = await db.case.count(where=where)
    
    cases = await db.case.find_many(
        where=where,
        include={
            "assignments": {
                "include": {"consultant": True}
            },
            "client": True,
        },
        order={"updatedAt": "desc"},
        skip=(page - 1) * per_page,
        take=per_page,
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
    summary="Get case details",
)
async def get_case_details(
    case_id: str,
    current_user: TokenData = Depends(require_admin),
):
    """Get detailed information about a case.
    
    Args:
        case_id: ID of the case
        
    Returns:
        Full case details with assignments, documents, etc.
    """
    db = await get_prisma_client()
    
    case = await db.case.find_unique(
        where={"id": case_id},
        include={
            "assignments": {
                "include": {"consultant": True}
            },
            "documents": True,
            "client": True,
            "messages": {
                "take": 10,
                "order": {"createdAt": "desc"},
            },
        }
    )
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )
    
    return case


@router.post(
    "/cases/{case_id}/assign",
    summary="Assign consultant to case",
)
async def assign_consultant(
    case_id: str,
    data: AssignConsultantRequest,
    request: Request,
    current_user: TokenData = Depends(require_admin),
):
    """Assign a consultant to a case.
    
    Args:
        case_id: ID of the case
        data: Consultant ID to assign
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.assign_consultant(
        case_id=case_id,
        consultant_id=data.consultant_id,
        admin_id=current_user.user_id,
        ip_address=get_client_ip(request),
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    
    return {"status": "success", "message": message}


@router.post(
    "/cases/{case_id}/documents/{document_id}/approve",
    summary="Approve document",
)
async def approve_document(
    case_id: str,
    document_id: str,
    request: Request,
    current_user: TokenData = Depends(require_admin),
):
    """Approve a document for delivery to client.
    
    After approval, if email delivery is enabled, document is sent to client.
    
    Args:
        case_id: ID of the case
        document_id: ID of the document
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.approve_document(
        case_id=case_id,
        document_id=document_id,
        admin_id=current_user.user_id,
        ip_address=get_client_ip(request),
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    
    return {"status": "success", "message": message}


@router.post(
    "/cases/{case_id}/documents/{document_id}/reject",
    summary="Reject document",
)
async def reject_document(
    case_id: str,
    document_id: str,
    data: DocumentReviewRequest,
    request: Request,
    current_user: TokenData = Depends(require_admin),
):
    """Reject a document and return for revision.
    
    Args:
        case_id: ID of the case
        document_id: ID of the document
        data: Review comment
        
    Returns:
        Success message
    """
    case_service = await get_case_service()
    success, message = await case_service.reject_document(
        case_id=case_id,
        document_id=document_id,
        admin_id=current_user.user_id,
        comment=data.comment,
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
    summary="Get all payouts",
)
async def get_all_payouts(
    status_filter: Optional[str] = Query(None, alias="status"),
    consultant_id: Optional[str] = Query(None, alias="consultantId"),
    current_user: TokenData = Depends(require_admin),
):
    """Get all payouts in the system.
    
    Args:
        status_filter: Optional filter by status
        consultant_id: Optional filter by consultant
        
    Returns:
        List of payouts with totals
    """
    db = await get_prisma_client()
    
    where = {}
    if status_filter:
        where["status"] = status_filter
    if consultant_id:
        where["consultantId"] = consultant_id
    
    payouts = await db.payout.find_many(
        where=where,
        include={
            "consultant": True,
            "case": True,
        },
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


@router.get(
    "/settings",
    response_model=GlobalSettingsResponse,
    summary="Get global settings",
)
async def get_settings(
    current_user: TokenData = Depends(require_admin),
):
    """Get global platform settings.
    
    Returns:
        Current global settings
    """
    db = await get_prisma_client()
    
    settings = await db.globalsettings.find_first()
    
    if not settings:
        # Create default settings
        settings = await db.globalsettings.create(
            data={
                "isReviewRequired": True,
                "useEmailDelivery": False,
                "offerTimeoutHours": 24,
            }
        )
    
    return GlobalSettingsResponse(
        id=settings.id,
        isReviewRequired=settings.isReviewRequired,
        useEmailDelivery=settings.useEmailDelivery,
        offerTimeoutHours=settings.offerTimeoutHours,
        updatedAt=settings.updatedAt,
    )


@router.patch(
    "/settings",
    response_model=GlobalSettingsResponse,
    summary="Update global settings",
)
async def update_settings(
    data: GlobalSettingsUpdate,
    request: Request,
    current_user: TokenData = Depends(require_admin),
):
    """Update global platform settings.
    
    Toggle switches:
    - isReviewRequired: Enable/disable senior review before client delivery
    - useEmailDelivery: Enable/disable email delivery of documents
    
    Args:
        data: Settings to update
        
    Returns:
        Updated settings
    """
    db = await get_prisma_client()
    
    # Get current settings
    current_settings = await db.globalsettings.find_first()
    
    if not current_settings:
        current_settings = await db.globalsettings.create(
            data={
                "isReviewRequired": True,
                "useEmailDelivery": False,
                "offerTimeoutHours": 24,
            }
        )
    
    # Prepare update data
    update_data = {}
    old_values = {}
    
    if data.is_review_required is not None:
        update_data["isReviewRequired"] = data.is_review_required
        old_values["isReviewRequired"] = current_settings.isReviewRequired
    
    if data.use_email_delivery is not None:
        update_data["useEmailDelivery"] = data.use_email_delivery
        old_values["useEmailDelivery"] = current_settings.useEmailDelivery
    
    if data.offer_timeout_hours is not None:
        update_data["offerTimeoutHours"] = data.offer_timeout_hours
        old_values["offerTimeoutHours"] = current_settings.offerTimeoutHours
    
    if not update_data:
        return GlobalSettingsResponse(
            id=current_settings.id,
            isReviewRequired=current_settings.isReviewRequired,
            useEmailDelivery=current_settings.useEmailDelivery,
            offerTimeoutHours=current_settings.offerTimeoutHours,
            updatedAt=current_settings.updatedAt,
        )
    
    # Update settings
    settings = await db.globalsettings.update(
        where={"id": current_settings.id},
        data=update_data,
    )
    
    # Log audit
    audit = AuditService(db)
    await audit.log(
        action=AuditService.ACTION_UPDATE_SETTINGS,
        entity_type=AuditService.ENTITY_SETTINGS,
        entity_id=settings.id,
        user_id=current_user.user_id,
        old_value=old_values,
        new_value=update_data,
        ip_address=get_client_ip(request),
    )
    
    logger.info(
        "Admin %s updated settings: %s",
        current_user.user_id,
        update_data
    )
    
    return GlobalSettingsResponse(
        id=settings.id,
        isReviewRequired=settings.isReviewRequired,
        useEmailDelivery=settings.useEmailDelivery,
        offerTimeoutHours=settings.offerTimeoutHours,
        updatedAt=settings.updatedAt,
    )


@router.get(
    "/consultants",
    summary="Get all consultants",
)
async def get_consultants(
    active_only: bool = Query(True, alias="activeOnly"),
    current_user: TokenData = Depends(require_admin),
):
    """Get list of all consultants.
    
    Args:
        active_only: If True, only return active consultants
        
    Returns:
        List of consultants with their profiles
    """
    db = await get_prisma_client()
    
    where = {"role": "CONSULTANT"}
    if active_only:
        where["isActive"] = True
    
    consultants = await db.user.find_many(
        where=where,
        include={"consultantProfile": True},
        order={"name": "asc"},
    )
    
    return {
        "consultants": consultants,
        "total": len(consultants),
    }
