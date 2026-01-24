"""Tests for configuration settings."""

import os
from pathlib import Path

import pytest

from src.config.settings import Settings, get_settings, reload_settings


class TestSettings:
    """Test settings loading and validation."""

    def test_default_settings_load(self) -> None:
        """Test that settings can be loaded with defaults."""
        # Clear any cached settings
        reload_settings()
        settings = get_settings()

        # Check default values are set
        assert settings.paths.inbox == Path("/app/inbox")
        assert settings.pipeline.max_retries == 3
        assert settings.classification.confidence_threshold == 0.7

    def test_settings_from_environment(self, temp_dir: Path) -> None:
        """Test that environment variables override defaults."""
        # Set environment variables
        os.environ["OPENAI_API_KEY"] = "test-key-123"
        os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "custom_inbox")

        try:
            settings = reload_settings()

            assert settings.openai_api_key == "test-key-123"
            assert settings.paths.inbox == temp_dir / "custom_inbox"
        finally:
            # Clean up
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("VOICE_CAPTURE_INBOX_PATH", None)
            reload_settings()

    def test_validate_required_settings_missing(self) -> None:
        """Test that missing required settings are detected."""
        # Clear API keys
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOTION_API_KEY"]:
            os.environ.pop(key, None)

        settings = reload_settings()
        missing = settings.validate_required_for_production()

        assert "OPENAI_API_KEY" in missing
        assert "ANTHROPIC_API_KEY" in missing
        assert "NOTION_API_KEY" in missing

    def test_validate_required_settings_present(self) -> None:
        """Test that present required settings pass validation."""
        os.environ["OPENAI_API_KEY"] = "test-openai"
        os.environ["ANTHROPIC_API_KEY"] = "test-anthropic"
        os.environ["NOTION_API_KEY"] = "test-notion"
        os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"

        try:
            settings = reload_settings()
            missing = settings.validate_required_for_production()

            assert len(missing) == 0
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("NOTION_API_KEY", None)
            os.environ.pop("NOTION_VOICE_CAPTURES_DB_ID", None)
            reload_settings()

    def test_ensure_directories_exist(self, temp_dir: Path) -> None:
        """Test that directories are created when ensure_directories_exist is called."""
        os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
        os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
        os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
        os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "data" / "test.db")
        os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")

        try:
            settings = reload_settings()
            settings.ensure_directories_exist()

            assert (temp_dir / "inbox").exists()
            assert (temp_dir / "processing").exists()
            assert (temp_dir / "failed").exists()
            assert (temp_dir / "data").exists()
            assert (temp_dir / "logs").exists()
        finally:
            os.environ.pop("VOICE_CAPTURE_INBOX_PATH", None)
            os.environ.pop("VOICE_CAPTURE_PROCESSING_PATH", None)
            os.environ.pop("VOICE_CAPTURE_FAILED_PATH", None)
            os.environ.pop("VOICE_CAPTURE_DB_PATH", None)
            os.environ.pop("VOICE_CAPTURE_LOG_PATH", None)
            reload_settings()

    def test_settings_caching(self) -> None:
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_settings_reload(self) -> None:
        """Test that reload_settings returns new instance."""
        settings1 = get_settings()
        settings2 = reload_settings()

        # After reload, should be different instance
        assert settings1 is not settings2

        # But get_settings should now return the new cached instance
        settings3 = get_settings()
        assert settings2 is settings3

    def test_nested_settings_defaults(self) -> None:
        """Test that nested settings have correct defaults."""
        settings = reload_settings()

        # Check transcription defaults
        assert settings.transcription.backend == "whisper_api"
        assert settings.transcription.model == "whisper-1"
        assert settings.transcription.timeout_seconds == 120.0

        # Check classification defaults
        assert settings.classification.model == "claude-sonnet-4-20250514"
        assert settings.classification.confidence_threshold == 0.7
        assert settings.classification.max_tokens == 2048

        # Check pipeline defaults
        assert settings.pipeline.max_retries == 3
        assert settings.pipeline.base_backoff_seconds == 5.0
        assert settings.pipeline.file_settle_delay_seconds == 2.0

        # Check watcher defaults
        assert ".m4a" in settings.watcher.valid_extensions
        assert ".wav" in settings.watcher.valid_extensions
        assert ".mp3" in settings.watcher.valid_extensions

    def test_confidence_threshold_bounds(self) -> None:
        """Test that confidence threshold is validated."""
        # Valid values should work
        settings = reload_settings()
        assert 0.0 <= settings.classification.confidence_threshold <= 1.0


class TestHttpServerSettings:
    """Test HTTP server settings loading and validation."""

    def test_http_settings_defaults(self) -> None:
        """Test that HTTP settings have correct defaults."""
        settings = reload_settings()

        # HTTP server is disabled by default (backward compatible)
        assert settings.http.enabled is False
        assert settings.http.host == "0.0.0.0"
        assert settings.http.port == 8080
        assert settings.http.api_key is None
        assert settings.http.max_upload_mb == 100
        assert settings.http.request_timeout_seconds == 60
        assert settings.http.cors_origins == []

    def test_http_settings_from_environment(self) -> None:
        """Test that HTTP settings can be loaded from environment variables."""
        os.environ["HTTP_ENABLED"] = "true"
        os.environ["HTTP_PORT"] = "9090"
        os.environ["HTTP_HOST"] = "127.0.0.1"
        os.environ["HTTP_API_KEY"] = "test-api-key-123"
        os.environ["HTTP_MAX_UPLOAD_MB"] = "50"
        os.environ["HTTP_REQUEST_TIMEOUT_SECONDS"] = "120"

        try:
            settings = reload_settings()

            assert settings.http.enabled is True
            assert settings.http.port == 9090
            assert settings.http.host == "127.0.0.1"
            assert settings.http.api_key == "test-api-key-123"
            assert settings.http.max_upload_mb == 50
            assert settings.http.request_timeout_seconds == 120
        finally:
            os.environ.pop("HTTP_ENABLED", None)
            os.environ.pop("HTTP_PORT", None)
            os.environ.pop("HTTP_HOST", None)
            os.environ.pop("HTTP_API_KEY", None)
            os.environ.pop("HTTP_MAX_UPLOAD_MB", None)
            os.environ.pop("HTTP_REQUEST_TIMEOUT_SECONDS", None)
            reload_settings()

    def test_http_port_validation(self) -> None:
        """Test that HTTP port is validated within valid range."""
        from pydantic import ValidationError
        from src.config.settings import HttpServerSettings

        # Valid ports should work
        valid_settings = HttpServerSettings(port=8080)
        assert valid_settings.port == 8080

        valid_settings = HttpServerSettings(port=1)
        assert valid_settings.port == 1

        valid_settings = HttpServerSettings(port=65535)
        assert valid_settings.port == 65535

        # Invalid ports should raise validation error
        with pytest.raises(ValidationError):
            HttpServerSettings(port=0)

        with pytest.raises(ValidationError):
            HttpServerSettings(port=65536)

    def test_http_max_upload_validation(self) -> None:
        """Test that max upload size is validated."""
        from pydantic import ValidationError
        from src.config.settings import HttpServerSettings

        # Valid values should work
        valid_settings = HttpServerSettings(max_upload_mb=1)
        assert valid_settings.max_upload_mb == 1

        valid_settings = HttpServerSettings(max_upload_mb=500)
        assert valid_settings.max_upload_mb == 500

        # Invalid values should raise validation error
        with pytest.raises(ValidationError):
            HttpServerSettings(max_upload_mb=0)

        with pytest.raises(ValidationError):
            HttpServerSettings(max_upload_mb=501)

    def test_http_timeout_validation(self) -> None:
        """Test that request timeout is validated."""
        from pydantic import ValidationError
        from src.config.settings import HttpServerSettings

        # Valid values should work
        valid_settings = HttpServerSettings(request_timeout_seconds=10)
        assert valid_settings.request_timeout_seconds == 10

        valid_settings = HttpServerSettings(request_timeout_seconds=300)
        assert valid_settings.request_timeout_seconds == 300

        # Invalid values should raise validation error
        with pytest.raises(ValidationError):
            HttpServerSettings(request_timeout_seconds=9)

        with pytest.raises(ValidationError):
            HttpServerSettings(request_timeout_seconds=301)

    def test_http_cors_origins(self) -> None:
        """Test that CORS origins can be configured."""
        from src.config.settings import HttpServerSettings

        # Empty list by default
        settings = HttpServerSettings()
        assert settings.cors_origins == []

        # Can set custom origins
        settings = HttpServerSettings(cors_origins=["http://localhost:3000", "https://example.com"])
        assert len(settings.cors_origins) == 2
        assert "http://localhost:3000" in settings.cors_origins
        assert "https://example.com" in settings.cors_origins

    def test_http_disabled_by_default_no_breaking_change(self) -> None:
        """Test that HTTP is disabled by default to ensure backward compatibility."""
        # This test ensures we don't accidentally enable HTTP by default
        # which would be a breaking change for existing deployments
        settings = reload_settings()
        assert settings.http.enabled is False, "HTTP must be disabled by default for backward compatibility"
