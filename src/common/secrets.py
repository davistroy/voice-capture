"""Secret masking utilities for error logs.

Provides defense-in-depth masking of secrets that may accidentally appear
in error messages, tracebacks, or notification content.

Work item 6.9: Add Secret Masking to Error Logs.
"""

import re
from typing import Sequence

# Common patterns for secrets that may appear in error messages
DEFAULT_SECRET_PATTERNS = [
    r'sk-[a-zA-Z0-9]{20,}',           # OpenAI API keys
    r'sk-ant-[a-zA-Z0-9-]{20,}',      # Anthropic API keys
    r'secret_[a-zA-Z0-9]{20,}',       # Notion tokens
    r'Bearer\s+[a-zA-Z0-9._-]+',      # Bearer tokens
    r'api[_-]?key["\s:=]+[^\s"\']+',  # Generic API keys
    r'password["\s:=]+[^\s"\']+',     # Passwords
]


def mask_secrets(
    text: str,
    patterns: Sequence[str] | None = None,
    replacement: str = "[REDACTED]"
) -> str:
    """Mask secrets in text using regex patterns.

    This is a defense-in-depth measure - secrets should not appear in error
    messages, but if they do, this function masks them before logging or
    sending notifications.

    Args:
        text: The text that may contain secrets.
        patterns: Optional sequence of regex patterns to match.
                  If None, uses DEFAULT_SECRET_PATTERNS.
        replacement: The string to replace matched secrets with.
                    Defaults to "[REDACTED]".

    Returns:
        The text with any matched secrets replaced.

    Example:
        >>> mask_secrets("Error: API key sk-abc123xyz789...")
        'Error: API key [REDACTED]'
    """
    if not text:
        return text

    if patterns is None:
        patterns = DEFAULT_SECRET_PATTERNS

    result = text
    for pattern in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def mask_exception(error: Exception) -> str:
    """Get masked string representation of exception.

    Converts exception to string and masks any secrets that may be present.

    Args:
        error: The exception to get a masked string for.

    Returns:
        String representation of the exception with secrets masked.

    Example:
        >>> e = ValueError("Invalid API key: sk-abc123xyz789...")
        >>> mask_exception(e)
        'Invalid API key: [REDACTED]'
    """
    return mask_secrets(str(error))
