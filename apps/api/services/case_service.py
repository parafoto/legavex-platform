"""Case business logic service."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from prisma import Prisma

from ..config import settings
from ..schemas import CaseStatus, AssignmentStatus, DocumentStatus
from .audit_service import AuditService
from .email_service import EmailService

logger = logging.getLogger(__name__)


class CaseService:
    """Service for case-related business logic."""
    
    def __init__(self, db: Prisma):
        """Initialize case service.
        
        Args:
            db: Prisma database client
        """
        self.db = db
        self.audit = AuditService(db)
        self.email = EmailService(db)
    
    async def get_consultant_cases(
        self,
        consultant_id: str,
        status_filter: Optional[List[CaseStatus]] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Tuple[list, int]:
        """Get cases assigned to a consultant.
        
        Args:
            consultant_id: ID of the consultant
            status_filter: Optional list of case statuses to filter by
            page: Page number (1-based)
            per_page: Items per page
            
        Returns:
            Tuple of (cases list, total count)
        """
        # Build where clause for assignments
        assignment_where = {
            "consultantId": consultant_id,
            "status": {"in": ["OFFERED", "ACCEPTED"]},
        }
        
        # Get case IDs from assignments
        assignments = await self.db.caseassignment.find_many(
            where=assignment_where,
            include={"case": True},
        )
        
        case_ids = [a.caseId for a in assignments]
        
        if not case_ids:
            return [], 0
        
        # Build case filter
        case_where = {"id": {"in": case_ids}}
        if status_filter:
            case_where["status"] = {"in": [s.value for s in status_filter]}
        
        # Get total count
        total = await self.db.case.count(where=case_where)
        
        # Get paginated cases
        cases = await self.db.case.find_many(
            where=case_where,
            include={
                "assignments": {
                    "where": {"consultantId": consultant_id}
                }
            },
            order={"updatedAt": "desc"},
            skip=(page - 1) * per_page,
            take=per_page,
        )
        
        return cases, total
    
    async def get_case_details(
        self,
        case_id: str,
        user_id: str,
        user_role: str,
    ) -> Optional[dict]:
        """Get case details with access control.
        
        Args:
            case_id: ID of the case
            user_id: ID of the requesting user
            user_role: Role of the requesting user
            
        Returns:
            Case details or None if not found/not authorized
        """
        case = await self.db.case.find_unique(
            where={"id": case_id},
            include={
                "assignments": True,
                "documents": True,
                "client": True,
            }
        )
        
        if not case:
            return None
        
        # Check access
        if user_role == "CONSULTANT":
            # Consultant can only see their assigned cases
            has_assignment = any(
                a.consultantId == user_id and a.status in ["OFFERED", "ACCEPTED"]
                for a in case.assignments
            )
            if not has_assignment:
                return None
        
        return case
    
    async def accept_case(
        self,
        case_id: str,
        consultant_id: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Accept a case assignment.
        
        Args:
            case_id: ID of the case
            consultant_id: ID of the consultant
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Find the assignment
        assignment = await self.db.caseassignment.find_first(
            where={
                "caseId": case_id,
                "consultantId": consultant_id,
                "status": "OFFERED",
            }
        )
        
        if not assignment:
            return False, "Assignment not found or already responded"
        
        # Check if offer has expired
        if assignment.offerExpiresAt and assignment.offerExpiresAt < datetime.utcnow():
            return False, "Offer has expired"
        
        # Update assignment status
        await self.db.caseassignment.update(
            where={"id": assignment.id},
            data={
                "status": "ACCEPTED",
                "respondedAt": datetime.utcnow(),
            }
        )
        
        # Update case status
        await self.db.case.update(
            where={"id": case_id},
            data={"status": "IN_PROGRESS"}
        )
        
        # Decline other offers for this case
        await self.db.caseassignment.update_many(
            where={
                "caseId": case_id,
                "status": "OFFERED",
                "id": {"not": assignment.id},
            },
            data={"status": "REASSIGNED"}
        )
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_ACCEPT,
            entity_type=AuditService.ENTITY_ASSIGNMENT,
            entity_id=assignment.id,
            user_id=consultant_id,
            old_value={"status": "OFFERED"},
            new_value={"status": "ACCEPTED"},
            ip_address=ip_address,
        )
        
        logger.info(
            "Consultant %s accepted case %s",
            consultant_id,
            case_id
        )
        
        return True, "Case accepted successfully"
    
    async def decline_case(
        self,
        case_id: str,
        consultant_id: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Decline a case assignment.
        
        Args:
            case_id: ID of the case
            consultant_id: ID of the consultant
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Find the assignment
        assignment = await self.db.caseassignment.find_first(
            where={
                "caseId": case_id,
                "consultantId": consultant_id,
                "status": "OFFERED",
            }
        )
        
        if not assignment:
            return False, "Assignment not found or already responded"
        
        # Update assignment status
        await self.db.caseassignment.update(
            where={"id": assignment.id},
            data={
                "status": "DECLINED",
                "respondedAt": datetime.utcnow(),
            }
        )
        
        # Check if all consultants declined
        remaining_offers = await self.db.caseassignment.count(
            where={
                "caseId": case_id,
                "status": "OFFERED",
            }
        )
        
        if remaining_offers == 0:
            # Escalate case if no one accepted
            accepted = await self.db.caseassignment.count(
                where={
                    "caseId": case_id,
                    "status": "ACCEPTED",
                }
            )
            
            if accepted == 0:
                await self.db.case.update(
                    where={"id": case_id},
                    data={"status": "ESCALATED"}
                )
                logger.warning("Case %s escalated - all consultants declined", case_id)
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_DECLINE,
            entity_type=AuditService.ENTITY_ASSIGNMENT,
            entity_id=assignment.id,
            user_id=consultant_id,
            old_value={"status": "OFFERED"},
            new_value={"status": "DECLINED"},
            ip_address=ip_address,
        )
        
        logger.info(
            "Consultant %s declined case %s",
            consultant_id,
            case_id
        )
        
        return True, "Case declined"
    
    async def assign_consultant(
        self,
        case_id: str,
        consultant_id: str,
        admin_id: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Assign a consultant to a case (admin action).
        
        Args:
            case_id: ID of the case
            consultant_id: ID of the consultant to assign
            admin_id: ID of the admin performing the action
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Verify case exists
        case = await self.db.case.find_unique(where={"id": case_id})
        if not case:
            return False, "Case not found"
        
        # Verify consultant exists and is active
        consultant = await self.db.user.find_unique(
            where={"id": consultant_id},
            include={"consultantProfile": True}
        )
        
        if not consultant or consultant.role != "CONSULTANT":
            return False, "Consultant not found"
        
        if not consultant.consultantProfile or not consultant.consultantProfile.isActive:
            return False, "Consultant is not active"
        
        # Check if consultant already has max cases
        active_cases = await self.db.caseassignment.count(
            where={
                "consultantId": consultant_id,
                "status": "ACCEPTED",
            }
        )
        
        if active_cases >= consultant.consultantProfile.maxParallelCases:
            return False, f"Consultant already has {active_cases} active cases (max: {consultant.consultantProfile.maxParallelCases})"
        
        # Check for existing assignment
        existing = await self.db.caseassignment.find_first(
            where={
                "caseId": case_id,
                "consultantId": consultant_id,
            }
        )
        
        if existing:
            return False, "Consultant already assigned to this case"
        
        # Get settings for offer timeout
        settings_record = await self.db.globalsettings.find_first()
        timeout_hours = settings_record.offerTimeoutHours if settings_record else 24
        
        # Create assignment
        expires_at = datetime.utcnow() + timedelta(hours=timeout_hours)
        
        assignment = await self.db.caseassignment.create(
            data={
                "caseId": case_id,
                "consultantId": consultant_id,
                "status": "OFFERED",
                "offerExpiresAt": expires_at,
            }
        )
        
        # Update case status if it was NEW
        if case.status == "NEW":
            await self.db.case.update(
                where={"id": case_id},
                data={"status": "WAITING_CONSULTANT"}
            )
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_ASSIGN,
            entity_type=AuditService.ENTITY_ASSIGNMENT,
            entity_id=assignment.id,
            user_id=admin_id,
            new_value={
                "caseId": case_id,
                "consultantId": consultant_id,
                "expiresAt": expires_at.isoformat(),
            },
            ip_address=ip_address,
        )
        
        logger.info(
            "Admin %s assigned consultant %s to case %s",
            admin_id,
            consultant_id,
            case_id
        )
        
        return True, "Consultant assigned successfully"
    
    async def submit_document(
        self,
        case_id: str,
        consultant_id: str,
        document_id: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Submit a document for review or delivery.
        
        Follows the business logic:
        - If is_review_required: mark as PENDING_REVIEW
        - If not review_required and use_email_delivery: send via email
        - If not review_required and not email_delivery: mark as APPROVED (visible to client)
        
        Args:
            case_id: ID of the case
            consultant_id: ID of the consultant
            document_id: ID of the document
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Get case with settings
        case = await self.db.case.find_unique(
            where={"id": case_id},
            include={"client": True}
        )
        
        if not case:
            return False, "Case not found"
        
        # Get document
        document = await self.db.casedocument.find_unique(
            where={"id": document_id}
        )
        
        if not document or document.caseId != case_id:
            return False, "Document not found"
        
        if document.consultantId != consultant_id:
            return False, "Not authorized to submit this document"
        
        # Determine next status based on settings
        if case.isReviewRequired:
            # Send to senior review
            new_status = DocumentStatus.PENDING_REVIEW.value
            message = "Document submitted for senior review"
            
        elif case.useEmailDelivery:
            # Send directly via email
            new_status = DocumentStatus.APPROVED.value
            
            # Send email
            client_email = case.clientEmail or (case.client.email if case.client else None)
            if client_email:
                await self.email.send_document_to_client(
                    case_id=case_id,
                    recipient_email=client_email,
                    file_path=document.fileUrl,
                    case_title=case.title,
                )
                message = "Document sent to client via email"
            else:
                return False, "Client email not found"
        else:
            # Make available in platform
            new_status = DocumentStatus.APPROVED.value
            message = "Document approved and available to client"
        
        # Update document status
        await self.db.casedocument.update(
            where={"id": document_id},
            data={
                "status": new_status,
                "type": "FINAL",
            }
        )
        
        # Update case status if document is final
        if new_status == DocumentStatus.APPROVED.value:
            await self.db.case.update(
                where={"id": case_id},
                data={"status": "DONE"}
            )
        elif new_status == DocumentStatus.PENDING_REVIEW.value:
            await self.db.case.update(
                where={"id": case_id},
                data={"status": "REVIEW"}
            )
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_UPLOAD_DOCUMENT,
            entity_type=AuditService.ENTITY_DOCUMENT,
            entity_id=document_id,
            user_id=consultant_id,
            new_value={"status": new_status},
            ip_address=ip_address,
        )
        
        return True, message
    
    async def approve_document(
        self,
        case_id: str,
        document_id: str,
        admin_id: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Approve a document (admin/senior action).
        
        After approval:
        - If use_email_delivery: send via email
        - Otherwise: make available in platform
        
        Args:
            case_id: ID of the case
            document_id: ID of the document
            admin_id: ID of the admin
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Get case
        case = await self.db.case.find_unique(
            where={"id": case_id},
            include={"client": True}
        )
        
        if not case:
            return False, "Case not found"
        
        # Get document
        document = await self.db.casedocument.find_unique(
            where={"id": document_id}
        )
        
        if not document or document.caseId != case_id:
            return False, "Document not found"
        
        if document.status != "PENDING_REVIEW":
            return False, f"Document is not pending review (status: {document.status})"
        
        # Approve document
        await self.db.casedocument.update(
            where={"id": document_id},
            data={
                "status": "APPROVED",
                "reviewedAt": datetime.utcnow(),
            }
        )
        
        # Send via email if configured
        if case.useEmailDelivery:
            client_email = case.clientEmail or (case.client.email if case.client else None)
            if client_email:
                await self.email.send_document_to_client(
                    case_id=case_id,
                    recipient_email=client_email,
                    file_path=document.fileUrl,
                    case_title=case.title,
                )
                message = "Document approved and sent to client via email"
            else:
                message = "Document approved but client email not found"
        else:
            message = "Document approved and available to client"
        
        # Update case status
        await self.db.case.update(
            where={"id": case_id},
            data={"status": "DONE"}
        )
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_APPROVE_DOCUMENT,
            entity_type=AuditService.ENTITY_DOCUMENT,
            entity_id=document_id,
            user_id=admin_id,
            old_value={"status": "PENDING_REVIEW"},
            new_value={"status": "APPROVED"},
            ip_address=ip_address,
        )
        
        return True, message
    
    async def reject_document(
        self,
        case_id: str,
        document_id: str,
        admin_id: str,
        comment: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Reject a document and send back for revision.
        
        Args:
            case_id: ID of the case
            document_id: ID of the document
            admin_id: ID of the admin
            comment: Review comment for consultant
            ip_address: Client IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        # Get document
        document = await self.db.casedocument.find_unique(
            where={"id": document_id}
        )
        
        if not document or document.caseId != case_id:
            return False, "Document not found"
        
        if document.status != "PENDING_REVIEW":
            return False, f"Document is not pending review (status: {document.status})"
        
        # Reject document
        await self.db.casedocument.update(
            where={"id": document_id},
            data={
                "status": "REJECTED",
                "reviewComment": comment,
                "reviewedAt": datetime.utcnow(),
            }
        )
        
        # Update case status back to IN_PROGRESS
        await self.db.case.update(
            where={"id": case_id},
            data={"status": "IN_PROGRESS"}
        )
        
        # Log audit
        await self.audit.log(
            action=AuditService.ACTION_REJECT_DOCUMENT,
            entity_type=AuditService.ENTITY_DOCUMENT,
            entity_id=document_id,
            user_id=admin_id,
            old_value={"status": "PENDING_REVIEW"},
            new_value={"status": "REJECTED", "comment": comment},
            ip_address=ip_address,
        )
        
        return True, "Document returned for revision"
