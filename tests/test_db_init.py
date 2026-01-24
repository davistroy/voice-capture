"""Tests for database initialization CLI command.

Tests the init_database function and CLI command.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import pytest

from src.db.init import init_database, main


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# init_database Tests
# ============================================================================


class TestInitDatabase:
    """Tests for init_database function."""

    @pytest.mark.asyncio
    async def test_init_database_creates_new(self, temp_dir: Path):
        """Test initializing a new database."""
        db_path = temp_dir / "new_database.db"

        result = await init_database(db_path, force=False)

        assert result is True
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_init_database_creates_parent_directory(self, temp_dir: Path):
        """Test that parent directory is created if it doesn't exist."""
        db_path = temp_dir / "subdir" / "database.db"
        assert not db_path.parent.exists()

        result = await init_database(db_path, force=False)

        assert result is True
        assert db_path.parent.exists()
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_init_database_idempotent(self, temp_dir: Path):
        """Test that initializing an existing database is idempotent."""
        db_path = temp_dir / "existing.db"

        # Initialize twice
        result1 = await init_database(db_path, force=False)
        result2 = await init_database(db_path, force=False)

        assert result1 is True
        assert result2 is True

    @pytest.mark.asyncio
    async def test_init_database_force_recreates(self, temp_dir: Path):
        """Test force flag deletes and recreates database."""
        db_path = temp_dir / "force_test.db"

        # Create initial database
        result1 = await init_database(db_path, force=False)
        assert result1 is True

        # Force recreate
        result2 = await init_database(db_path, force=True)
        assert result2 is True

        # Database should exist
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_init_database_verifies_tables(self, temp_dir: Path):
        """Test that database verification checks for tables."""
        db_path = temp_dir / "verify_tables.db"

        result = await init_database(db_path, force=False)

        assert result is True

        # Verify tables were created by checking the database
        import aiosqlite
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in await cursor.fetchall()]

            # Should have the captures table at minimum
            assert "captures" in tables


# ============================================================================
# main() CLI Tests
# ============================================================================


class TestMainCLI:
    """Tests for main CLI function."""

    def test_main_with_custom_path(self, temp_dir: Path, monkeypatch):
        """Test main with custom database path."""
        custom_path = temp_dir / "custom.db"

        monkeypatch.setattr(sys, "argv", ["init", "--path", str(custom_path)])

        exit_code = main()

        assert exit_code == 0
        assert custom_path.exists()

    def test_main_verbose_mode(self, temp_dir: Path, monkeypatch):
        """Test main with verbose logging."""
        db_path = temp_dir / "verbose.db"

        monkeypatch.setattr(sys, "argv", ["init", "--path", str(db_path), "--verbose"])

        exit_code = main()

        assert exit_code == 0
        assert db_path.exists()

    def test_main_force_requires_confirmation(self, temp_dir: Path, monkeypatch):
        """Test that force flag requires confirmation."""
        db_path = temp_dir / "force.db"
        db_path.touch()  # Create the file first

        monkeypatch.setattr(sys, "argv", ["init", "--path", str(db_path), "--force"])

        # Simulate user typing 'n' for no
        with patch("builtins.input", return_value="n"):
            exit_code = main()

        assert exit_code == 1  # Should abort

    def test_main_force_with_confirmation(self, temp_dir: Path, monkeypatch):
        """Test force flag with user confirmation."""
        db_path = temp_dir / "force_confirm.db"
        db_path.touch()  # Create the file first

        monkeypatch.setattr(sys, "argv", ["init", "--path", str(db_path), "--force"])

        # Simulate user typing 'y' for yes
        with patch("builtins.input", return_value="y"):
            exit_code = main()

        assert exit_code == 0
        assert db_path.exists()

    def test_main_force_nonexistent_db_with_confirmation(self, temp_dir: Path, monkeypatch):
        """Test force flag when database doesn't exist yet still asks for confirmation."""
        db_path = temp_dir / "nonexistent.db"
        assert not db_path.exists()

        monkeypatch.setattr(sys, "argv", ["init", "--path", str(db_path), "--force"])

        # Force always prompts for confirmation
        with patch("builtins.input", return_value="y"):
            exit_code = main()

        assert exit_code == 0
        assert db_path.exists()
