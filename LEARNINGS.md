# Learnings Log

This file captures issues encountered during development and their solutions to prevent recurrence.

---

## Summary

Key learnings from the Voice Capture to Notion Pipeline implementation:

1. **Pydantic v2 requires separate pydantic-settings package** — Unlike v1, settings management is now in a separate package that must be explicitly installed.

2. **Use validation_alias for environment variable mapping** — When Pydantic field names differ from env var names (especially with nested settings), explicit `validation_alias` prevents silent failures.

3. **Magic bytes validation beats extension checks** — File validation via magic bytes (first bytes of file) is more reliable than trusting file extensions for audio format detection.

4. **Async SQLite needs careful transaction handling** — aiosqlite works well but requires explicit transaction management for multi-step operations to ensure atomicity.

5. **Exponential backoff with jitter prevents thundering herd** — Adding 10% random jitter to retry delays prevents synchronized retries across multiple requests.

6. **Confidence thresholds need fallback templates** — Classification systems should always have a fallback (General template) when confidence is below threshold to prevent data loss.

7. **Circuit breakers protect against cascade failures** — For sustained API failures, circuit breaker pattern (temporary disable after N failures) prevents resource exhaustion.

8. **Pushover rate limiting requires client-side throttling** — Even with retry logic, notification spam protection requires tracking recent sends at the application level.

9. **Jinja2 templates in YAML need careful escaping** — Embedding Jinja2 templates in YAML config files requires attention to brace escaping and multiline string handling.

10. **Sparse week detection improves synthesis quality** — Prompting for supplemental input when capture count is low (< 3) produces more useful weekly summaries.

---

## 2026-01-20

### Missing pydantic-settings module

**Problem:** Tests failed with ModuleNotFoundError for pydantic-settings. The pydantic-settings package is separate from the main pydantic package in Pydantic v2.

**Solution:** Install pydantic-settings via pip: `pip install pydantic-settings`

**Prevention:** Verify all dependencies are installed in CI/CD pipelines. Ensure requirements.txt explicitly lists pydantic-settings as a separate dependency from pydantic.

---

### PathsSettings environment variables not being read

**Problem:** PathsSettings fields were not picking up values from environment variables due to a naming mismatch. The Pydantic settings model expected different env var names than what was being provided.

**Solution:** Added `validation_alias` to Path fields in the settings model to explicitly map the expected environment variable names to the model fields.

**Prevention:** When using Pydantic settings with custom environment variable naming conventions, always use explicit `validation_alias` (or `alias`) to ensure the mapping is clear and predictable. This is especially important when the field name differs from the env var name or when using nested settings classes with prefixes.
