"""Pydantic settings management for Voice Capture.

Loads configuration from environment variables with YAML defaults.
Environment variables override YAML settings.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_project_root() -> Path:
    """Get the project root directory."""
    # When running from src/, go up one level
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback to current working directory
    return Path.cwd()


def _load_yaml_config() -> dict[str, Any]:
    """Load configuration from YAML file if it exists."""
    project_root = _get_project_root()
    config_path = project_root / "config" / "settings.yaml"

    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


class PathsSettings(BaseSettings):
    """Path configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="VOICE_CAPTURE_",
        extra="ignore",
    )

    inbox: Path = Field(
        default=Path("/app/inbox"),
        validation_alias="VOICE_CAPTURE_INBOX_PATH",
        description="Directory for incoming audio files (rclone sync target)",
    )
    processing: Path = Field(
        default=Path("/app/processing"),
        validation_alias="VOICE_CAPTURE_PROCESSING_PATH",
        description="Directory for files being processed",
    )
    failed: Path = Field(
        default=Path("/app/failed"),
        validation_alias="VOICE_CAPTURE_FAILED_PATH",
        description="Directory for failed files requiring manual review",
    )
    database: Path = Field(
        default=Path("/app/data/voice_capture.db"),
        validation_alias="VOICE_CAPTURE_DB_PATH",
        description="SQLite database path",
    )
    logs: Path = Field(
        default=Path("/app/logs"),
        validation_alias="VOICE_CAPTURE_LOG_PATH",
        description="Log files directory",
    )
    templates: Path = Field(
        default=Path("./config/templates"),
        validation_alias="VOICE_CAPTURE_TEMPLATES_PATH",
        description="Template configuration directory",
    )

    @field_validator("inbox", "processing", "failed", "database", "logs", "templates", mode="before")
    @classmethod
    def convert_to_path(cls, v: Any) -> Path:
        """Convert string to Path."""
        if isinstance(v, str):
            return Path(v)
        return v


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(extra="ignore")

    level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    format: str = Field(
        default="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        description="Log message format",
    )
    max_bytes: int = Field(
        default=10485760,  # 10MB
        description="Maximum log file size before rotation",
    )
    backup_count: int = Field(
        default=5,
        description="Number of backup log files to keep",
    )


class TranscriptionSettings(BaseSettings):
    """Transcription service configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    backend: str = Field(
        default="whisper_api",
        description="Transcription backend (whisper_api, local_whisper)",
    )
    model: str = Field(
        default="whisper-1",
        description="Whisper model name",
    )
    timeout_seconds: float = Field(
        default=120.0,
        description="API request timeout in seconds",
    )


class ClassificationSettings(BaseSettings):
    """Classification service configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model for classification",
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to use a specific template",
    )
    max_tokens: int = Field(
        default=2048,
        description="Maximum tokens for classification response",
    )


class PipelineSettings(BaseSettings):
    """Pipeline processing configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    max_retries: int = Field(
        default=3,
        ge=1,
        description="Maximum retry attempts for failed operations",
    )
    base_backoff_seconds: float = Field(
        default=5.0,
        ge=0.0,
        description="Base delay for exponential backoff",
    )
    max_backoff_seconds: float = Field(
        default=300.0,
        ge=0.0,
        description="Maximum delay for exponential backoff",
    )
    file_settle_delay_seconds: float = Field(
        default=2.0,
        ge=0.0,
        description="Delay to wait for file write completion",
    )


class WatcherSettings(BaseSettings):
    """Folder watcher configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    valid_extensions: list[str] = Field(
        default=[".m4a", ".wav", ".mp3"],
        description="Valid audio file extensions",
    )
    polling_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        description="Interval for polling watcher events",
    )


class HealthCheckSettings(BaseSettings):
    """Health check configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    schedule: str = Field(
        default="0 21 * * *",
        description="Cron schedule for daily health check (9 PM default)",
    )
    failure_rate_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Failure rate threshold for alerting",
    )
    queue_backup_threshold: int = Field(
        default=10,
        ge=1,
        description="Queue depth threshold for alerting",
    )


class AudioSettings(BaseSettings):
    """Audio file constraints."""

    model_config = SettingsConfigDict(extra="ignore")

    max_size_mb: int = Field(
        default=100,
        ge=1,
        description="Maximum audio file size in MB",
    )
    max_duration_seconds: int = Field(
        default=3600,  # 1 hour
        ge=1,
        description="Maximum audio duration in seconds",
    )


class Settings(BaseSettings):
    """Main application settings.

    Configuration is loaded in priority order:
    1. Environment variables (highest priority)
    2. YAML configuration file (config/settings.yaml)
    3. Default values (lowest priority)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # API Keys (required)
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for Whisper transcription",
    )
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key for Claude classification",
    )
    notion_api_key: str = Field(
        default="",
        description="Notion integration API key",
    )
    pushover_api_token: str = Field(
        default="",
        description="Pushover application API token",
    )
    pushover_user_key: str = Field(
        default="",
        description="Pushover user key",
    )

    # Notion Database IDs (required)
    notion_voice_captures_db_id: str = Field(
        default="",
        description="Notion Voice Captures database ID",
    )
    notion_weekly_summaries_db_id: str = Field(
        default="",
        description="Notion Weekly Summaries database ID",
    )

    # rclone configuration
    rclone_sync_interval: int = Field(
        default=180,
        ge=60,
        description="rclone sync interval in seconds",
    )

    # Nested settings
    paths: PathsSettings = Field(default_factory=PathsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    watcher: WatcherSettings = Field(default_factory=WatcherSettings)
    health_check: HealthCheckSettings = Field(default_factory=HealthCheckSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)

    @model_validator(mode="before")
    @classmethod
    def load_yaml_defaults(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load YAML configuration as defaults, allowing env vars to override."""
        yaml_config = _load_yaml_config()

        # Merge YAML config with provided data (env vars take precedence)
        def deep_merge(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        return deep_merge(yaml_config, data)

    def validate_required_for_production(self) -> list[str]:
        """Validate that all required settings are configured.

        Returns a list of missing required settings.
        """
        missing = []

        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.notion_api_key:
            missing.append("NOTION_API_KEY")
        if not self.notion_voice_captures_db_id:
            missing.append("NOTION_VOICE_CAPTURES_DB_ID")

        # Pushover is optional but recommended
        # if not self.pushover_api_token:
        #     missing.append("PUSHOVER_API_TOKEN")
        # if not self.pushover_user_key:
        #     missing.append("PUSHOVER_USER_KEY")

        return missing

    def ensure_directories_exist(self) -> None:
        """Create required directories if they don't exist."""
        directories = [
            self.paths.inbox,
            self.paths.processing,
            self.paths.failed,
            self.paths.logs,
            self.paths.database.parent,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Settings are loaded once and cached for performance.
    Call get_settings.cache_clear() to reload.
    """
    return Settings()


def reload_settings() -> Settings:
    """Force reload of settings."""
    get_settings.cache_clear()
    return get_settings()
