"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .config import settings
from .models import get_prisma_client, disconnect_prisma
from .routers import auth_router, consultant_router, admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting LegasVex Advisor Portal API...")
    
    try:
        # Connect to database
        await get_prisma_client()
        logger.info("Database connected successfully")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down LegasVex Advisor Portal API...")
    await disconnect_prisma()
    logger.info("Database disconnected")


# Create FastAPI application
app = FastAPI(
    title="LegasVex Advisor Portal API",
    description="""
    Backend API for LegasVex Advisor Portal.
    
    ## Features
    
    - **Authentication**: JWT-based authentication with role support
    - **Consultant Dashboard**: Case management, chat, document upload
    - **Admin Panel**: Case assignment, document review, settings management
    - **RBAC**: Role-based access control (CLIENT, CONSULTANT, ADMIN)
    
    ## Roles
    
    - **CLIENT**: Can create cases and view their status
    - **CONSULTANT**: Can accept/decline cases, chat, upload documents
    - **ADMIN**: Full access to all cases, can assign consultants, approve documents
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed response."""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": errors,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.exception(f"Unexpected error: {exc}")
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "message": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


# Include routers
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(consultant_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint.
    
    Returns:
        Health status and version info
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "service": "legasvex-api",
    }


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint.
    
    Returns:
        API information
    """
    return {
        "name": "LegasVex Advisor Portal API",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else "Disabled in production",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
