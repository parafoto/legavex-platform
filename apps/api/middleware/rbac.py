"""Role-Based Access Control (RBAC) middleware and dependencies."""

import logging
from functools import wraps
from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from ..config import settings
from ..schemas import Role
from ..models import get_prisma_client

logger = logging.getLogger(__name__)

security = HTTPBearer()


class TokenData:
    """JWT token payload data."""
    
    def __init__(self, user_id: str, email: str, role: Role):
        self.user_id = user_id
        self.email = email
        self.role = role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """Extract and validate JWT token from request.
    
    Args:
        credentials: HTTP Bearer credentials
        
    Returns:
        TokenData with user information
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        
        user_id = payload.get("sub")
        email = payload.get("email")
        role = payload.get("role")
        
        if not user_id or not email or not role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        
        return TokenData(
            user_id=user_id,
            email=email,
            role=Role(role),
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def require_role(*allowed_roles: Role) -> Callable:
    """Dependency factory to require specific roles.
    
    Args:
        *allowed_roles: Roles that are allowed to access the endpoint
        
    Returns:
        Dependency function that validates user role
        
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: TokenData = Depends(require_role(Role.ADMIN))):
            ...
    """
    async def role_checker(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        if current_user.role not in allowed_roles:
            logger.warning(
                "Access denied for user %s (role: %s) to endpoint requiring %s",
                current_user.user_id,
                current_user.role.value,
                [r.value for r in allowed_roles],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}",
            )
        return current_user
    
    return role_checker


# Pre-built role dependencies for convenience
require_admin = require_role(Role.ADMIN)
require_consultant = require_role(Role.CONSULTANT)
require_consultant_or_admin = require_role(Role.CONSULTANT, Role.ADMIN)


async def verify_case_access(
    case_id: str,
    current_user: TokenData,
) -> bool:
    """Verify user has access to a specific case.
    
    - Admins can access all cases
    - Consultants can only access their assigned cases
    - Clients can only access their own cases
    
    Args:
        case_id: ID of the case
        current_user: Current authenticated user
        
    Returns:
        True if access is allowed
        
    Raises:
        HTTPException: If access is denied
    """
    if current_user.role == Role.ADMIN:
        return True
    
    db = await get_prisma_client()
    
    if current_user.role == Role.CONSULTANT:
        # Check if consultant is assigned to this case
        assignment = await db.caseassignment.find_first(
            where={
                "caseId": case_id,
                "consultantId": current_user.user_id,
                "status": {"in": ["OFFERED", "ACCEPTED"]},
            }
        )
        
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned to this case",
            )
        
        return True
    
    if current_user.role == Role.CLIENT:
        # Check if client owns this case
        case = await db.case.find_unique(
            where={"id": case_id}
        )
        
        if not case or case.clientId != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this case",
            )
        
        return True
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied",
    )
