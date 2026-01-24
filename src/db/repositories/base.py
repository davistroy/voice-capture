"""Base repository class for database operations.

Provides common patterns and utilities for all repository implementations.
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import aiosqlite

if TYPE_CHECKING:
    from src.db.connection import ConnectionPool


class BaseRepository:
    """Base class for repository implementations.

    Provides connection management and common utilities.
    All repository methods should use _get_connection() to acquire
    database connections from the pool.

    Usage:
        class MyRepository(BaseRepository):
            async def get_item(self, item_id: int):
                async with self._get_connection() as conn:
                    cursor = await conn.execute(
                        "SELECT * FROM items WHERE id = ?",
                        (item_id,)
                    )
                    return await cursor.fetchone()
    """

    def __init__(self, pool: "ConnectionPool"):
        """Initialize repository with connection pool.

        Args:
            pool: ConnectionPool instance for database access
        """
        self._pool = pool

    @asynccontextmanager
    async def _get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Get a connection from the pool.

        Yields a connection and returns it to the pool when done.

        Raises:
            RuntimeError: If pool is not initialized
        """
        async with self._pool.acquire() as conn:
            yield conn
