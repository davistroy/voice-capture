# Learnings Log

This file captures issues encountered during development and their solutions to prevent recurrence.

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
