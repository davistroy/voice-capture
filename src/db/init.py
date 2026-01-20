"""CLI command for database initialization.

Usage:
    python -m src.db.init [--force]

Options:
    --force     Drop and recreate all tables (WARNING: destroys data)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.config.settings import get_settings
from src.db.database import Database, SCHEMA_SQL

logger = logging.getLogger(__name__)


async def init_database(db_path: Path, force: bool = False) -> bool:
    """Initialize the database.

    Args:
        db_path: Path to the database file
        force: If True, drop and recreate all tables

    Returns:
        True if initialization succeeded
    """
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if force and db_path.exists():
        logger.warning(f"Force flag set - deleting existing database: {db_path}")
        db_path.unlink()

    db = Database(db_path)
    try:
        await db.initialize()
        logger.info(f"Database initialized successfully at: {db_path}")

        # Verify tables were created
        async with db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row["name"] for row in await cursor.fetchall()]
            logger.info(f"Tables created: {tables}")

            # Verify indexes
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            )
            indexes = [row["name"] for row in await cursor.fetchall()]
            logger.info(f"Indexes created: {indexes}")

        return True

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

    finally:
        await db.close()


def main() -> int:
    """Main entry point for CLI command."""
    parser = argparse.ArgumentParser(
        description="Initialize the Voice Capture SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m src.db.init                  # Initialize database
    python -m src.db.init --force          # Recreate database from scratch
    python -m src.db.init --path /tmp/test.db  # Use custom path
        """,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Drop and recreate all tables (WARNING: destroys data)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Custom database path (default: from settings)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Get database path
    if args.path:
        db_path = args.path
    else:
        settings = get_settings()
        db_path = settings.paths.database

    print(f"Initializing database at: {db_path}")

    if args.force:
        response = input("WARNING: This will delete all existing data. Continue? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

    # Run initialization
    success = asyncio.run(init_database(db_path, force=args.force))

    if success:
        print("Database initialization complete.")
        return 0
    else:
        print("Database initialization failed. Check logs for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
