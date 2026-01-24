"""Connection pool and schema management for Voice Capture database.

This module provides the core database infrastructure:
- ConnectionPool: Async connection pool for SQLite
- SCHEMA_SQL: Database schema definition
- initialize_database: Schema initialization function
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

logger = logging.getLogger(__name__)


# Schema definition matching TDD Section 3.1 exactly
SCHEMA_SQL = """
-- Main processing queue
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    current_path TEXT,
    device TEXT,
    captured_at TIMESTAMP,
    source TEXT DEFAULT 'watcher',  -- Upload source: 'watcher' or 'http'

    -- Processing state
    status TEXT NOT NULL DEFAULT 'pending',
    -- Values: pending, transcribing, classifying, posting, complete, failed

    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP,

    -- Transcription results
    transcript TEXT,
    transcript_duration_seconds REAL,
    transcript_language TEXT,

    -- Classification results
    template_name TEXT,
    classification_confidence REAL,
    extracted_fields JSON,
    suggested_title TEXT,
    tags JSON,

    -- Notion results
    notion_page_id TEXT,
    notion_page_url TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_captures_status ON captures(status);
CREATE INDEX IF NOT EXISTS idx_captures_captured_at ON captures(captured_at);
CREATE INDEX IF NOT EXISTS idx_captures_source ON captures(source);

-- Failure history for debugging
CREATE TABLE IF NOT EXISTS failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    error_details JSON,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (capture_id) REFERENCES captures(id)
);

CREATE INDEX IF NOT EXISTS idx_failure_log_capture_id ON failure_log(capture_id);

-- Daily statistics for health monitoring
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    captures_received INTEGER DEFAULT 0,
    captures_completed INTEGER DEFAULT 0,
    captures_failed INTEGER DEFAULT 0,
    total_audio_seconds REAL DEFAULT 0,
    avg_processing_time_seconds REAL,
    template_breakdown JSON
);
"""

# Valid status values for state machine
VALID_STATUSES = {"pending", "transcribing", "classifying", "posting", "complete", "failed"}


class ConnectionPool:
    """Async SQLite connection pool.

    Manages a pool of database connections for efficient async access.
    Connections are pre-created during initialization and recycled.

    Usage:
        pool = ConnectionPool(Path("/path/to/database.db"))
        await pool.initialize()

        async with pool.acquire() as conn:
            cursor = await conn.execute("SELECT * FROM captures")
            ...

        await pool.close()
    """

    def __init__(self, db_path: Path, pool_size: int = 5):
        """Initialize connection pool.

        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=pool_size)
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def initialized(self) -> bool:
        """Check if pool is initialized."""
        return self._initialized

    async def initialize(self) -> None:
        """Initialize the connection pool and create schema.

        Creates the database file and all tables/indexes if they don't exist.
        Pre-populates the connection pool.
        Safe to call multiple times.
        """
        async with self._lock:
            if self._initialized:
                return

            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create initial connection to setup schema
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            try:
                await conn.executescript(SCHEMA_SQL)
                await conn.commit()
                logger.info(f"Database initialized at {self.db_path}")
            finally:
                await conn.close()

            # Pre-populate connection pool
            for _ in range(self.pool_size):
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row
                await self._pool.put(conn)

            self._initialized = True

    async def close(self) -> None:
        """Close all database connections."""
        async with self._lock:
            if not self._initialized:
                return

            while not self._pool.empty():
                conn = await self._pool.get()
                await conn.close()

            self._initialized = False
            logger.info("Database connections closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[aiosqlite.Connection]:
        """Acquire a connection from the pool.

        Yields a connection and returns it to the pool when done.

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._initialized:
            raise RuntimeError("Connection pool not initialized. Call initialize() first.")

        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def __aenter__(self) -> "ConnectionPool":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    def empty(self) -> bool:
        """Check if pool is empty (for testing)."""
        return self._pool.empty()
