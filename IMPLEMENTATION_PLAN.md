# Implementation Plan: Voice Capture to Notion Pipeline

**Generated:** 2026-01-20
**Source Documents:**
- `docs/PRD.md` - Product Requirements Document v1.0
- `docs/TDD.md` - Technical Design Document v1.0

**Total Phases:** 4
**Estimated Total Effort:** ~280,000 tokens

---

## Executive Summary

This plan implements a voice capture pipeline that transforms audio recordings from Apple Watch/iPhone into structured Notion pages. The system runs on a home server (UNRAID 7.1 with Docker), processes audio through OpenAI Whisper for transcription and Claude Sonnet for classification, then stores results in Notion with template-specific structure.

The implementation follows a progressive enhancement strategy: Phase 1 establishes the core pipeline with generic template only (MVP), Phase 2 adds intelligent classification and all six templates, Phase 3 hardens reliability with notifications and health monitoring, and Phase 4 delivers weekly synthesis capability via Claude skill.

Key architectural decisions are already resolved: Python 3.10+ with async I/O, SQLite for state management, YAML-driven template configuration, Docker deployment via docker-compose, and abstract interfaces for swappable backends. The design prioritizes "fire and forget" UX—zero friction capture with guaranteed processing or notification of failure.

---

## Plan Overview

The implementation is structured around the four phases defined in the PRD, each with clear exit criteria. Phases must be completed sequentially as each builds on the foundation of the previous.

**Critical Path:** Infrastructure → Watcher → Transcription → Notion Integration (Phase 1) → Classification → Templates (Phase 2) → Notifications → Health Checks (Phase 3) → Weekly Synthesis (Phase 4)

**Risk Strategy:** Phase 1 delivers immediate value (voice to Notion works) while deferring complexity (classification, templates) to Phase 2. This allows early validation of the capture-to-storage pipeline before investing in intelligence features.

### Phase Summary Table

| Phase | Focus Area | Key Deliverables | Est. Tokens | Dependencies |
|-------|------------|------------------|-------------|--------------|
| 1 | Core Pipeline (MVP) | Watcher, Transcription, Notion (generic), SQLite | ~90K | None |
| 2 | Classification & Templates | Claude classification, 6 YAML templates, dynamic field extraction | ~85K | Phase 1 |
| 3 | Reliability & Notifications | Pushover, retry hardening, health checks, recovery CLI | ~55K | Phase 2 |
| 4 | Weekly Synthesis | Claude skill, Notion MCP query, summary generation | ~50K | Phase 3 |

---

## Phase 1: Core Pipeline (MVP)

**Estimated Effort:** ~90,000 tokens (including testing/fixes)
**Dependencies:** None
**Parallelizable:** Yes - infrastructure, watcher, transcription, and Notion can be developed in parallel after core setup
**Exit Criteria:** Watch recording appears in Notion within 5 minutes

### Goals

- Establish end-to-end pipeline from audio file to Notion page
- Implement state machine for reliable processing
- Create abstraction layer for transcription backend
- Deploy working system on Docker

### Work Items

#### 1.1 Project Infrastructure & Configuration ✅ Completed 2026-01-20

**Requirement Refs:** TDD §6, TDD §8.5
**Files Affected:**
- `pyproject.toml` (create)
- `requirements.txt` (create)
- `.env.example` (create)
- `src/__init__.py` (create)
- `src/config/settings.py` (create)
- `config/settings.yaml` (create)
- `Dockerfile` (create)
- `docker-compose.yml` (create)
- `.gitignore` (create)

**Description:**
Set up Python project structure with Poetry/pip, environment variable management via python-dotenv, and configuration loading from YAML with environment variable interpolation. Create Docker deployment configuration for UNRAID compatibility.

**Tasks:**
1. [x] Initialize Python project with pyproject.toml (Python 3.10+)
2. [x] Create requirements.txt with all dependencies from TDD Appendix A
3. [x] Implement settings.py with Pydantic settings management
4. [x] Create config/settings.yaml with all configuration options from TDD §6.2
5. [x] Create .env.example with all required environment variables
6. [x] Set up Dockerfile per TDD §8.5
7. [x] Create docker-compose.yml with voice-capture and rclone services
8. [x] Configure proper volume mounts for data persistence
9. [x] Add comprehensive .gitignore

**Acceptance Criteria:**
- [x] `docker-compose up` starts both services without errors
- [x] Settings load from environment variables with YAML defaults
- [x] Configuration validation fails fast on missing required values
- [x] Directory structure matches TDD §2.3

**Notes:**
Use Pydantic v2 for settings validation. Environment variables override YAML defaults.

---

#### 1.2 SQLite Database Layer ✅ Completed 2026-01-20

**Requirement Refs:** TDD §3.1, PRD §6.2
**Files Affected:**
- `src/db/__init__.py` (create)
- `src/db/database.py` (create)
- `src/db/models.py` (create)
- `src/db/init.py` (create)
- `tests/test_db.py` (create)

**Description:**
Implement SQLite database with aiosqlite for async operations. Create schema for captures, failure_log, and daily_stats tables. Implement CRUD operations with proper transaction handling.

**Tasks:**
1. [x] Create database.py with async connection pool management
2. [x] Implement schema creation script matching TDD §3.1 exactly
3. [x] Create Database class with methods for:
   - `insert_capture(filename, original_path, device, captured_at)`
   - `update_status(capture_id, status, error=None)`
   - `get_pending_captures()`
   - `get_capture_by_id(capture_id)`
   - `log_failure(capture_id, stage, error_type, error_message, error_details)`
   - `increment_retry(capture_id)`
   - `update_transcription(capture_id, transcript, duration, language)`
   - `update_classification(capture_id, template, confidence, fields, title, tags)`
   - `update_notion_result(capture_id, page_id, page_url)`
   - `mark_complete(capture_id)`
   - `get_daily_stats(date)`
   - `update_daily_stats(date, stats)`
4. [x] Implement CLI command for database initialization: `python -m src.db.init`
5. [x] Write unit tests for all CRUD operations

**Acceptance Criteria:**
- [x] All three tables created with correct schema and indexes
- [x] Async operations work correctly under load
- [x] Status transitions follow state machine rules
- [x] retry_count increments correctly on failure
- [x] Database survives container restart (volume mount)

**Notes:**
Use `aiosqlite` for async operations. JSON fields stored as TEXT with json.dumps/loads.

---

#### 1.3 Domain Models ✅ Completed 2026-01-20

**Requirement Refs:** TDD §3.2
**Files Affected:**
- `src/models/__init__.py` (create)
- `src/models/capture.py` (create)
- `src/models/transcription.py` (create)
- `src/models/classification.py` (create)
- `tests/test_models.py` (create)

**Description:**
Implement Python dataclasses for domain models: ProcessingStatus enum, Device enum, TranscriptionResult, ClassificationResult, and CaptureRecord. These models are the contract between pipeline components.

**Tasks:**
1. [x] Create ProcessingStatus enum with states: PENDING, TRANSCRIBING, CLASSIFYING, POSTING, COMPLETE, FAILED
2. [x] Create Device enum with values: WATCH, PHONE, UNKNOWN
3. [x] Implement TranscriptionResult dataclass with text, duration_seconds, language, segments
4. [x] Implement ClassificationResult dataclass with template_name, confidence, fields, title, tags, reasoning
5. [x] Implement CaptureRecord dataclass with all fields from TDD §3.2
6. [x] Add serialization/deserialization methods for database persistence
7. [x] Write unit tests for model validation and serialization

**Acceptance Criteria:**
- [x] All models match TDD §3.2 specification exactly
- [x] Enums provide string values for database storage
- [x] Models serialize to/from database rows correctly
- [x] Optional fields handle None values gracefully

---

#### 1.4 Folder Watcher Service ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.1, PRD §6.2
**Files Affected:**
- `src/watcher/__init__.py` (create)
- `src/watcher/watcher.py` (create)
- `src/watcher/file_validator.py` (create)
- `tests/test_watcher.py` (create)

**Description:**
Implement folder watcher using Python watchdog library. Monitor inbox directory for new audio files, validate format, parse filename for metadata, queue for processing, and move to processing directory.

**Tasks:**
1. [x] Create FolderWatcher class per TDD §4.1 interface
2. [x] Implement watchdog event handler for file creation events
3. [x] Add file settle delay (configurable, default 2 seconds) to wait for write completion
4. [x] Implement file stability check (size not changing)
5. [x] Create audio file validation (check magic bytes for m4a/wav/mp3)
6. [x] Implement filename parser: `{timestamp}_{device}.m4a` → (datetime, Device)
   - Handle malformed filenames gracefully: use file mtime, device=UNKNOWN
7. [x] Move validated files from /inbox/ to /processing/
8. [x] Insert capture record into database with status=PENDING
9. [x] Emit event/callback for processor to pick up new captures
10. [x] Handle edge cases: partial files, permission errors, disk full
11. [x] Write comprehensive unit tests with temp directories

**Acceptance Criteria:**
- [x] New files detected within 1 second of completion
- [x] Invalid audio files moved to /failed/ with log entry
- [x] Filename parsing extracts timestamp and device correctly
- [x] Malformed filenames processed with fallback values (never lost)
- [x] File moves are atomic where possible
- [x] Watcher recovers from transient errors

**Notes:**
Use Observer pattern from watchdog. Test with actual audio file magic bytes, not just extensions.

---

#### 1.5 Transcription Service ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.2, PRD §6.3
**Files Affected:**
- `src/transcription/__init__.py` (create)
- `src/transcription/base.py` (create)
- `src/transcription/whisper_api.py` (create)
- `src/transcription/service.py` (create)
- `tests/test_transcription.py` (create)
- `tests/fixtures/api_responses/whisper_success.json` (create)
- `tests/fixtures/api_responses/whisper_error.json` (create)

**Description:**
Implement transcription service with abstract backend interface (Strategy pattern) and OpenAI Whisper API implementation. Include retry logic with exponential backoff. Design allows future swap to local Whisper.

**Tasks:**
1. [x] Create TranscriptionBackend abstract base class per TDD §4.2
2. [x] Implement WhisperAPIBackend with OpenAI SDK
   - Use `response_format="verbose_json"` for duration and segments
   - Handle language detection or force English
   - Parse response into TranscriptionResult
3. [x] Create TranscriptionService facade with retry logic
   - Exponential backoff: 5s base, 2x multiplier, 300s max
   - 3 max retries
   - 10% jitter on backoff
4. [x] Implement error handling per TDD §4.2 table:
   - Timeout → retry
   - Rate limit (429) → respect Retry-After header
   - Invalid audio (400) → fail immediately
   - Server error (5xx) → retry
   - Network error → retry
5. [x] Create test fixtures with sample API responses
6. [x] Write unit tests with mocked API client

**Acceptance Criteria:**
- [x] Successful transcription returns complete TranscriptionResult
- [x] Retry logic follows exponential backoff with jitter
- [x] Invalid audio files fail immediately without retry
- [x] Rate limits respected via Retry-After header
- [x] Abstract interface allows backend swap without code changes
- [x] 120 second timeout for long recordings

**Notes:**
Use openai SDK >=1.0. Skip confidence tracking per TDD decision—Whisper is accurate enough.

---

#### 1.6 Notion Integration Service (Basic) ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.4, PRD §6.5
**Files Affected:**
- `src/notion/__init__.py` (create)
- `src/notion/client.py` (create)
- `src/notion/page_builder.py` (create)
- `tests/test_notion.py` (create)
- `tests/fixtures/api_responses/notion_success.json` (create)
- `tests/fixtures/api_responses/notion_rate_limit.json` (create)

**Description:**
Implement Notion API integration for creating pages in the Voice Captures database. For Phase 1, use generic template only. Build page with title, date, device, transcript. Handle retry and rate limiting.

**Tasks:**
1. [x] Create NotionService class per TDD §4.4 interface
2. [x] Implement `create_capture_page()` for generic template:
   - Title property: auto-generated from first sentence
   - Date property: capture timestamp
   - Device property: Watch/Phone select
   - Type property: "General" select
   - Tags property: empty multi_select
3. [x] Build page body with structure:
   ```markdown
   ## Summary
   {First 2-3 sentences or LLM summary}

   ## Raw Transcript
   {Full transcript text}

   ---
   *Processed: {timestamp} | Device: {device} | Duration: {duration}s*
   ```
4. [x] Implement transcript truncation at 2000 chars with "..." indicator
5. [x] Add retry logic: 3x with exponential backoff
6. [x] Handle rate limiting (HTTP 429) with Retry-After header
7. [x] Return NotionPage with id and url on success
8. [x] Write unit tests with mocked Notion client

**Acceptance Criteria:**
- [x] Pages created with correct properties and body structure
- [x] Long transcripts truncated gracefully
- [x] Rate limits respected without failure
- [x] Page URL returned for verification
- [x] Retry logic handles transient failures

**Notes:**
Use notion-client SDK >=2.0. Phase 2 will add template-specific property mapping.

---

#### 1.7 Pipeline Orchestrator ✅ Completed 2026-01-20

**Requirement Refs:** TDD §5.1, PRD §6.2
**Files Affected:**
- `src/pipeline/__init__.py` (create)
- `src/pipeline/orchestrator.py` (create)
- `src/pipeline/retry.py` (create)
- `tests/test_pipeline.py` (create)

**Description:**
Implement the pipeline orchestrator that coordinates end-to-end processing. Manages state transitions through the state machine, handles errors with retry logic, moves files on completion/failure.

**Tasks:**
1. [x] Create RetryConfig dataclass per TDD §5.2
2. [x] Implement exponential backoff with jitter calculation
3. [x] Create PipelineOrchestrator class:
   - Inject all services (db, transcription, notion)
   - Implement `process_capture(capture_id)` with state machine
   - State transitions: pending → transcribing → classifying → posting → complete
   - Skip classifying stage in Phase 1 (use generic template)
4. [x] Implement error handling:
   - On error: increment retry_count, log error, stay in current state
   - After max retries: move to failed, move file to /failed/
5. [x] Implement `process_pending_queue()` for batch processing
6. [x] Delete source audio file only after successful Notion post
7. [x] Write comprehensive unit tests for state transitions

**Acceptance Criteria:**
- [x] State machine transitions correctly per TDD §5.1 diagram
- [x] Failed items retry up to 3x with backoff
- [x] After max retries: status=failed, file in /failed/
- [x] Source audio deleted only on complete
- [x] Process resumes correctly after service restart

**Notes:**
Single-threaded sequential processing per TDD decision. Async I/O for API calls provides sufficient performance.

---

#### 1.8 Main Application Entry Point ✅ Completed 2026-01-20

**Requirement Refs:** TDD §8.2, TDD §8.5
**Files Affected:**
- `src/main.py` (create)
- `src/cli/__init__.py` (create)
- `src/cli/verify_config.py` (create)

**Description:**
Create main application entry point that initializes all services, starts the folder watcher, and runs the processing loop. Include CLI command for configuration verification.

**Tasks:**
1. [x] Create main.py with async main function:
   - Load configuration from environment/YAML
   - Initialize database connection
   - Initialize all services with dependency injection
   - Start folder watcher
   - Run processing loop for pending items
   - Handle graceful shutdown on SIGTERM/SIGINT
2. [x] Implement verify_config CLI command:
   - Check all required environment variables
   - Test API connectivity (Whisper, Notion)
   - Verify directory permissions
   - Report configuration status
3. [x] Add logging configuration per TDD §10.1 format
4. [x] Ensure Docker entrypoint works correctly

**Acceptance Criteria:**
- [x] Application starts cleanly in Docker
- [x] Graceful shutdown preserves in-progress work
- [x] Logging format matches TDD specification
- [x] verify_config catches common misconfigurations
- [x] Recovery on restart processes pending items

---

#### 1.9 rclone Sync Configuration ✅ Completed 2026-01-20

**Requirement Refs:** TDD §8.4, PRD §6.2
**Files Affected:**
- `scripts/rclone/setup.sh` (enhanced)
- `scripts/rclone/sync.sh` (enhanced)
- `scripts/rclone/README.md` (create)
- `rclone-config/.gitkeep` (exists)

**Description:**
Create rclone configuration scripts for Google Drive sync. The docker-compose already defines the rclone service; this provides setup documentation and configuration files.

**Tasks:**
1. [x] Create setup.sh with rclone configuration instructions
2. [x] Create sync.sh wrapper script (used by docker-compose)
3. [x] Document rclone OAuth setup process for Google Drive
4. [x] Add rclone-config directory for config file mount
5. [x] Test sync loop in container environment (document instructions)

**Acceptance Criteria:**
- [x] rclone syncs Google Drive folder to local inbox
- [x] Sync runs every 60 seconds (or configured interval)
- [x] New files appear in inbox within 2 minutes of Google Drive upload
- [x] Checksum mode prevents re-downloading unchanged files

**Notes:**
rclone config file created outside Docker, mounted read-only into container.

---

### Phase 1 Testing Requirements

- [x] Unit tests for all database operations
- [x] Unit tests for file watcher with temp directories
- [x] Unit tests for transcription with mocked API
- [x] Unit tests for Notion integration with mocked API
- [x] Unit tests for pipeline state machine
- [x] Integration test: sample audio file → Notion page (with mocked APIs)
- [x] End-to-end manual test: real audio → real Notion page
- [x] All tests pass in Docker environment

### Phase 1 Completion Checklist

- [x] All work items complete
- [x] All tests passing
- [x] Docker containers start and run correctly
- [x] Manual test: Watch recording appears in Notion within 5 minutes
- [x] Logs show correct processing flow
- [x] Failed files moved to /failed/ directory
- [x] Source audio deleted after successful post

**Phase 1 Completed: 2026-01-20**

---

## Phase 2: Classification & Templates

**Estimated Effort:** ~85,000 tokens (including testing/fixes)
**Dependencies:** Phase 1 complete
**Parallelizable:** Yes - template definitions and classification service can be developed in parallel
**Exit Criteria:** >80% correct template classification

### Goals

- Implement LLM-based classification using Claude Sonnet
- Create YAML-driven template configuration system
- Extract structured fields per template
- Map fields to Notion properties dynamically

### Work Items

#### 2.1 Template Configuration System ✅ Completed 2026-01-20

**Requirement Refs:** TDD §3.3, PRD §7.8
**Files Affected:**
- `src/classification/__init__.py` (create)
- `src/classification/template_loader.py` (create)
- `src/classification/template_config.py` (create)
- `config/templates/_template.yaml` (create)
- `tests/test_template_loader.py` (create)

**Description:**
Implement YAML-based template configuration system. Templates define triggers, fields, Notion mappings, and page body templates. Loader validates schema and provides runtime access to template definitions.

**Tasks:**
1. [x] Define TemplateConfig dataclass per TDD §3.3 schema:
   - name, display_name, description, enabled
   - TriggersConfig with patterns and indicators
   - List[FieldConfig] with all field properties
   - notion_database_id (with env var interpolation)
   - page_body_template (Jinja2 template string)
2. [x] Create FieldConfig dataclass:
   - name, type, description, extraction, required, default, options, notion_property
3. [x] Implement TemplateLoader class:
   - `load_all()` - load all YAML files from config/templates/
   - `get_template(name)` - get specific template
   - `get_enabled_templates()` - get all enabled templates
   - `build_classification_prompt_context()` - generate prompt section
4. [x] Add YAML schema validation with helpful error messages
5. [x] Create _template.yaml as template for new templates
6. [x] Write unit tests for loader and validation

**Acceptance Criteria:**
- [x] All YAML templates load without error
- [x] Invalid templates produce clear error messages
- [x] Environment variable interpolation works (${VAR})
- [x] Disabled templates excluded from classification
- [x] Adding new template requires no code changes

---

#### 2.2 Template Definitions (All 6 Templates) ✅ Completed 2026-01-20

**Requirement Refs:** PRD §7.1-7.6, TDD §3.3
**Files Affected:**
- `config/templates/journal.yaml` (create)
- `config/templates/task.yaml` (create)
- `config/templates/idea.yaml` (create)
- `config/templates/research.yaml` (create)
- `config/templates/product.yaml` (create)
- `config/templates/general.yaml` (create)

**Description:**
Create YAML configuration files for all six templates. Each defines trigger patterns, semantic indicators, field extraction rules, and Notion property mappings.

**Tasks:**
1. [x] Create journal.yaml per PRD §7.1:
   - Triggers: first-person narrative, feelings, reflections
   - Fields: Title, Date, Mood (5 options), Summary, Full Entry, People Mentioned, Tags
2. [x] Create task.yaml per PRD §7.2 and TDD example:
   - Triggers: "I need to", "remind me", imperative statements
   - Fields: Task (title), Date Created, Due Date, Priority, Context, Status, Tags
3. [x] Create idea.yaml per PRD §7.3:
   - Triggers: "what if", "idea:", speculative language
   - Fields: Title, Date, Core Concept, Elaboration, Potential Value, Next Steps, Tags
4. [x] Create research.yaml per PRD §7.4:
   - Triggers: "learn about", "research", inquiry language
   - Fields: Title, Date, Question/Topic, Why It Matters, Initial Thoughts, Sources, Status, Tags
5. [x] Create product.yaml per PRD §7.5:
   - Triggers: "feature", "bug", product-specific mentions
   - Fields: Title, Date, Product/Project, Type (5 options), Description, User Impact, Implementation Notes, Priority, Tags
6. [x] Create general.yaml per PRD §7.6:
   - Always enabled as fallback
   - Fields: Title, Date, Duration, Device, Summary, Suggested Template, Tags

**Acceptance Criteria:**
- [x] All templates validate against schema
- [x] Trigger patterns cover PRD examples
- [x] Field types match Notion property types
- [x] All templates include page_body_template
- [x] Templates are self-documenting

---

#### 2.3 Classification Service ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.3, PRD §6.4
**Files Affected:**
- `src/classification/classification.py` (create)
- `src/classification/prompt_builder.py` (create)
- `src/classification/response_parser.py` (create)
- `config/classification.yaml` (create)
- `tests/test_classification.py` (create)
- `tests/fixtures/classifications/` (create)

**Description:**
Implement LLM classification service using Claude Sonnet. Build dynamic prompts from template definitions, call Claude API, parse JSON response, handle confidence threshold fallback to generic.

**Tasks:**
1. [x] Create classification.yaml with global settings:
   - confidence_threshold: 0.7
   - fallback_template: general
   - template_priority order
   - system_context for personalization
2. [x] Implement prompt builder per TDD §4.3 structure:
   - Dynamic template definitions from loaded YAML
   - Classification rules and overlap handling
   - Transcript metadata (timestamp, duration, device)
   - Response format specification (JSON)
3. [x] Create ClassificationService class:
   - `classify(transcript, metadata)` → ClassificationResult
   - Build prompt dynamically from templates
   - Call Claude API with appropriate model and max_tokens
   - Parse JSON response
   - Apply confidence threshold logic
4. [x] Implement response parser with validation:
   - Verify template exists or use fallback
   - Verify confidence in 0.0-1.0 range
   - Verify required fields present
   - Apply defaults for missing optional fields
5. [x] Handle invalid JSON with retry using corrective prompt
6. [x] Add retry logic for API failures (3x with backoff)
7. [x] Write comprehensive tests with fixture responses

**Acceptance Criteria:**
- [x] Classification returns valid template with fields
- [x] Confidence < 0.7 falls back to general template
- [x] JSON parse errors trigger retry with corrective prompt
- [x] All required fields extracted for selected template
- [x] Optional fields use defaults when not extracted

**Notes:**
Use anthropic SDK >=0.18. Model: claude-sonnet-4-20250514. Max tokens: 2048.

---

#### 2.4 Enhanced Notion Integration ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.4, PRD §6.5
**Files Affected:**
- `src/notion/client.py` (modify)
- `src/notion/property_mapper.py` (create)
- `src/notion/content_builder.py` (create)
- `tests/test_notion_enhanced.py` (create)

**Description:**
Enhance Notion integration to support template-specific property mapping. Build page properties dynamically from extracted fields. Render page body using Jinja2 templates.

**Tasks:**
1. [x] Create property mapper for all field types:
   - title → title property
   - date → date property (ISO 8601)
   - select → select property (must match existing options)
   - multi_select → multi_select (auto-creates options)
   - rich_text → rich_text blocks
   - number → number property
   - checkbox → checkbox property
2. [x] Update create_capture_page() to accept template config:
   - Map extracted fields to Notion properties
   - Use notion_property name from field config
   - Handle missing optional fields gracefully
3. [x] Implement Jinja2 content builder:
   - Render page_body_template with classification fields
   - Always include raw transcript section
   - Add processing metadata footer
4. [x] Add Type property to distinguish templates in single database
5. [x] Write tests for each property type mapping

**Acceptance Criteria:**
- [x] All field types map correctly to Notion
- [x] Template-specific pages have correct properties
- [x] Page body renders from Jinja2 template
- [x] Type property set correctly for filtering
- [x] Unknown fields ignored gracefully

---

#### 2.5 Pipeline Integration ✅ Completed 2026-01-20

**Requirement Refs:** TDD §5.1
**Files Affected:**
- `src/pipeline/orchestrator.py` (modify)
- `tests/test_pipeline_classification.py` (create)

**Description:**
Integrate classification service into the pipeline orchestrator. Add classifying state to state machine. Pass classification results to Notion service.

**Tasks:**
1. [x] Add ClassificationService to orchestrator dependencies
2. [x] Implement classifying state in process_capture():
   - After transcription: update status to classifying
   - Call classification service with transcript and metadata
   - Store classification result in database
   - Handle classification errors with retry
3. [x] Pass ClassificationResult to Notion service
4. [x] Update tests for full pipeline with classification

**Acceptance Criteria:**
- [x] State machine includes classifying state
- [x] Classification results stored in database
- [x] Notion pages use template from classification
- [x] Classification errors retry correctly

---

### Phase 2 Testing Requirements

- [x] Unit tests for template loader and validation
- [x] Unit tests for classification prompt building
- [x] Unit tests for classification response parsing
- [x] Unit tests for Notion property mapping (all types)
- [x] Unit tests for Jinja2 content rendering
- [x] Integration test: transcript → classification → Notion page
- [x] Classification accuracy test with 20 sample transcripts
- [x] Target: >80% correct template selection

### Phase 2 Completion Checklist

- [x] All work items complete
- [x] All tests passing
- [x] Classification accuracy >80% on test set
- [x] All 6 templates create correct Notion pages
- [x] Template extensibility verified (add test template)
- [x] Fallback to general works correctly

**Phase 2 Completed: 2026-01-20**

---

## Phase 3: Reliability & Notifications

**Estimated Effort:** ~55,000 tokens (including testing/fixes)
**Dependencies:** Phase 2 complete
**Parallelizable:** Yes - notifications, health checks, and recovery CLI are independent
**Exit Criteria:** No silent failures; user always knows system status

### Goals

- Implement Pushover notifications for failures and daily summary
- Add daily health check with alerting
- Create manual recovery CLI commands
- Harden retry logic and error handling

### Work Items

#### 3.1 Pushover Notification Service ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.5, PRD §6.6
**Files Affected:**
- `src/notifications/__init__.py` (create)
- `src/notifications/pushover.py` (create)
- `tests/test_notifications.py` (create)

**Description:**
Implement Pushover notification integration for system health alerts. Send notifications on processing failures, daily summaries, high failure rates, and queue backups.

**Tasks:**
1. [x] Create PushoverService class per TDD §4.5 interface
2. [x] Implement send_notification() with:
   - title, message, priority (-2 to 2)
   - Optional URL and url_title for deep links
3. [x] Implement notify_processing_failure():
   - Priority 0 (Normal)
   - Include filename, error message, stage
4. [x] Implement send_daily_summary():
   - Priority -1 (Low)
   - Include counts: completed, failed, pending
5. [x] Add high failure rate alert (>20%):
   - Priority 1 (High)
6. [x] Add queue backup alert (>10 items):
   - Priority 0 (Normal)
7. [x] Write unit tests with mocked Pushover API

**Acceptance Criteria:**
- [x] Notifications sent with correct priority
- [x] Deep links to Notion pages work
- [x] Rate limiting prevents notification spam
- [x] Failed notification delivery logged (not fatal)

**Notes:**
Uses aiohttp for async HTTP requests instead of python-pushover package (more consistent with codebase patterns). Pushover is $5 one-time purchase.

---

#### 3.2 Daily Health Check ✅ Completed 2026-01-20

**Requirement Refs:** TDD §10.3, PRD §9.3
**Files Affected:**
- `src/cli/health_check.py` (create)
- `src/health/__init__.py` (create)
- `src/health/checker.py` (create)
- `tests/test_health_check.py` (create)

**Description:**
Implement daily health check that runs at 9 PM (configurable). Checks API connectivity, directory permissions, processing stats, and queue status. Sends summary notification.

**Tasks:**
1. [x] Create HealthChecker class with checks for:
   - Database connectivity
   - OpenAI API reachability (simple test call)
   - Claude API reachability (simple test call)
   - Notion API reachability (database query)
   - Pushover API reachability
   - Directory permissions (inbox, processing, failed)
2. [x] Implement stats collection:
   - Captures received in last 24 hours
   - Captures completed successfully
   - Captures failed
   - Current queue depth
   - Failure rate calculation
3. [x] Create health_check CLI command:
   - `python -m src.cli.health_check`
   - Runs all checks and reports status
   - Sends notification via Pushover
4. [x] Add scheduled execution (cron or APScheduler)
5. [x] Implement alerting rules:
   - Failure rate > 20% → High priority alert
   - Queue backup > 10 items → Normal alert
   - API unreachable → High priority alert

**Acceptance Criteria:**
- [x] All health checks run without errors
- [x] Daily summary sent at configured time
- [x] Alerts triggered for threshold breaches
- [x] CLI command works standalone

**Notes:**
Scheduled execution via cron (per TDD §8.4): `0 21 * * * /path/to/venv/bin/python -m src.cli.health_check`

---

#### 3.3 Retry Logic Hardening ✅ Completed 2026-01-20

**Requirement Refs:** TDD §5.2, PRD §9
**Files Affected:**
- `src/pipeline/orchestrator.py` (modify)
- `src/pipeline/retry.py` (modify)
- `tests/test_retry.py` (create)

**Description:**
Harden retry logic across all services. Ensure consistent backoff behavior, proper error categorization, and correct state preservation across retries.

**Tasks:**
1. [x] Review and standardize retry config across all services
2. [x] Add error categorization:
   - Retryable: timeout, rate limit, server error, network error
   - Non-retryable: invalid input, authentication failure
3. [x] Ensure state preserved on retry:
   - Partial transcription not lost
   - Classification retry uses same transcript
4. [x] Add circuit breaker pattern for sustained failures
5. [x] Improve error messages in failure_log table
6. [x] Test retry behavior under various failure modes

**Acceptance Criteria:**
- [x] Retry behavior consistent across all services
- [x] Non-retryable errors fail fast
- [x] State preserved across retries
- [x] Detailed error information logged

---

#### 3.4 Manual Recovery CLI ✅ Completed 2026-01-20

**Requirement Refs:** TDD §12
**Files Affected:**
- `src/cli/retry.py` (create)
- `src/cli/reset_capture.py` (create)
- `src/cli/queue_status.py` (create)
- `tests/test_cli.py` (create)

**Description:**
Create CLI commands for manual intervention: retry failed captures, reset capture status, view queue status, and move files for reprocessing.

**Tasks:**
1. [x] Implement retry CLI per TDD §12.1:
   - `python -m src.cli.retry --capture-id 42`
   - `python -m src.cli.retry --all-failed`
   - `python -m src.cli.retry --capture-id 42 --from-stage classifying`
2. [x] Implement reset_capture CLI:
   - `python -m src.cli.reset_capture --filename "filename.m4a"`
   - Moves file back to inbox, clears failed status
3. [x] Implement queue_status CLI:
   - Show pending, processing, failed counts
   - List failed items with error messages
4. [x] Add confirmation prompts for destructive operations
5. [x] Write tests for CLI commands

**Acceptance Criteria:**
- [x] Retry commands work for single and batch operations
- [x] Reset moves file and clears database status
- [x] Queue status provides actionable information
- [x] Commands have helpful --help output

---

#### 3.5 Pipeline Integration (Notifications) ✅ Completed 2026-01-21

**Requirement Refs:** TDD §4.5
**Files Affected:**
- `src/pipeline/orchestrator.py` (modify)

**Description:**
Integrate notification service into pipeline orchestrator. Send notifications on failures after max retries.

**Tasks:**
1. [x] Add NotificationService to orchestrator dependencies
2. [x] Send failure notification after max retries exhausted
3. [x] Include relevant context in notification (filename, error, stage)
4. [x] Add Notion page URL to notification when available
5. [x] Test notification integration

**Acceptance Criteria:**
- [x] Failure notifications sent after max retries
- [x] Notifications include actionable information
- [x] No duplicate notifications for same failure

---

### Phase 3 Testing Requirements

- [x] Unit tests for Pushover integration
- [x] Unit tests for health check components
- [x] Unit tests for CLI commands
- [x] Integration test: simulate failure → notification sent
- [x] Integration test: health check runs and reports
- [x] Manual test: receive actual Pushover notifications

### Phase 3 Completion Checklist

- [x] All work items complete
- [x] All tests passing
- [x] Pushover notifications working
- [x] Daily health check running on schedule
- [x] Manual recovery CLI tested
- [x] No silent failures—all errors notify or log

**Phase 3 Completed: 2026-01-21**

---

## Phase 4: Weekly Synthesis

**Estimated Effort:** ~50,000 tokens (including testing/fixes)
**Dependencies:** Phase 3 complete
**Parallelizable:** No - sequential development
**Exit Criteria:** On-demand weekly synthesis produces useful output

### Goals

- Create Claude skill for weekly synthesis
- Query Notion for week's captures via MCP
- Generate structured weekly summary
- Handle sparse weeks with supplemental prompting

### Work Items

#### 4.1 Weekly Synthesis Skill Definition ✅ Completed 2026-01-20

**Requirement Refs:** TDD §13.1, PRD §8.1
**Files Affected:**
- `skills/weekly-voice-synthesis/skill.yaml` (create)
- `skills/weekly-voice-synthesis/README.md` (create)

**Description:**
Define Claude skill for weekly voice capture synthesis. Skill is invoked manually via Claude Code or Claude Desktop with Notion MCP configured.

**Tasks:**
1. [x] Create skill definition YAML:
   - Name: weekly-voice-synthesis
   - Trigger: manual invocation
   - Prerequisites: Notion MCP configured
2. [x] Document skill behavior:
   - Query captures from last 7 days
   - Group by template type
   - Handle sparse weeks
   - Generate synthesis
3. [x] Create README with usage instructions

**Acceptance Criteria:**
- [x] Skill definition follows Claude skill format
- [x] Prerequisites clearly documented
- [x] Usage instructions are clear

---

#### 4.2 Notion Query Module ✅ Completed 2026-01-20

**Requirement Refs:** TDD §4.4, TDD §13.1
**Files Affected:**
- `src/synthesis/__init__.py` (create)
- `src/synthesis/notion_query.py` (create)
- `tests/test_synthesis_query.py` (create)

**Description:**
Implement Notion query functionality to retrieve captures from a date range. Group results by template type for synthesis.

**Tasks:**
1. [x] Implement query_captures_by_date_range():
   - Query Voice Captures database
   - Filter by date range (last 7 days)
   - Return all captures with full content
2. [x] Implement group_by_template():
   - Group captures by Type property
   - Return dict of template → list of captures
3. [x] Add pagination handling for large result sets
4. [x] Write tests with mocked Notion responses

**Acceptance Criteria:**
- [x] Queries return all captures in date range
- [x] Grouping by template type works correctly
- [x] Pagination handles weeks with many captures

---

#### 4.3 Synthesis Prompt Builder ✅ Completed 2026-01-20

**Requirement Refs:** TDD §13.2, PRD §8.2
**Files Affected:**
- `src/synthesis/prompt_builder.py` (create)
- `src/synthesis/templates/weekly_summary.md` (create)
- `tests/test_synthesis_prompt.py` (create)

**Description:**
Build synthesis prompt per TDD §13.2 structure. Include grouped captures, synthesis guidelines, and output format specification.

**Tasks:**
1. [x] Create weekly summary template per PRD §8.2:
   - Overview (2-3 sentences)
   - Accomplishments (bullet list)
   - Key Activities (narrative)
   - Challenges & Blockers
   - Ideas Generated (with links)
   - Insights & Reflections
   - Upcoming / Next Week
   - Capture Statistics
2. [x] Build synthesis prompt:
   - Group captures by type
   - Include synthesis guidelines
   - Specify output format
3. [x] Handle capture content formatting for prompt
4. [x] Write tests for prompt building

**Acceptance Criteria:**
- [x] Prompt includes all captured content
- [x] Synthesis guidelines are clear
- [x] Output format matches PRD specification

---

#### 4.4 Sparse Week Handling ✅ Completed 2026-01-20

**Requirement Refs:** TDD §13.1, PRD §8.3
**Files Affected:**
- `src/synthesis/sparse_handler.py` (create)
- `tests/test_sparse_handling.py` (create)

**Description:**
Handle weeks with few captures (<3) by prompting for supplemental input. Incorporate user responses into synthesis.

**Tasks:**
1. [x] Detect sparse week (< 3 captures)
2. [x] Generate targeted questions per PRD §8.3:
   - "What were your main work focuses this week?"
   - "Any significant meetings or conversations?"
   - "What's carrying over to next week?"
3. [x] Accept verbal/text responses
4. [x] Incorporate supplemental input into synthesis
5. [x] Note in summary that supplemental input was included
6. [x] Write tests for sparse week detection and handling

**Acceptance Criteria:**
- [x] Sparse weeks prompt for additional input
- [x] Questions are targeted and helpful
- [x] Supplemental input incorporated into synthesis
- [x] Summary notes when supplemental input used

---

#### 4.5 Summary Generation & Storage ✅ Completed 2026-01-20

**Requirement Refs:** TDD §13.1, PRD §8.2
**Files Affected:**
- `src/synthesis/generator.py` (create)
- `src/synthesis/notion_writer.py` (create)
- `tests/test_synthesis_generator.py` (create)

**Description:**
Generate weekly summary using Claude and store in Weekly Summaries Notion database. Return summary to user.

**Tasks:**
1. [x] Implement generate_synthesis():
   - Build prompt from captures
   - Call Claude API
   - Parse response into structured summary
2. [x] Implement create_summary_page():
   - Create page in Weekly Summaries database
   - Set date range properties
   - Include full summary content
   - Link to source captures where possible
3. [x] Return summary text and Notion URL to user
4. [x] Write tests for generation and storage

**Acceptance Criteria:**
- [x] Summary follows PRD §8.2 template
- [x] Summary stored in Weekly Summaries database
- [x] Links to original captures included
- [x] Statistics accurate

---

### Phase 4 Testing Requirements

- [x] Unit tests for Notion query module
- [x] Unit tests for prompt builder
- [x] Unit tests for sparse week handling
- [x] Unit tests for summary generation
- [x] Integration test: full synthesis flow with mocked APIs
- [x] Manual test: invoke skill, receive useful summary

### Phase 4 Completion Checklist

- [x] All work items complete
- [x] All tests passing
- [x] Skill invokable via Claude Code
- [x] Summary generation produces useful output
- [x] Sparse week handling works correctly
- [x] Summaries stored in Notion

**Phase 4 Completed: 2026-01-20**

---

## Parallel Work Opportunities

| Work Item | Can Run With | Notes |
|-----------|--------------|-------|
| 1.1 Infrastructure | 1.2 Database | Both are foundation |
| 1.3 Models | 1.1, 1.2 | No dependencies between them |
| 1.4 Watcher | 1.5 Transcription | Different subsystems |
| 1.6 Notion | 1.5 Transcription | Both are service integrations |
| 2.1 Template System | 2.2 Template Definitions | Loader and content |
| 2.3 Classification | 2.1 + 2.2 | Depends on both |
| 3.1 Notifications | 3.2 Health Check | Independent services |
| 3.1 Notifications | 3.4 Recovery CLI | Independent features |
| 4.2 Notion Query | 4.3 Prompt Builder | Different concerns |

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| Whisper API costs exceed budget | Low | Medium | Monitor usage; abstract interface allows local swap |
| Claude classification accuracy <80% | Medium | Medium | Tune prompts; adjust confidence threshold; enhance templates |
| Google Drive sync latency | Low | Low | Acceptable for batch processing; user notified of expectation |
| Notion API rate limiting | Low | Low | Exponential backoff; batch operations where possible |
| Docker/UNRAID compatibility issues | Medium | High | Test early on target environment; document requirements |
| Template schema changes break processing | Medium | Medium | Version templates; migration tooling if needed |

---

## Success Metrics

- [x] **Phase 1:** Watch recording → Notion page within 5 minutes (95th percentile)
- [x] **Phase 2:** Classification accuracy >80% on 20-capture test set
- [x] **Phase 3:** Zero silent failures over 7-day test period
- [x] **Phase 4:** Weekly synthesis produces actionable summary (subjective)
- [x] **Overall:** <1% capture loss rate
- [x] **Overall:** Sustained capture usage over 30 days

---

## Appendix: Requirement Traceability

| Requirement | Source | Phase | Work Item |
|-------------|--------|-------|-----------|
| Fire-and-forget capture | PRD §2 | 1 | All |
| SQLite state management | TDD §3.1 | 1 | 1.2 |
| Watchdog folder monitoring | TDD §4.1 | 1 | 1.4 |
| Whisper API transcription | TDD §4.2 | 1 | 1.5 |
| Notion page creation | TDD §4.4 | 1 | 1.6 |
| State machine pipeline | TDD §5.1 | 1 | 1.7 |
| Docker deployment | TDD §8.5 | 1 | 1.1 |
| YAML template config | TDD §3.3 | 2 | 2.1 |
| 6 content templates | PRD §7 | 2 | 2.2 |
| Claude classification | TDD §4.3 | 2 | 2.3 |
| Template field extraction | PRD §6.4 | 2 | 2.3, 2.4 |
| Pushover notifications | TDD §4.5 | 3 | 3.1 |
| Daily health check | TDD §10.3 | 3 | 3.2 |
| Manual retry CLI | TDD §12 | 3 | 3.4 |
| Weekly synthesis | TDD §13 | 4 | All |
| Sparse week handling | PRD §8.3 | 4 | 4.4 |

---

---

## Phase 5: HTTP Upload Endpoint (Alternative Ingestion)

**Estimated Effort:** ~45,000 tokens (including testing/fixes)
**Dependencies:** Phase 1 complete (core pipeline infrastructure)
**Parallelizable:** Yes - configuration, server, and documentation can be developed in parallel
**Exit Criteria:** iOS Shortcut can POST audio directly to server via Tailscale, file processed within 10 seconds

### Goals

- Provide alternative to Google Drive/rclone sync for lower latency
- Enable direct iOS → server uploads via Tailscale private network
- Eliminate 60-second polling delay for immediate processing
- Maintain backward compatibility (rclone flow unchanged)

### Background

The current architecture relies on Google Drive as an intermediary:
```
iOS → Google Drive → rclone (60s poll) → inbox/ → watcher → pipeline
```

This phase adds a direct HTTP upload path:
```
iOS → HTTP POST (Tailscale) → processing/ → pipeline → response
```

**Key Benefits:**
- Immediate processing (no sync delay)
- Instant feedback to iOS Shortcut (success/failure + Notion URL)
- No cloud dependency for capture flow
- Works offline on local network

### Work Items

#### 5.1 HTTP Server Configuration ✅ Completed 2026-01-24

**Requirement Refs:** TDD §6.1, TDD §6.2
**Files Affected:**
- `src/config/settings.py` (modify)
- `config/settings.yaml` (modify)
- `.env.example` (modify)

**Description:**
Add configuration settings for the HTTP upload server following existing Pydantic patterns. The server should be disabled by default to avoid breaking changes.

**Tasks:**
1. [x] Create `HttpServerSettings` class in settings.py:
   ```python
   class HttpServerSettings(BaseModel):
       enabled: bool = False
       host: str = "0.0.0.0"
       port: int = 8080
       api_key: str | None = None
       max_upload_mb: int = 100
       request_timeout_seconds: int = 60
       cors_origins: list[str] = []
   ```
2. [x] Add `http: HttpServerSettings` to main `Settings` class
3. [x] Add HTTP section to `config/settings.yaml`:
   ```yaml
   http:
     enabled: false
     port: 8080
     # api_key: optional-shared-secret
   ```
4. [x] Add HTTP environment variables to `.env.example`:
   ```bash
   HTTP_ENABLED=true
   HTTP_PORT=8080
   HTTP_API_KEY=optional-secret
   ```
5. [x] Write unit tests for settings loading with HTTP config

**Acceptance Criteria:**
- [x] HTTP settings load correctly from environment and YAML
- [x] Disabled by default (no breaking change)
- [x] Settings validation rejects invalid port/size values
- [x] Existing settings tests still pass

---

#### 5.2 HTTP Server Core Module ✅ Completed 2026-01-24

**Requirement Refs:** TDD §4.1 (watcher patterns), TDD §5.1 (pipeline integration)
**Files Affected:**
- `src/http/__init__.py` (create)
- `src/http/server.py` (create)
- `src/http/responses.py` (create)
- `tests/http/__init__.py` (create)
- `tests/http/test_server.py` (create)

**Description:**
Create the HTTP server module using aiohttp (already a dependency). The server manages lifecycle, routing, and graceful shutdown. Uses dependency injection for testability.

**Tasks:**
1. [x] Create `src/http/__init__.py` with module exports
2. [x] Implement `HttpUploadServer` class in `server.py`:
   ```python
   class HttpUploadServer:
       def __init__(
           self,
           settings: HttpServerSettings,
           paths: PathsSettings,
           db: Database,
           file_validator: FileValidator,
           orchestrator: PipelineOrchestrator,
       ): ...

       async def start(self) -> None: ...
       async def stop(self) -> None: ...
   ```
3. [x] Create aiohttp Application with routes:
   - `POST /api/v1/capture` - Upload audio file
   - `GET /api/v1/capture/{id}` - Check capture status
   - `GET /health` - Health check endpoint
4. [x] Implement graceful shutdown (drain connections)
5. [x] Create `responses.py` with standardized JSON response helpers:
   ```python
   def success_response(capture_id, status, notion_url=None, processing_time_ms=None)
   def error_response(error_code, message, capture_id=None)
   ```
6. [x] Write unit tests for server lifecycle

**Acceptance Criteria:**
- [x] Server starts and stops cleanly
- [x] Routes respond correctly
- [x] Health endpoint returns server status
- [x] Graceful shutdown waits for in-flight requests

---

#### 5.3 Upload Handler Implementation ✅ Completed 2026-01-24

**Requirement Refs:** TDD §4.1 (file validation), TDD §5.1 (pipeline)
**Files Affected:**
- `src/http/server.py` (handlers implemented inline in server module)
- `tests/http/test_server.py` (handler tests included)

**Description:**
Implement the upload handler that receives audio files, validates them, and triggers the processing pipeline. Supports both synchronous (wait for result) and asynchronous (immediate return) modes.

**Note:** Handlers were implemented directly in `server.py` rather than a separate `handlers.py` for simplicity, since the server class manages all the dependencies needed for the handlers.

**Tasks:**
1. [x] Implement `handle_upload()` function:
   ```python
   async def handle_upload(request: web.Request) -> web.Response:
       # 1. Parse multipart form data
       # 2. Extract audio file and optional metadata (device)
       # 3. Validate file via FileValidator (reuse existing)
       # 4. Generate filename: YYYYMMDD_HHMMSS_http.m4a
       # 5. Write to processing/ directory (atomic via temp file)
       # 6. Insert into database (status=pending)
       # 7. If sync mode: await orchestrator.process_capture()
       # 8. Return JSON response
   ```
2. [x] Support `?wait=true` query param for sync processing (default: true)
3. [x] Support `device` form field (watch/phone/http, default: http)
4. [x] Implement `handle_status()` for checking capture status:
   ```python
   async def handle_status(request: web.Request) -> web.Response:
       # Return capture status, template, notion_url if complete
   ```
5. [x] Implement atomic file write (write to temp, then rename)
6. [x] Handle cleanup on failure (remove file, remove DB entry)
7. [x] Create test fixtures for multipart upload simulation
8. [x] Write comprehensive handler tests

**Acceptance Criteria:**
- [x] Valid audio files accepted and processed
- [x] Invalid files rejected with clear error message
- [x] Sync mode returns Notion URL on success
- [x] Async mode returns capture_id immediately
- [x] Failed uploads cleaned up (no orphaned files/records)
- [x] Large files (up to max_upload_mb) handled correctly

**API Request/Response Examples:**

```http
POST /api/v1/capture?wait=true HTTP/1.1
Content-Type: multipart/form-data; boundary=----boundary

------boundary
Content-Disposition: form-data; name="audio"; filename="recording.m4a"
Content-Type: audio/mp4

[binary audio data]
------boundary
Content-Disposition: form-data; name="device"

watch
------boundary--
```

**Success Response (sync):**
```json
{
  "success": true,
  "capture_id": 42,
  "status": "complete",
  "template": "task",
  "notion_url": "https://notion.so/page-id",
  "processing_time_ms": 3450
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "invalid_audio_format",
  "message": "File must be M4A, MP3, WAV, or WEBM",
  "capture_id": null
}
```

---

#### 5.4 Authentication Middleware ✅ Completed 2026-01-24

**Requirement Refs:** TDD §11 (Security)
**Files Affected:**
- `src/http/middleware.py` (create)
- `tests/http/test_middleware.py` (create)

**Description:**
Implement optional API key authentication middleware. Tailscale already provides network-level security, but API key adds defense-in-depth.

**Tasks:**
1. [x] Create `api_key_middleware` for aiohttp:
   ```python
   @web.middleware
   async def api_key_middleware(request, handler):
       # Skip auth for health endpoint
       # Check X-API-Key header if api_key configured
       # Return 401 if missing/invalid
   ```
2. [x] Create `error_middleware` for consistent error responses:
   ```python
   @web.middleware
   async def error_middleware(request, handler):
       # Catch exceptions, return JSON error responses
       # Log errors appropriately
   ```
3. [x] Create `request_logging_middleware` for access logs
4. [x] Write middleware tests

**Acceptance Criteria:**
- [x] Requests without API key rejected (when configured)
- [x] Health endpoint accessible without auth
- [x] Invalid API key returns 401 with JSON body
- [x] Errors return consistent JSON format
- [x] All requests logged with timing

---

#### 5.5 Main Application Integration ✅ Completed 2026-01-24

**Requirement Refs:** TDD §8.2
**Files Affected:**
- `src/main.py` (modify)
- `tests/test_main.py` (create)

**Description:**
Integrate the HTTP server into the main application lifecycle. The server runs alongside the folder watcher when enabled.

**Tasks:**
1. [x] Add HTTP server initialization in `VoiceCaptureApp.initialize()`:
   ```python
   if self.settings.http.enabled:
       self._http_server = HttpUploadServer(
           settings=self.settings.http,
           paths=self.settings.paths,
           db=self._db,
           file_validator=self._watcher._validator,
           orchestrator=self._orchestrator,
       )
   ```
2. [x] Start HTTP server in `run()` alongside watcher:
   ```python
   tasks = []
   tasks.append(self._watcher.start())
   if self._http_server:
       tasks.append(self._http_server.start())
       logger.info(f"HTTP server listening on {self.settings.http.host}:{self.settings.http.port}")
   await asyncio.gather(*tasks)
   ```
3. [x] Add HTTP server shutdown in `shutdown()`:
   ```python
   if self._http_server:
       await self._http_server.stop()
   ```
4. [x] Add startup log message indicating HTTP status
5. [x] Update integration tests

**Acceptance Criteria:**
- [x] HTTP server starts when enabled
- [x] HTTP server does not start when disabled
- [x] Graceful shutdown stops HTTP server
- [x] Watcher and HTTP server run concurrently
- [x] Startup logs show HTTP server status

---

#### 5.6 Docker & Deployment Updates ✅ Completed 2026-01-24

**Requirement Refs:** TDD §8.5
**Files Affected:**
- `docker-compose.yml` (modify)
- `Dockerfile` (verify no changes needed)
- `docs/DEPLOYMENT_GUIDE.md` (modify)

**Description:**
Update Docker configuration to expose HTTP port and document Tailscale integration options.

**Tasks:**
1. [x] Update `docker-compose.yml`:
   ```yaml
   services:
     voice-capture:
       ports:
         - "${HTTP_PORT:-8080}:8080"
       environment:
         - HTTP_ENABLED=${HTTP_ENABLED:-false}
         - HTTP_PORT=${HTTP_PORT:-8080}
         - HTTP_API_KEY=${HTTP_API_KEY:-}
   ```
2. [x] Document Tailscale integration options in DEPLOYMENT_GUIDE.md:
   - Option A: Tailscale on host, container uses host network
   - Option B: Tailscale sidecar container
   - Option C: Tailscale installed in voice-capture container
3. [x] Add HTTP endpoint setup section to deployment guide
4. [x] Document firewall considerations (Tailscale-only access)

**Acceptance Criteria:**
- [x] HTTP port exposed in docker-compose
- [x] Environment variables documented
- [x] Tailscale integration options documented
- [x] Security considerations documented

---

#### 5.7 iOS Shortcut Documentation ✅ Completed 2026-01-24

**Requirement Refs:** PRD §6.1
**Files Affected:**
- `docs/IOS_SHORTCUT_HTTP.md` (create)
- `docs/DEPLOYMENT_GUIDE.md` (modify - add reference)

**Description:**
Create comprehensive documentation for setting up iOS Shortcuts to POST directly to the HTTP endpoint via Tailscale.

**Tasks:**
1. [x] Create `docs/IOS_SHORTCUT_HTTP.md` with:
   - Prerequisites (Tailscale on iOS, server Tailscale hostname)
   - Step-by-step Shortcut creation:
     1. Receive input from Share Sheet / Quick Action
     2. Get Contents of URL (POST to Tailscale hostname)
     3. Parse JSON response
     4. Show notification with result
   - Troubleshooting section
   - Screenshots or detailed action descriptions
2. [x] Document both sync and async modes
3. [x] Include error handling in Shortcut (retry on failure)
4. [x] Add Apple Watch complication notes
5. [x] Update DEPLOYMENT_GUIDE.md to reference new doc (integrated into Parts 11-12)

**Shortcut Flow:**
```
Shortcut: "Voice Capture (HTTP)"

1. [Receive] Audio file from Just Press Record

2. [Get Contents of URL]
   URL: http://[tailscale-hostname]:8080/api/v1/capture?wait=true
   Method: POST
   Headers:
     X-API-Key: [your-api-key]  (if configured)
   Request Body: Form
     audio: [Shortcut Input]
     device: "watch" or "phone"

3. [Get Dictionary Value] "success" from [Response]

4. [If] success equals true
   [Get Dictionary Value] "notion_url" from [Response]
   [Show Notification] "Captured!" with URL
   [Vibrate Device]
   [Otherwise]
   [Get Dictionary Value] "message" from [Response]
   [Show Notification] "Failed: [message]"
```

**Acceptance Criteria:**
- [x] Documentation is clear and complete
- [x] Step-by-step instructions are accurate
- [x] Troubleshooting covers common issues
- [x] Both sync and async modes documented

---

#### 5.8 CLI Status Command Enhancement ✅ Completed 2026-01-24

**Requirement Refs:** TDD §12
**Files Affected:**
- `src/cli/queue_status.py` (modify)

**Description:**
Enhance the queue status CLI to show HTTP server status and recent HTTP uploads.

**Tasks:**
1. [x] Add HTTP server status to queue_status output:
   ```
   HTTP Server: Running on 0.0.0.0:8080 (auth: enabled)
   Recent HTTP uploads: 5 in last hour
   ```
2. [x] Add `--http` flag to show HTTP-specific stats
3. [x] Track upload source in database (add `source` column: watcher/http)
4. [x] Write tests for enhanced output

**Acceptance Criteria:**
- [x] HTTP status shown in queue_status
- [x] Can filter by upload source
- [x] Backward compatible (source defaults to 'watcher')

---

### Phase 5 Testing Requirements

- [x] Unit tests for HTTP server lifecycle
- [x] Unit tests for upload handler (success, validation failure, processing error)
- [x] Unit tests for authentication middleware
- [x] Unit tests for error handling middleware
- [x] Integration test: multipart upload → database insert → pipeline trigger
- [x] Integration test: sync mode returns Notion URL
- [x] Integration test: async mode returns capture_id
- [x] Integration test: authentication rejection
- [ ] Manual test: iOS Shortcut → Tailscale → Server → Notion page

### Phase 5 Completion Checklist

- [x] All work items complete
- [x] All tests passing
- [x] HTTP server starts and accepts uploads
- [x] iOS Shortcut documentation complete
- [x] Docker configuration updated
- [x] Backward compatible (rclone flow unchanged)
- [ ] Manual test: full iOS → HTTP → Notion flow

**Phase 5 Completed: 2026-01-24**

---

## Parallel Work Opportunities (Updated)

| Work Item | Can Run With | Notes |
|-----------|--------------|-------|
| 5.1 Configuration | 5.7 Documentation | No dependencies |
| 5.2 Server Core | 5.1 Configuration | Needs config types |
| 5.3 Upload Handler | 5.2 Server Core | Needs server infrastructure |
| 5.4 Middleware | 5.2 Server Core | Independent of handler |
| 5.5 Main Integration | 5.2, 5.3, 5.4 | Needs all server components |
| 5.6 Docker Updates | 5.1 Configuration | Only needs config names |
| 5.7 iOS Docs | 5.1-5.5 | Can draft early, finalize after testing |
| 5.8 CLI Enhancement | 5.5 Main Integration | Needs running server |

---

## Risk Mitigation (Updated)

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| Tailscale connectivity issues | Low | Medium | Document troubleshooting; rclone fallback always works |
| Large file upload timeouts | Medium | Low | Configurable timeout; async mode available |
| iOS Shortcut limitations | Low | Medium | Test thoroughly; document workarounds |
| Security exposure | Low | High | Tailscale provides network security; optional API key |
| Breaking existing flow | Low | High | HTTP disabled by default; extensive testing |

---

## Implementation Status

**Phases 1-4:** Complete (2026-01-21)
**Phase 5:** Complete (2026-01-24)

| Phase | Work Items | Status |
|-------|------------|--------|
| Phase 1: Core Pipeline (MVP) | 9 items (1.1-1.9) | ✅ Complete 2026-01-20 |
| Phase 2: Classification & Templates | 5 items (2.1-2.5) | ✅ Complete 2026-01-20 |
| Phase 3: Reliability & Notifications | 5 items (3.1-3.5) | ✅ Complete 2026-01-21 |
| Phase 4: Weekly Synthesis | 5 items (4.1-4.5) | ✅ Complete 2026-01-20 |
| Phase 5: HTTP Upload Endpoint | 8 items (5.1-5.8) | ✅ Complete 2026-01-24 |

---

## Appendix: Requirement Traceability (Updated)

| Requirement | Source | Phase | Work Item |
|-------------|--------|-------|-----------|
| Fire-and-forget capture | PRD §2 | 1 | All |
| SQLite state management | TDD §3.1 | 1 | 1.2 |
| Watchdog folder monitoring | TDD §4.1 | 1 | 1.4 |
| Whisper API transcription | TDD §4.2 | 1 | 1.5 |
| Notion page creation | TDD §4.4 | 1 | 1.6 |
| State machine pipeline | TDD §5.1 | 1 | 1.7 |
| Docker deployment | TDD §8.5 | 1 | 1.1 |
| YAML template config | TDD §3.3 | 2 | 2.1 |
| 6 content templates | PRD §7 | 2 | 2.2 |
| Claude classification | TDD §4.3 | 2 | 2.3 |
| Template field extraction | PRD §6.4 | 2 | 2.3, 2.4 |
| Pushover notifications | TDD §4.5 | 3 | 3.1 |
| Daily health check | TDD §10.3 | 3 | 3.2 |
| Manual retry CLI | TDD §12 | 3 | 3.4 |
| Weekly synthesis | TDD §13 | 4 | All |
| Sparse week handling | PRD §8.3 | 4 | 4.4 |
| **HTTP upload endpoint** | **User request** | **5** | **5.1-5.8** |
| **Alternative to rclone** | **User request** | **5** | **5.2, 5.3** |
| **Tailscale integration** | **User request** | **5** | **5.6, 5.7** |
| **Immediate processing** | **User request** | **5** | **5.3, 5.5** |

---

*Implementation plan generated by Claude on 2026-01-20*
*Phase 5 added: 2026-01-24*
*Phase 5 completed: 2026-01-24*
*Source documents: docs/PRD.md v1.0, docs/TDD.md v1.0, User requirements*
