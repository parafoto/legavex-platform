"""Authentication routes."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
import jwt
from passlib.context import CryptContext

from ..config import settings
from ..models import get_prisma_client
from ..schemas import UserCreate, UserLogin, UserResponse, UserWithToken, Role
from ..middleware import get_current_user, TokenData
from ..dependencies import get_audit_service, get_client_ip
from ..services import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(user_id: str, email: str, role: str) -> str:
    """Create JWT access token."""
    expires = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expires,
        "iat": datetime.utcnow(),
    }
    
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@router.post(
    "/login",
    response_model=UserWithToken,
    summary="Login with email and password",
)
async def login(
    credentials: UserLogin,
    request: Request,
):
    """Authenticate user and return JWT token.
    
    Args:
        credentials: Email and password
        
    Returns:
        User data with access token
    """
    db = await get_prisma_client()
    
    # Find user by email
    user = await db.user.find_unique(
        where={"email": credentials.email}
    )
    
    if not user:
        logger.warning("Login attempt for non-existent user: %s", credentials.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Verify password
    if not user.passwordHash or not verify_password(credentials.password, user.passwordHash):
        logger.warning("Invalid password for user: %s", credentials.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Check if user is active
    if not user.isActive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    
    # Create token
    token = create_access_token(user.id, user.email, user.role)
    
    # Log audit
    audit = AuditService(db)
    await audit.log(
        action=AuditService.ACTION_LOGIN,
        entity_type=AuditService.ENTITY_USER,
        entity_id=user.id,
        user_id=user.id,
        ip_address=get_client_ip(request),
    )
    
    logger.info("User logged in: %s (role: %s)", user.email, user.role)
    
    return UserWithToken(
        user=UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            role=Role(user.role),
            isActive=user.isActive,
            createdAt=user.createdAt,
        ),
        access_token=token,
    )


@router.post(
    "/register",
    response_model=UserWithToken,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user (for testing)",
)
async def register(
    user_data: UserCreate,
    request: Request,
):
    """Register a new user.
    
    Note: In production, this endpoint should be protected or removed.
    User creation should be done through admin panel.
    
    Args:
        user_data: User registration data
        
    Returns:
        Created user with access token
    """
    db = await get_prisma_client()
    
    # Check if email already exists
    existing = await db.user.find_unique(
        where={"email": user_data.email}
    )
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Hash password
    password_hash = get_password_hash(user_data.password)
    
    # Create user
    user = await db.user.create(
        data={
            "name": user_data.name,
            "email": user_data.email,
            "phone": user_data.phone,
            "passwordHash": password_hash,
            "role": user_data.role.value,
        }
    )
    
    # If consultant, create profile
    if user_data.role == Role.CONSULTANT:
        await db.consultantprofile.create(
            data={
                "userId": user.id,
            }
        )
    
    # Create token
    token = create_access_token(user.id, user.email, user.role)
    
    # Log audit
    audit = AuditService(db)
    await audit.log(
        action=AuditService.ACTION_CREATE_USER,
        entity_type=AuditService.ENTITY_USER,
        entity_id=user.id,
        user_id=user.id,
        new_value={"email": user.email, "role": user.role},
        ip_address=get_client_ip(request),
    )
    
    logger.info("User registered: %s (role: %s)", user.email, user.role)
    
    return UserWithToken(
        user=UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            role=Role(user.role),
            isActive=user.isActive,
            createdAt=user.createdAt,
        ),
        access_token=token,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user info",
)
async def get_me(
    current_user: TokenData = Depends(get_current_user),
):
    """Get current authenticated user information.
    
    Returns:
        Current user data
    """
    db = await get_prisma_client()
    
    user = await db.user.find_unique(
        where={"id": current_user.user_id}
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=Role(user.role),
        isActive=user.isActive,
        createdAt=user.createdAt,
    )
