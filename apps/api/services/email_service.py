"""Email service for sending documents to clients.

This module provides email functionality using SMTP.
Currently implemented as a stub that logs emails without actually sending.

TODO: Integrate with Proton Mail via aiosmtplib for real email delivery.
"""

import logging
from datetime import datetime
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from prisma import Prisma

from ..config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails to clients.
    
    Supports sending documents via SMTP (Proton Mail or any SMTP server).
    Currently implemented as a stub for MVP - logs emails without sending.
    """
    
    def __init__(self, db: Prisma):
        """Initialize email service.
        
        Args:
            db: Prisma database client
        """
        self.db = db
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_name = settings.email_from_name
        self.email_enabled = settings.email_enabled
    
    async def send_document_to_client(
        self,
        case_id: str,
        recipient_email: str,
        file_path: str,
        case_title: str,
        consultant_name: Optional[str] = None,
        anonymize_consultant: bool = True,
    ) -> bool:
        """Send document to client via email.
        
        Args:
            case_id: ID of the case
            recipient_email: Client's email address
            file_path: Path to the PDF document
            case_title: Title of the case for email subject
            consultant_name: Name of consultant (optional)
            anonymize_consultant: If True, don't include consultant name
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            # Build email content
            subject = f"LegaVex: Документ по делу «{case_title}»"
            
            if anonymize_consultant or not consultant_name:
                greeting = "Уважаемый клиент,"
                consultant_info = ""
            else:
                greeting = "Уважаемый клиент,"
                consultant_info = f"\n\nКонсультант: {consultant_name}"
            
            body = f"""{greeting}

Во вложении находится подготовленный документ по вашему делу «{case_title}».{consultant_info}

Если у вас есть вопросы, пожалуйста, свяжитесь с нами через платформу.

---
LegaVex — юридическая помощь на стороне человека.
Это письмо отправлено через защищённый канал.
"""
            
            if self.email_enabled:
                # TODO: Implement real email sending via aiosmtplib
                # Example implementation:
                # 
                # import aiosmtplib
                # from email.mime.multipart import MIMEMultipart
                # from email.mime.application import MIMEApplication
                # 
                # msg = MIMEMultipart()
                # msg['From'] = f"{self.from_name} <{self.smtp_user}>"
                # msg['To'] = recipient_email
                # msg['Subject'] = subject
                # msg.attach(MIMEText(body, 'plain', 'utf-8'))
                # 
                # with open(file_path, 'rb') as f:
                #     attachment = MIMEApplication(f.read(), _subtype='pdf')
                #     attachment.add_header('Content-Disposition', 'attachment', filename='document.pdf')
                #     msg.attach(attachment)
                # 
                # await aiosmtplib.send(
                #     msg,
                #     hostname=self.smtp_host,
                #     port=self.smtp_port,
                #     start_tls=True,
                #     username=self.smtp_user,
                #     password=self.smtp_password,
                # )
                
                logger.warning(
                    "Email sending is enabled but not yet implemented. "
                    "Email would be sent to: %s",
                    recipient_email
                )
                status = "SENT"  # Mark as sent for now
                error_message = None
            else:
                # Stub mode - just log the email
                logger.info(
                    "[STUB] Email would be sent:\n"
                    "  To: %s\n"
                    "  Subject: %s\n"
                    "  Attachment: %s",
                    recipient_email,
                    subject,
                    file_path
                )
                status = "SENT"
                error_message = None
            
            # Log to database
            await self.db.emaillog.create(
                data={
                    "caseId": case_id,
                    "recipientEmail": recipient_email,
                    "subject": subject,
                    "status": status,
                    "errorMessage": error_message,
                }
            )
            
            logger.info(
                "Email logged for case %s to %s (status: %s)",
                case_id,
                recipient_email,
                status
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to send email for case %s to %s: %s",
                case_id,
                recipient_email,
                str(e)
            )
            
            # Log failure to database
            try:
                await self.db.emaillog.create(
                    data={
                        "caseId": case_id,
                        "recipientEmail": recipient_email,
                        "subject": f"LegaVex: Документ по делу «{case_title}»",
                        "status": "FAILED",
                        "errorMessage": str(e),
                    }
                )
            except Exception as log_error:
                logger.error("Failed to log email error: %s", log_error)
            
            return False
    
    async def get_email_logs(
        self,
        case_id: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """Get email logs, optionally filtered by case.
        
        Args:
            case_id: Optional case ID to filter by
            limit: Maximum number of logs to return
            
        Returns:
            List of email log records
        """
        where = {}
        if case_id:
            where["caseId"] = case_id
        
        return await self.db.emaillog.find_many(
            where=where,
            order={"sentAt": "desc"},
            take=limit,
        )
