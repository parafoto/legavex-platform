"""Prisma client wrapper for database operations."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from prisma import Prisma

logger = logging.getLogger(__name__)

# Global Prisma client instance
_prisma_client: Prisma | None = None


async def get_prisma_client() -> Prisma:
    """Get or create Prisma client instance."""
    global _prisma_client
    
    if _prisma_client is None:
        _prisma_client = Prisma()
    
    if not _prisma_client.is_connected():
        await _prisma_client.connect()
        logger.info("Connected to database")
    
    return _prisma_client


async def disconnect_prisma() -> None:
    """Disconnect Prisma client."""
    global _prisma_client
    
    if _prisma_client is not None and _prisma_client.is_connected():
        await _prisma_client.disconnect()
        logger.info("Disconnected from database")
        _prisma_client = None


@asynccontextmanager
async def get_db() -> AsyncGenerator[Prisma, None]:
    """Async context manager for database operations."""
    client = await get_prisma_client()
    try:
        yield client
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
