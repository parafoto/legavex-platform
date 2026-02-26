"""FastAPI dependency injection."""

from typing import AsyncGenerator

from fastapi import Request
from prisma import Prisma

from .models import get_prisma_client
from .services import CaseService, EmailService, AuditService


async def get_db() -> AsyncGenerator[Prisma, None]:
    """Get database client dependency.
    
    Yields:
        Prisma client instance
    """
    client = await get_prisma_client()
    yield client


async def get_case_service(db: Prisma = None) -> CaseService:
    """Get case service dependency.
    
    Args:
        db: Optional Prisma client
        
    Returns:
        CaseService instance
    """
    if db is None:
        db = await get_prisma_client()
    return CaseService(db)


async def get_email_service(db: Prisma = None) -> EmailService:
    """Get email service dependency.
    
    Args:
        db: Optional Prisma client
        
    Returns:
        EmailService instance
    """
    if db is None:
        db = await get_prisma_client()
    return EmailService(db)


async def get_audit_service(db: Prisma = None) -> AuditService:
    """Get audit service dependency.
    
    Args:
        db: Optional Prisma client
        
    Returns:
        AuditService instance
    """
    if db is None:
        db = await get_prisma_client()
    return AuditService(db)


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Client IP address
    """
    # Check for forwarded headers (reverse proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    return request.client.host if request.client else "unknown"
