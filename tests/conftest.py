"""Pytest configuration and shared fixtures for Voice Capture tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from src.config.settings import Settings, reload_settings


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    """Create test settings with temporary directories."""
    # Set environment variables for test settings
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["NOTION_API_KEY"] = "test-notion-key"
    os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"
    os.environ["NOTION_WEEKLY_SUMMARIES_DB_ID"] = "test-weekly-db-id"
    os.environ["PUSHOVER_API_TOKEN"] = "test-pushover-token"
    os.environ["PUSHOVER_USER_KEY"] = "test-pushover-user"

    # Use temp directories
    os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
    os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
    os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
    os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "data" / "test.db")
    os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")

    # Reload settings to pick up test values
    settings = reload_settings()

    # Ensure directories exist
    settings.ensure_directories_exist()

    yield settings

    # Clean up environment variables
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "NOTION_API_KEY",
        "NOTION_VOICE_CAPTURES_DB_ID",
        "NOTION_WEEKLY_SUMMARIES_DB_ID",
        "PUSHOVER_API_TOKEN",
        "PUSHOVER_USER_KEY",
        "VOICE_CAPTURE_INBOX_PATH",
        "VOICE_CAPTURE_PROCESSING_PATH",
        "VOICE_CAPTURE_FAILED_PATH",
        "VOICE_CAPTURE_DB_PATH",
        "VOICE_CAPTURE_LOG_PATH",
    ]:
        os.environ.pop(key, None)

    # Clear settings cache
    reload_settings()


@pytest.fixture
def sample_audio_bytes() -> bytes:
    """Return minimal valid M4A file header bytes for testing."""
    # Minimal ftyp box for M4A (just enough to pass magic byte validation)
    # This is not a playable file, just enough to pass format detection
    return bytes([
        0x00, 0x00, 0x00, 0x20,  # Box size (32 bytes)
        0x66, 0x74, 0x79, 0x70,  # "ftyp"
        0x4D, 0x34, 0x41, 0x20,  # "M4A "
        0x00, 0x00, 0x00, 0x00,  # Version
        0x4D, 0x34, 0x41, 0x20,  # "M4A " (compatible brand)
        0x6D, 0x70, 0x34, 0x32,  # "mp42" (compatible brand)
        0x69, 0x73, 0x6F, 0x6D,  # "isom" (compatible brand)
        0x00, 0x00, 0x00, 0x00,  # Padding
    ])
