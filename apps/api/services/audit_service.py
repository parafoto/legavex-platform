"""Audit logging service for tracking user actions."""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from prisma import Prisma

logger = logging.getLogger(__name__)


class AuditService:
    """Service for logging audit events.
    
    Tracks important actions like:
    - Case assignments (assign)
    - Case acceptance/decline (accept, decline)
    - Status changes (change_status)
    - Document uploads (upload_document)
    - Document reviews (approve_document, reject_document)
    - Email sends (send_email)
    - Settings changes (update_settings)
    """
    
    # Action constants
    ACTION_ASSIGN = "assign"
    ACTION_ACCEPT = "accept"
    ACTION_DECLINE = "decline"
    ACTION_CHANGE_STATUS = "change_status"
    ACTION_UPLOAD_DOCUMENT = "upload_document"
    ACTION_APPROVE_DOCUMENT = "approve_document"
    ACTION_REJECT_DOCUMENT = "reject_document"
    ACTION_SEND_EMAIL = "send_email"
    ACTION_UPDATE_SETTINGS = "update_settings"
    ACTION_LOGIN = "login"
    ACTION_CREATE_USER = "create_user"
    ACTION_SEND_MESSAGE = "send_message"
    
    # Entity types
    ENTITY_CASE = "Case"
    ENTITY_DOCUMENT = "CaseDocument"
    ENTITY_USER = "User"
    ENTITY_SETTINGS = "GlobalSettings"
    ENTITY_MESSAGE = "CaseMessage"
    ENTITY_ASSIGNMENT = "CaseAssignment"
    
    def __init__(self, db: Prisma):
        """Initialize audit service.
        
        Args:
            db: Prisma database client
        """
        self.db = db
    
    async def log(
        self,
        action: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        old_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Log an audit event.
        
        Args:
            action: Action performed (e.g., 'assign', 'accept', 'upload_document')
            entity_type: Type of entity affected (e.g., 'Case', 'CaseDocument')
            entity_id: ID of the affected entity
            user_id: ID of the user performing the action
            old_value: Previous value (for updates)
            new_value: New value (for updates)
            ip_address: Client IP address
            user_agent: Client user agent string
        """
        try:
            # Serialize values to JSON if they're not strings
            old_value_str = self._serialize_value(old_value)
            new_value_str = self._serialize_value(new_value)
            
            await self.db.auditlog.create(
                data={
                    "userId": user_id,
                    "action": action,
                    "entityType": entity_type,
                    "entityId": entity_id,
                    "oldValue": old_value_str,
                    "newValue": new_value_str,
                    "ipAddress": ip_address,
                    "userAgent": user_agent,
                }
            )
            
            logger.info(
                "Audit: %s performed %s on %s/%s",
                user_id or "system",
                action,
                entity_type,
                entity_id or "N/A"
            )
            
        except Exception as e:
            # Don't let audit logging failures break the main flow
            logger.error(
                "Failed to log audit event: action=%s, entity=%s/%s, error=%s",
                action,
                entity_type,
                entity_id,
                str(e)
            )
    
    def _serialize_value(self, value: Any) -> Optional[str]:
        """Serialize value to JSON string.
        
        Args:
            value: Value to serialize
            
        Returns:
            JSON string or None
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    
    async def get_logs(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        """Get audit logs with optional filtering.
        
        Args:
            user_id: Filter by user ID
            action: Filter by action
            entity_type: Filter by entity type
            entity_id: Filter by entity ID
            limit: Maximum number of logs to return
            offset: Number of logs to skip
            
        Returns:
            List of audit log records
        """
        where = {}
        if user_id:
            where["userId"] = user_id
        if action:
            where["action"] = action
        if entity_type:
            where["entityType"] = entity_type
        if entity_id:
            where["entityId"] = entity_id
        
        return await self.db.auditlog.find_many(
            where=where,
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
        )
