"""Audio file validation for Voice Capture.

Validates audio files by checking magic bytes (not just extensions),
file size, and other integrity checks before processing.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from src.models.capture import Device

logger = logging.getLogger(__name__)


class AudioFormat(Enum):
    """Supported audio formats with their magic bytes."""

    M4A = "m4a"
    WAV = "wav"
    MP3 = "mp3"
    UNKNOWN = "unknown"


# Magic bytes for audio file formats
# Reference: https://en.wikipedia.org/wiki/List_of_file_signatures
MAGIC_BYTES = {
    # M4A/MP4 containers have 'ftyp' at offset 4
    AudioFormat.M4A: [
        (4, b"ftyp"),  # General MP4 container marker
        (4, b"ftypM4A"),  # Specific M4A
        (4, b"ftypisom"),  # ISO base media
        (4, b"ftypmp42"),  # MP4 v2
    ],
    # WAV files start with 'RIFF' and have 'WAVE' at offset 8
    AudioFormat.WAV: [
        (0, b"RIFF"),
    ],
    # MP3 files can start with ID3 tag or frame sync
    AudioFormat.MP3: [
        (0, b"ID3"),  # ID3v2 tag
        (0, b"\xff\xfb"),  # MPEG frame sync (Layer 3)
        (0, b"\xff\xfa"),  # MPEG frame sync (Layer 3)
        (0, b"\xff\xf3"),  # MPEG frame sync (Layer 3)
        (0, b"\xff\xf2"),  # MPEG frame sync (Layer 3)
    ],
}


class FileValidationError(Exception):
    """Exception raised when file validation fails."""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


@dataclass
class ValidationResult:
    """Result of file validation.

    Attributes:
        is_valid: Whether the file is a valid audio file
        format: Detected audio format
        size_bytes: File size in bytes
        error_message: Error message if validation failed
        error_reason: Categorized error reason
    """

    is_valid: bool
    format: AudioFormat
    size_bytes: int
    error_message: Optional[str] = None
    error_reason: Optional[str] = None


@dataclass
class ParsedFilename:
    """Result of filename parsing.

    Attributes:
        timestamp: Captured timestamp (from filename or file mtime)
        device: Source device
        was_parsed: Whether the filename was successfully parsed
    """

    timestamp: datetime
    device: Device
    was_parsed: bool


class FileValidator:
    """Validates audio files for processing.

    Checks file format using magic bytes, validates size constraints,
    and parses filenames for metadata extraction.
    """

    # Filename pattern: {timestamp}_{device}.{ext}
    # Timestamp format: 2026-01-20T143022 (ISO-like without colons)
    FILENAME_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T\d{6})_([a-zA-Z]+)\.[a-zA-Z0-9]+$"
    )

    # Alternative patterns for flexibility
    TIMESTAMP_PATTERNS = [
        # 2026-01-20T143022
        (r"(\d{4}-\d{2}-\d{2}T\d{6})", "%Y-%m-%dT%H%M%S"),
        # 2026-01-20_143022
        (r"(\d{4}-\d{2}-\d{2}_\d{6})", "%Y-%m-%d_%H%M%S"),
        # 20260120_143022
        (r"(\d{8}_\d{6})", "%Y%m%d_%H%M%S"),
        # 20260120143022
        (r"(\d{14})", "%Y%m%d%H%M%S"),
    ]

    def __init__(
        self,
        valid_extensions: tuple[str, ...] = (".m4a", ".wav", ".mp3"),
        max_size_bytes: int = 100 * 1024 * 1024,  # 100 MB
        min_size_bytes: int = 100,  # 100 bytes minimum
    ):
        """Initialize file validator.

        Args:
            valid_extensions: Tuple of valid file extensions (with leading dot)
            max_size_bytes: Maximum allowed file size
            min_size_bytes: Minimum allowed file size
        """
        self.valid_extensions = tuple(ext.lower() for ext in valid_extensions)
        self.max_size_bytes = max_size_bytes
        self.min_size_bytes = min_size_bytes

    def validate_audio_file(self, file_path: Path) -> ValidationResult:
        """Validate an audio file.

        Performs comprehensive validation:
        1. Checks file exists and is readable
        2. Validates file extension
        3. Checks file size constraints
        4. Validates magic bytes for audio format

        Args:
            file_path: Path to the audio file

        Returns:
            ValidationResult with validation status and details
        """
        # Check file exists
        if not file_path.exists():
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=0,
                error_message=f"File does not exist: {file_path}",
                error_reason="file_not_found",
            )

        # Check it's a file (not directory)
        if not file_path.is_file():
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=0,
                error_message=f"Path is not a file: {file_path}",
                error_reason="not_a_file",
            )

        # Check extension
        extension = file_path.suffix.lower()
        if extension not in self.valid_extensions:
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=0,
                error_message=f"Invalid extension '{extension}'. Expected one of {self.valid_extensions}",
                error_reason="invalid_extension",
            )

        # Check file size
        try:
            size_bytes = file_path.stat().st_size
        except OSError as e:
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=0,
                error_message=f"Cannot read file stats: {e}",
                error_reason="permission_error",
            )

        if size_bytes < self.min_size_bytes:
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=size_bytes,
                error_message=f"File too small: {size_bytes} bytes (min: {self.min_size_bytes})",
                error_reason="file_too_small",
            )

        if size_bytes > self.max_size_bytes:
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=size_bytes,
                error_message=f"File too large: {size_bytes} bytes (max: {self.max_size_bytes})",
                error_reason="file_too_large",
            )

        # Check magic bytes
        audio_format = self._detect_format(file_path)
        if audio_format == AudioFormat.UNKNOWN:
            return ValidationResult(
                is_valid=False,
                format=AudioFormat.UNKNOWN,
                size_bytes=size_bytes,
                error_message="Invalid audio file: magic bytes do not match any supported format",
                error_reason="invalid_format",
            )

        # Verify format matches extension
        expected_format = self._extension_to_format(extension)
        if expected_format != AudioFormat.UNKNOWN and audio_format != expected_format:
            # Log warning but still accept if magic bytes indicate valid audio
            logger.warning(
                f"Format mismatch for {file_path}: extension suggests {expected_format.value}, "
                f"magic bytes indicate {audio_format.value}"
            )

        return ValidationResult(
            is_valid=True,
            format=audio_format,
            size_bytes=size_bytes,
        )

    def _detect_format(self, file_path: Path) -> AudioFormat:
        """Detect audio format from magic bytes.

        Args:
            file_path: Path to the file

        Returns:
            Detected AudioFormat or UNKNOWN
        """
        try:
            # Read first 32 bytes for magic byte detection
            with open(file_path, "rb") as f:
                header = f.read(32)

            if len(header) < 12:
                return AudioFormat.UNKNOWN

            # Check each format's magic bytes
            for audio_format, signatures in MAGIC_BYTES.items():
                for offset, magic in signatures:
                    if offset + len(magic) <= len(header):
                        if header[offset : offset + len(magic)] == magic:
                            # Additional check for WAV: verify 'WAVE' at offset 8
                            if audio_format == AudioFormat.WAV:
                                if len(header) >= 12 and header[8:12] == b"WAVE":
                                    return audio_format
                            else:
                                return audio_format

            return AudioFormat.UNKNOWN

        except OSError as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return AudioFormat.UNKNOWN

    def _extension_to_format(self, extension: str) -> AudioFormat:
        """Convert file extension to AudioFormat.

        Args:
            extension: File extension (with leading dot)

        Returns:
            Corresponding AudioFormat or UNKNOWN
        """
        mapping = {
            ".m4a": AudioFormat.M4A,
            ".wav": AudioFormat.WAV,
            ".mp3": AudioFormat.MP3,
        }
        return mapping.get(extension.lower(), AudioFormat.UNKNOWN)

    def parse_filename(self, filename: str, file_path: Optional[Path] = None) -> ParsedFilename:
        """Parse filename to extract timestamp and device.

        Expected format: {timestamp}_{device}.{ext}
        Example: 2026-01-20T143022_watch.m4a

        Falls back to file modification time and UNKNOWN device if parsing fails.

        Args:
            filename: The filename to parse
            file_path: Optional path to file for fallback mtime

        Returns:
            ParsedFilename with extracted or fallback metadata
        """
        # Try primary pattern
        match = self.FILENAME_PATTERN.match(filename)
        if match:
            timestamp_str = match.group(1)
            device_str = match.group(2).lower()

            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H%M%S")
                device = Device.from_string(device_str)
                return ParsedFilename(
                    timestamp=timestamp,
                    device=device,
                    was_parsed=True,
                )
            except ValueError:
                pass  # Fall through to alternative patterns

        # Try alternative timestamp patterns
        base_name = Path(filename).stem
        for pattern, date_format in self.TIMESTAMP_PATTERNS:
            ts_match = re.search(pattern, base_name)
            if ts_match:
                try:
                    timestamp = datetime.strptime(ts_match.group(1), date_format)

                    # Try to extract device
                    device = Device.UNKNOWN
                    remaining = base_name.replace(ts_match.group(1), "").strip("_- ")
                    if remaining:
                        device = Device.from_string(remaining)

                    return ParsedFilename(
                        timestamp=timestamp,
                        device=device,
                        was_parsed=True,
                    )
                except ValueError:
                    continue

        # Fallback: use file mtime if available
        fallback_time = datetime.utcnow()
        if file_path and file_path.exists():
            try:
                mtime = file_path.stat().st_mtime
                fallback_time = datetime.fromtimestamp(mtime)
            except OSError:
                pass

        logger.warning(
            f"Could not parse filename '{filename}', using mtime={fallback_time}, device=UNKNOWN"
        )

        return ParsedFilename(
            timestamp=fallback_time,
            device=Device.UNKNOWN,
            was_parsed=False,
        )

    def check_file_stable(
        self, file_path: Path, previous_size: Optional[int] = None
    ) -> Tuple[bool, int]:
        """Check if file size is stable (not still being written).

        Args:
            file_path: Path to the file
            previous_size: Previous file size to compare against

        Returns:
            Tuple of (is_stable, current_size)
        """
        try:
            current_size = file_path.stat().st_size
            if previous_size is None:
                return False, current_size
            return current_size == previous_size, current_size
        except OSError as e:
            logger.error(f"Error checking file stability for {file_path}: {e}")
            return False, 0
