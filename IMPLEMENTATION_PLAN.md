# Implementation Plan: Device Passthrough, Date/Location Fields, Feedback Template

**Generated:** 2026-01-26
**Source:** User requirements (3 changes)
**Total Phases:** 3
**Dependencies:** None external

---

## Executive Summary

Three changes to the voice-capture pipeline:

1. **Device passthrough** -- Remove the `Device` enum and alias mapping. Pass whatever text the iOS Shortcut sends as the device value straight through the pipeline to Notion. This simplifies the code and allows future devices without code changes.

2. **Date and location from API** -- Accept `date` and `location` fields in the HTTP upload API. Use the incoming date (with its timezone) as the capture timestamp for the Notion Date property. Store and pass the location text to a Location property in Notion.

3. **Feedback template** -- New content type for employee performance feedback. Extracts employee name (also added as a tag), feedback type, context, and actionable items. Designed for short voice memos like "Feedback on Libby. She did a great job on the Chick-fil-A presentation today."

---

## Plan Overview

| Phase | Focus | Key Deliverables | Dependencies |
|-------|-------|-----------------|--------------|
| 1 | Device passthrough | Remove Device enum, pass raw text, update TextFormatter | None |
| 2 | Date and location fields | New API fields, DB column, Notion property | Phase 1 |
| 3 | Feedback template | New YAML template, classification rules, Notion mapping | Phase 2 |

---

## Phase 1: Device Passthrough

**Goals:** Remove the Device enum and all mapping logic. Pass the raw device string from the API through the entire pipeline to Notion unchanged.

### Work Item 1.1: Remove Device Enum and Update CaptureRecord

**Affected files:**
- `src/models/capture.py`

**Tasks:**
- [ ] Remove the `Device` enum class entirely (lines 86-120)
- [ ] Change `CaptureRecord.device` field type from `Device` to `str`, default `"unknown"`
- [ ] Update `__post_init__` to remove Device enum conversion (line 187)
- [ ] Update `to_dict()` to use `self.device` directly instead of `self.device.value` (line 210)
- [ ] Update `to_db_dict()` to use `self.device` directly instead of `self.device.value` (line 376)
- [ ] Update `from_dict()` to use `data.get("device", "unknown")` directly as string (line 265)
- [ ] Update `from_db_row()` to use `row.get("device", "unknown")` directly as string (line 347)
- [ ] Remove the `from src.models.capture import Device` usage throughout codebase

**Acceptance criteria:**
- [ ] `CaptureRecord.device` is a plain `str`
- [ ] No `Device` enum exists in the codebase
- [ ] All serialization/deserialization passes raw device string

### Work Item 1.2: Update HTTP Server

**Affected files:**
- `src/http/server.py`

**Tasks:**
- [ ] Remove `from src.models.capture import Device` import (line 26)
- [ ] Remove `device = Device.from_string(device_str)` call (line 358)
- [ ] Pass `device_str` directly to `db.insert_capture(device=device_str)` (line 364)
- [ ] Stop lowercasing the device string on line 303 -- preserve original casing from iOS
- [ ] Update log line to use `device_str` instead of `device.value` (line 374)

**Acceptance criteria:**
- [ ] API accepts any device text and passes it through unchanged
- [ ] Device casing from iOS is preserved (e.g., "iPhone" stays "iPhone")

### Work Item 1.3: Update TextFormatter

**Affected files:**
- `src/pipeline/text_formatter.py`

**Tasks:**
- [ ] Update `format_device_name()` to return the raw device string as-is, instead of mapping to known values
- [ ] If device is empty or None, return "Unknown" (keep existing fallback)
- [ ] Remove the hardcoded "Watch"/"Phone" mapping

**Acceptance criteria:**
- [ ] `format_device_name("iPhone")` returns `"iPhone"`
- [ ] `format_device_name("Apple Watch")` returns `"Apple Watch"`
- [ ] `format_device_name(None)` returns `"Unknown"`
- [ ] `format_device_name("")` returns `"Unknown"`

### Work Item 1.4: Update Tests

**Affected files:**
- `tests/test_models.py`
- `tests/test_pipeline.py`
- `tests/pipeline/test_text_formatter.py`
- `tests/http/test_server.py`
- Any other test files referencing `Device` enum

**Tasks:**
- [ ] Remove all `Device` enum imports and references from tests
- [ ] Update test assertions for device to use raw strings
- [ ] Update `TextFormatter` tests for new passthrough behavior
- [ ] Add test: arbitrary device strings pass through correctly
- [ ] Verify all existing tests pass with string device values

**Acceptance criteria:**
- [ ] All tests pass
- [ ] No references to `Device` enum remain in test files

### Phase 1 Completion Checklist
- [ ] Device enum fully removed
- [ ] Raw device text flows from API to Notion unchanged
- [ ] All tests pass
- [ ] No breaking changes to existing captures in DB (they already store strings)

---

## Phase 2: Date and Location Fields

**Goals:** Accept `date` and `location` fields from the iOS Shortcut HTTP upload. Use the incoming date as the Notion Date property. Pass location text to a Location rich_text property in Notion.

### Work Item 2.1: Add Location Column to Database Schema

**Affected files:**
- `src/db/connection.py`

**Tasks:**
- [ ] Add `location TEXT` column to captures table in SCHEMA_SQL (after `source` line)
- [ ] Add ALTER TABLE migration for existing databases (in ConnectionPool.initialize)

**Implementation notes:**
- SQLite `CREATE TABLE IF NOT EXISTS` will not add columns to existing tables
- Need to check if column exists and ALTER TABLE if not

**Acceptance criteria:**
- [ ] New databases have `location` column
- [ ] Existing databases get `location` column via migration

### Work Item 2.2: Update Database Layer

**Affected files:**
- `src/db/database.py`
- `src/db/repositories.py` (CaptureRepository)
- `src/db/models.py` (CaptureRow)

**Tasks:**
- [ ] Add `location` parameter to `Database.insert_capture()` and `CaptureRepository.insert()`
- [ ] Update INSERT SQL to include `location` column
- [ ] Update `CaptureRow` dataclass/namedtuple to include `location` field
- [ ] Ensure `location` is read back from DB rows

**Acceptance criteria:**
- [ ] `insert_capture()` accepts optional `location` parameter
- [ ] Location is stored and retrievable from database

### Work Item 2.3: Update CaptureRecord Model

**Affected files:**
- `src/models/capture.py`

**Tasks:**
- [ ] Add `location: Optional[str] = None` field to CaptureRecord
- [ ] Update `to_dict()`, `to_db_dict()`, `from_dict()`, `from_db_row()` to handle location

**Acceptance criteria:**
- [ ] CaptureRecord serializes/deserializes location correctly

### Work Item 2.4: Update HTTP Server to Accept Date and Location

**Affected files:**
- `src/http/server.py`

**Tasks:**
- [ ] Add parsing for `date` form field in multipart reader loop
- [ ] Add parsing for `location` form field in multipart reader loop
- [ ] When `date` is provided, parse it with `dateutil.parser.parse()` and use as `captured_at`
- [ ] Pass `location` to `db.insert_capture(location=location_str)`
- [ ] Handle date parsing errors gracefully (fall back to current time)

**Implementation notes:**
- iOS Shortcuts send dates in various formats; use `python-dateutil` for flexible parsing
- Preserve timezone information from the incoming date string
- Add `python-dateutil` to dependencies if not already present

**Acceptance criteria:**
- [ ] API accepts `date` field and uses it as capture timestamp
- [ ] API accepts `location` field and stores it
- [ ] Missing date/location fields work as before (backward compatible)
- [ ] Invalid date format falls back gracefully

### Work Item 2.5: Update Notion Integration for Location

**Affected files:**
- `src/notion/client.py`
- `src/notion/property_mapper.py`

**Tasks:**
- [ ] Add `location: Optional[str] = None` to `CaptureMetadata` dataclass
- [ ] In `_build_template_properties()`, add Location property when metadata.location is present
- [ ] Create `create_location_property()` helper in property_mapper.py (rich_text, same pattern as device)

**Acceptance criteria:**
- [ ] Location text appears in Notion as a "Location" property
- [ ] Missing location produces no Location property

### Work Item 2.6: Update Orchestrator to Pass Location and Date

**Affected files:**
- `src/pipeline/orchestrator.py`

**Tasks:**
- [ ] In `_do_posting()`, read location from capture record and include in CaptureMetadata
- [ ] Ensure `captured_at` from the DB record (now set from API date) flows to Notion Date property
- [ ] The captured_at flow should already work since it's read from the DB row

**Acceptance criteria:**
- [ ] Location from API appears on Notion page
- [ ] Date from API (with timezone) is used as Notion Date property

### Work Item 2.7: Update Tests for Date and Location

**Affected files:**
- `tests/http/test_server.py`
- `tests/test_db.py`
- `tests/test_pipeline.py`
- `tests/test_notion.py`
- `tests/test_models.py`

**Tasks:**
- [ ] Add test: HTTP upload with date field sets captured_at correctly
- [ ] Add test: HTTP upload with location field stores and retrieves correctly
- [ ] Add test: HTTP upload without date/location fields works as before
- [ ] Add test: Invalid date format falls back gracefully
- [ ] Add test: Location appears in Notion properties
- [ ] Update any existing tests affected by new parameters

**Acceptance criteria:**
- [ ] All tests pass
- [ ] New fields have test coverage

### Work Item 2.8: Update Documentation

**Affected files:**
- `docs/IOS_SHORTCUT_HTTP.md`

**Tasks:**
- [ ] Add `date` and `location` fields to the API reference table
- [ ] Update the form fields table in shortcut creation section
- [ ] Update the request format example

**Acceptance criteria:**
- [ ] Documentation reflects new API fields

### Phase 2 Completion Checklist
- [ ] Date from API used as Notion Date property with timezone
- [ ] Location from API stored in DB and shown in Notion
- [ ] Backward compatible (missing fields work as before)
- [ ] All tests pass
- [ ] Documentation updated

---

## Phase 3: Feedback Template

**Goals:** Add a new "Feedback" content type for employee performance feedback. Extract employee name as a tag. Include fields appropriate for compiling into performance reviews.

### Work Item 3.1: Create Feedback Template YAML

**Affected files:**
- `config/templates/feedback.yaml` (new file)

**Tasks:**
- [ ] Create `feedback.yaml` following existing template structure
- [ ] Define fields:
  - `title` (title) -- Clean feedback title, e.g., "Libby - Chick-fil-A Presentation Performance". notion_property: Title
  - `date` (date) -- Capture timestamp. notion_property: Date
  - `employee_name` (rich_text) -- Name of the employee receiving feedback. notion_property: Employee
  - `feedback_type` (select) -- Positive, Constructive, Observation. notion_property: Feedback Type
  - `summary` (rich_text) -- 2-3 sentence summary of the feedback
  - `context` (rich_text) -- Project, client, or situation context
  - `actionable_items` (rich_text) -- Specific behaviors to continue or improve
  - `tags` (multi_select) -- Include employee name as first tag + topic tags. notion_property: Tags
  - `transcription` (rich_text) -- Full raw transcript. notion_property: Transcription
- [ ] Define triggers/patterns: "feedback on", "feedback for", "feedback about", "performance note", "note on [name]'s performance"
- [ ] Define indicators: employee evaluation language, performance observations, behavior descriptions
- [ ] Create page_body_template with sections for Summary, Context, Actionable Items, Raw Transcript

**Acceptance criteria:**
- [ ] Template YAML validates and loads correctly
- [ ] All fields have extraction guidance
- [ ] Employee name extraction guidance includes instruction to add to tags

### Work Item 3.2: Update Classification Rules

**Affected files:**
- `src/classification/prompt_builder.py`

**Tasks:**
- [ ] Add feedback template indicators to `_build_rules_section()`:
  - "feedback on", "feedback for", "feedback about" -> "feedback" template
  - "performance note", "note about [name]'s performance" -> "feedback" template
  - "This is feedback" -> "feedback" template, confidence 0.95+
- [ ] Add "feedback" to template selection list in `_build_response_format_section()`
- [ ] Add instruction: "For feedback template, ALWAYS include the employee name as the FIRST tag"
- [ ] Add feedback to overlap handling in `_build_overlap_section()`:
  - "Feedback vs Journal": If about a specific employee's performance, use Feedback; if personal reflection on team dynamics, use Journal
  - "Feedback vs Task": If observing past performance, use Feedback; if assigning action items, use Task

**Acceptance criteria:**
- [ ] "Feedback on Libby. She did a great job..." classifies as feedback with high confidence
- [ ] "This is feedback on John" classifies as feedback, confidence 0.95+
- [ ] Employee name appears in tags

### Work Item 3.3: Update Tests for Feedback Template

**Affected files:**
- `tests/test_classification.py`
- `tests/test_template_loader.py`

**Tasks:**
- [ ] Add test: feedback template loads correctly from YAML
- [ ] Add test: feedback template has correct fields defined
- [ ] Add test: feedback triggers include expected patterns

**Acceptance criteria:**
- [ ] All tests pass
- [ ] Feedback template has test coverage

### Phase 3 Completion Checklist
- [ ] Feedback template YAML created and loads
- [ ] Classification correctly identifies feedback captures
- [ ] Employee name extracted and added to tags
- [ ] Notion page created with all feedback properties (Employee, Feedback Type, etc.)
- [ ] All tests pass

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Existing DB missing location column | Medium | Add ALTER TABLE migration in connection pool init |
| Notion property auto-creation fails | Low | Properties auto-create on first use via Notion API |
| iOS date format variations | Medium | Use python-dateutil for flexible parsing |
| Device enum removal breaks tests | Low | Straightforward string replacement |

---

## Success Metrics

- [ ] All 3 changes implemented and tested
- [ ] All existing tests still pass
- [ ] New tests added for each change
- [ ] Pipeline processes captures with new fields end-to-end
- [ ] Notion pages display device (raw text), date (from API), location, and feedback type correctly
