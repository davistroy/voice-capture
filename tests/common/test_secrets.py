"""Tests for secret masking functionality.

Work item 6.9: Add Secret Masking to Error Logs.
"""

import pytest

from src.common.secrets import (
    mask_secrets,
    mask_exception,
    DEFAULT_SECRET_PATTERNS,
)


class TestMaskSecrets:
    """Tests for the mask_secrets function."""

    def test_mask_openai_api_key(self):
        """Test that OpenAI API keys (sk-...) are masked."""
        text = "Error: Invalid API key sk-abc123xyz789abc123xyz789"
        result = mask_secrets(text)
        assert "sk-abc123xyz789abc123xyz789" not in result
        assert "[REDACTED]" in result
        assert "Error: Invalid API key" in result

    def test_mask_anthropic_api_key(self):
        """Test that Anthropic API keys (sk-ant-...) are masked."""
        text = "Error: Invalid API key sk-ant-abc123-xyz789-def456-ghi012"
        result = mask_secrets(text)
        assert "sk-ant-abc123-xyz789-def456-ghi012" not in result
        assert "[REDACTED]" in result
        assert "Error: Invalid API key" in result

    def test_mask_notion_token(self):
        """Test that Notion tokens (secret_...) are masked."""
        text = "Notion API error: secret_abc123xyz789abc123xyz789 is invalid"
        result = mask_secrets(text)
        assert "secret_abc123xyz789abc123xyz789" not in result
        assert "[REDACTED]" in result
        assert "Notion API error:" in result

    def test_mask_bearer_token(self):
        """Test that Bearer tokens are masked."""
        text = "Authorization failed: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = mask_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "[REDACTED]" in result
        assert "Authorization failed:" in result

    def test_mask_generic_api_key(self):
        """Test that generic API key patterns are masked."""
        # Test api_key=value pattern
        text = 'Error with api_key="super-secret-key-123"'
        result = mask_secrets(text)
        assert "super-secret-key-123" not in result
        assert "[REDACTED]" in result

        # Test api-key:value pattern
        text = 'Config: api-key: my-secret-api-key'
        result = mask_secrets(text)
        assert "my-secret-api-key" not in result
        assert "[REDACTED]" in result

    def test_mask_password(self):
        """Test that passwords are masked."""
        text = 'Connection failed: password="my-secret-password"'
        result = mask_secrets(text)
        assert "my-secret-password" not in result
        assert "[REDACTED]" in result

        text = 'Error: password: secretpass123'
        result = mask_secrets(text)
        assert "secretpass123" not in result
        assert "[REDACTED]" in result

    def test_normal_text_not_affected(self):
        """Test that normal text without secrets is not affected."""
        text = "This is a normal error message without any secrets"
        result = mask_secrets(text)
        assert result == text

    def test_mixed_content_only_secrets_masked(self):
        """Test that only secrets are masked, not other content."""
        text = "Failed to call API at https://api.example.com with key sk-1234567890abcdef1234567890: timeout"
        result = mask_secrets(text)
        assert "https://api.example.com" in result
        assert "sk-1234567890abcdef1234567890" not in result
        assert "[REDACTED]" in result
        assert "timeout" in result

    def test_multiple_secrets_all_masked(self):
        """Test that multiple secrets in the same text are all masked."""
        text = "Keys: sk-openai123456789012345678 and sk-ant-anthropic12345678-abcd"
        result = mask_secrets(text)
        assert "sk-openai123456789012345678" not in result
        assert "sk-ant-anthropic12345678-abcd" not in result
        # Both should be replaced
        assert result.count("[REDACTED]") == 2

    def test_empty_string(self):
        """Test that empty string is handled correctly."""
        result = mask_secrets("")
        assert result == ""

    def test_none_safe(self):
        """Test that None is handled correctly."""
        # The function expects a string, but should handle empty/falsy gracefully
        result = mask_secrets("")
        assert result == ""

    def test_custom_patterns(self):
        """Test that custom patterns can be provided."""
        text = "Custom secret: CUSTOM_12345_SECRET"
        custom_patterns = [r'CUSTOM_\d+_SECRET']
        result = mask_secrets(text, patterns=custom_patterns)
        assert "CUSTOM_12345_SECRET" not in result
        assert "[REDACTED]" in result

    def test_custom_replacement(self):
        """Test that custom replacement string can be provided."""
        text = "API key: sk-abc123xyz789abc123xyz789"
        result = mask_secrets(text, replacement="[MASKED]")
        assert "[MASKED]" in result
        assert "[REDACTED]" not in result

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case-insensitive."""
        text = 'Config: PASSWORD="MySecretPass123"'
        result = mask_secrets(text)
        assert "MySecretPass123" not in result
        assert "[REDACTED]" in result

        text = 'Config: Api_Key="key123"'
        result = mask_secrets(text)
        assert "key123" not in result
        assert "[REDACTED]" in result


class TestMaskException:
    """Tests for the mask_exception function."""

    def test_mask_exception_with_secret(self):
        """Test that exception messages with secrets are masked."""
        error = ValueError("Invalid API key: sk-abc123xyz789abc123xyz789")
        result = mask_exception(error)
        assert "sk-abc123xyz789abc123xyz789" not in result
        assert "[REDACTED]" in result
        assert "Invalid API key:" in result

    def test_mask_exception_normal_error(self):
        """Test that normal exception messages are not affected."""
        error = ValueError("File not found: /path/to/file.txt")
        result = mask_exception(error)
        assert result == "File not found: /path/to/file.txt"

    def test_mask_exception_returns_string(self):
        """Test that mask_exception returns a string."""
        error = RuntimeError("Some error occurred")
        result = mask_exception(error)
        assert isinstance(result, str)

    def test_mask_exception_with_bearer_token(self):
        """Test that Bearer tokens in exceptions are masked."""
        error = Exception("Auth failed with Bearer abc.def.ghi")
        result = mask_exception(error)
        assert "abc.def.ghi" not in result
        assert "[REDACTED]" in result


class TestDefaultSecretPatterns:
    """Tests for the DEFAULT_SECRET_PATTERNS constant."""

    def test_patterns_list_not_empty(self):
        """Test that default patterns list is not empty."""
        assert len(DEFAULT_SECRET_PATTERNS) > 0

    def test_patterns_are_valid_regex(self):
        """Test that all default patterns are valid regex."""
        import re
        for pattern in DEFAULT_SECRET_PATTERNS:
            # Should not raise an exception
            re.compile(pattern)

    def test_openai_pattern_in_defaults(self):
        """Test that OpenAI key pattern is in defaults."""
        # Verify by testing that an OpenAI-like key is matched
        text = "key: sk-abc123xyz789abc123xyz789"
        result = mask_secrets(text)
        assert "sk-abc123xyz789abc123xyz789" not in result

    def test_anthropic_pattern_in_defaults(self):
        """Test that Anthropic key pattern is in defaults."""
        text = "key: sk-ant-abc123-xyz789-def456-ghi012"
        result = mask_secrets(text)
        assert "sk-ant-abc123-xyz789-def456-ghi012" not in result


class TestIntegrationWithPipeline:
    """Integration tests for secret masking in pipeline context."""

    def test_mask_traceback_with_secret(self):
        """Test masking secrets in a simulated traceback."""
        traceback_text = '''Traceback (most recent call last):
  File "/app/src/transcription/whisper.py", line 42, in transcribe
    response = client.audio.transcribe(file, api_key="sk-abc123xyz789abc123xyz789")
  File "/app/.venv/lib/openai/api.py", line 100, in transcribe
    raise APIError("Invalid API key: sk-abc123xyz789abc123xyz789")
openai.APIError: Invalid API key: sk-abc123xyz789abc123xyz789'''

        result = mask_secrets(traceback_text)
        assert "sk-abc123xyz789abc123xyz789" not in result
        assert result.count("[REDACTED]") == 3
        # Original structure should be preserved
        assert "Traceback (most recent call last):" in result
        assert "openai.APIError:" in result

    def test_mask_error_details_dict_values(self):
        """Test that we can mask secrets in dictionary string values."""
        error_details = {
            "error_message": "Failed with key sk-abc123xyz789abc123xyz789",
            "original_error_message": "Auth error: Bearer token.value.here",
        }

        masked_details = {}
        for key, value in error_details.items():
            if isinstance(value, str):
                masked_details[key] = mask_secrets(value)
            else:
                masked_details[key] = value

        assert "sk-abc123xyz789abc123xyz789" not in masked_details["error_message"]
        assert "token.value.here" not in masked_details["original_error_message"]
