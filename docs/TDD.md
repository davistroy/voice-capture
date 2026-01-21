# Voice Capture to Notion Pipeline
## Technical Design Document

**Version:** 1.0
**Author:** Troy Davis / Stratfield Consulting
**Date:** January 2026
**Status:** Draft
**PRD Reference:** docs/prd.md v1.0

---

## 1. Executive Summary

This document specifies the technical implementation of a voice capture pipeline that transforms audio recordings from Apple Watch/iPhone into structured Notion pages. The system runs on a home server, processes audio through transcription (OpenAI Whisper) and classification (Claude Sonnet), then stores results in Notion with template-specific structure.

**Key Technical Decisions:**
- Python 3.10+ as primary language
- SQLite for processing state management
- YAML-driven template configuration
- Abstract interfaces for swappable transcription backends
- Async processing with retry/backoff patterns

---

## 2. System Architecture

### 2.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HOME SERVER                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │   rclone     │───▶│   Watcher    │───▶│  Processor   │───▶│   Notion   │ │
│  │   Sync       │    │   Service    │    │   Pipeline   │    │   Client   │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └────────────┘ │
│         │                   │                   │                   │        │
│         │                   │                   │                   │        │
│         ▼                   ▼                   ▼                   ▼        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         SQLite State DB                               │   │
│  │   - Processing queue                                                   │   │
│  │   - File status tracking                                               │   │
│  │   - Retry counters                                                     │   │
│  │   - Error history                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ Transcription│    │ Classification│    │ Notification │                   │
│  │   Service    │    │   Service    │    │   Service    │                   │
│  │  (Whisper)   │    │   (Claude)   │    │  (Pushover)  │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Template Configuration                              │   │
│  │   config/templates/*.yaml                                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Process Flow

```
Audio File Arrives
        │
        ▼
┌───────────────────┐
│  Watcher Detects  │
│   New File        │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌─────────────────┐
│  Validate File    │────▶│  Invalid? Move  │
│  (format, size)   │ NO  │  to /failed/    │
└─────────┬─────────┘     └─────────────────┘
          │ YES
          ▼
┌───────────────────┐
│  Insert Queue     │
│  status=pending   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Move to          │
│  /processing/     │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌─────────────────┐
│  Transcribe       │────▶│  Retry 3x?      │
│  (Whisper API)    │ ERR │  Backoff        │
└─────────┬─────────┘     └────────┬────────┘
          │ OK                     │ FAIL
          ▼                        ▼
┌───────────────────┐     ┌─────────────────┐
│  Classify         │     │  Move /failed/  │
│  (Claude Sonnet)  │     │  Notify         │
└─────────┬─────────┘     └─────────────────┘
          │
          ▼
┌───────────────────┐
│  Map to Template  │
│  Extract Fields   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌─────────────────┐
│  Create Notion    │────▶│  Retry 3x?      │
│  Page             │ ERR │  Backoff        │
└─────────┬─────────┘     └────────┬────────┘
          │ OK                     │ FAIL
          ▼                        ▼
┌───────────────────┐     ┌─────────────────┐
│  Delete Source    │     │  Move /failed/  │
│  Audio            │     │  Notify         │
└─────────┬─────────┘     └─────────────────┘
          │
          ▼
┌───────────────────┐
│  status=complete  │
└───────────────────┘
```

### 2.3 Directory Structure

```
/home/user/voice-capture/
├── inbox/              # rclone sync target (Google Drive mirror)
├── processing/         # Files currently being processed
├── failed/             # Failed files for manual review
├── logs/               # Application logs
└── data/
    └── voice_capture.db   # SQLite database
```

---

## 3. Data Models

### 3.1 Processing Queue Schema (SQLite)

```sql
-- Main processing queue
CREATE TABLE captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    current_path TEXT,
    device TEXT,                         -- 'watch' or 'phone'
    captured_at TIMESTAMP,               -- Extracted from filename

    -- Processing state
    status TEXT NOT NULL DEFAULT 'pending',
    -- Values: pending, transcribing, classifying, posting, complete, failed

    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP,

    -- Transcription results
    transcript TEXT,
    transcript_duration_seconds REAL,
    transcript_language TEXT,

    -- Classification results
    template_name TEXT,
    classification_confidence REAL,
    extracted_fields JSON,               -- Template-specific fields
    suggested_title TEXT,
    tags JSON,                           -- Array of tag strings

    -- Notion results
    notion_page_id TEXT,
    notion_page_url TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_captures_status ON captures(status);
CREATE INDEX idx_captures_captured_at ON captures(captured_at);

-- Failure history for debugging
CREATE TABLE failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER NOT NULL,
    stage TEXT NOT NULL,                 -- transcribing, classifying, posting
    error_type TEXT,
    error_message TEXT,
    error_details JSON,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (capture_id) REFERENCES captures(id)
);

CREATE INDEX idx_failure_log_capture_id ON failure_log(capture_id);

-- Daily statistics for health monitoring
CREATE TABLE daily_stats (
    date TEXT PRIMARY KEY,               -- YYYY-MM-DD
    captures_received INTEGER DEFAULT 0,
    captures_completed INTEGER DEFAULT 0,
    captures_failed INTEGER DEFAULT 0,
    total_audio_seconds REAL DEFAULT 0,
    avg_processing_time_seconds REAL,
    template_breakdown JSON              -- {"journal": 5, "task": 3, ...}
);
```

### 3.2 Core Domain Models (Python)

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any

class ProcessingStatus(Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    CLASSIFYING = "classifying"
    POSTING = "posting"
    COMPLETE = "complete"
    FAILED = "failed"

class Device(Enum):
    WATCH = "watch"
    PHONE = "phone"
    UNKNOWN = "unknown"

@dataclass
class TranscriptionResult:
    text: str
    duration_seconds: float
    language: str
    segments: Optional[List[Dict[str, Any]]] = None  # Timestamped segments

@dataclass
class ClassificationResult:
    template_name: str
    confidence: float
    fields: Dict[str, Any]
    title: str
    tags: List[str]
    reasoning: Optional[str] = None  # LLM's classification reasoning

@dataclass
class CaptureRecord:
    id: Optional[int] = None
    filename: str = ""
    original_path: str = ""
    current_path: Optional[str] = None
    device: Device = Device.UNKNOWN
    captured_at: Optional[datetime] = None

    status: ProcessingStatus = ProcessingStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None
    last_attempt_at: Optional[datetime] = None

    transcription: Optional[TranscriptionResult] = None
    classification: Optional[ClassificationResult] = None

    notion_page_id: Optional[str] = None
    notion_page_url: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

### 3.3 Template Configuration Schema

```yaml
# Schema for config/templates/{template_name}.yaml

name: string                    # Internal identifier (lowercase, no spaces)
display_name: string            # Human-readable name
description: string             # Purpose of this template
enabled: boolean                # default: true

triggers:
  patterns: list[string]        # Explicit phrase patterns
  indicators: list[string]      # Semantic indicators for LLM

fields:
  - name: string                # Field identifier
    type: enum                  # title, date, select, multi_select, rich_text, number, checkbox
    description: string         # What this field captures
    extraction: string          # Instruction for LLM extraction
    required: boolean           # default: false
    default: any                # Default value if not extracted
    options: list[string]       # For select/multi_select types
    notion_property: string     # Notion property name (if different from name)

notion:
  database_id: string           # Environment variable reference or literal

page_body_template: string      # Jinja2 template for page content
```

**Example: task.yaml**

```yaml
name: task
display_name: Task
description: Action items, to-dos, reminders, commitments
enabled: true

triggers:
  patterns:
    - "I need to"
    - "don't forget to"
    - "remind me to"
    - "task:"
    - "todo:"
    - "action item"
  indicators:
    - imperative statements
    - action commitments
    - deadlines mentioned
    - responsibility assignments

fields:
  - name: title
    type: title
    description: Concise action item
    extraction: Extract the core action as a brief imperative statement
    required: true
    notion_property: Task

  - name: date_created
    type: date
    description: Capture timestamp
    extraction: Use capture metadata
    required: true
    notion_property: Date Created

  - name: due_date
    type: date
    description: Deadline if mentioned
    extraction: Extract explicit date/time references; leave empty if none
    required: false
    notion_property: Due Date

  - name: priority
    type: select
    description: Task priority
    extraction: Infer from urgency language; default to Medium if unclear
    options: [High, Medium, Low]
    default: Medium
    notion_property: Priority

  - name: context
    type: rich_text
    description: Why, for whom, related project
    extraction: Extract any mentioned context, stakeholders, or project references
    required: false
    notion_property: Context

  - name: status
    type: select
    description: Task status
    options: [Not Started, In Progress, Complete]
    default: Not Started
    notion_property: Status

  - name: tags
    type: multi_select
    description: Topic tags
    extraction: Generate 2-5 relevant topic tags
    notion_property: Tags

notion:
  database_id: ${NOTION_VOICE_CAPTURES_DB_ID}

page_body_template: |
  ## Context
  {{ context | default("No additional context provided.") }}

  ## Raw Transcript
  {{ transcript }}
```

---

## 4. Component Specifications

### 4.1 Folder Watcher Service

**Module:** `src/watcher/watcher.py`

**Responsibilities:**
- Monitor inbox directory for new audio files
- Validate file format and completeness
- Queue files for processing
- Handle file moves between directories

**Technology:** Python `watchdog` library

```python
# Key interfaces

class FolderWatcher:
    def __init__(
        self,
        inbox_path: Path,
        processing_path: Path,
        failed_path: Path,
        db: Database,
        file_settle_delay: float = 2.0,  # Seconds to wait for file write completion
        valid_extensions: tuple = ('.m4a', '.wav', '.mp3')
    ):
        ...

    async def start(self) -> None:
        """Start watching for new files."""
        ...

    async def stop(self) -> None:
        """Stop watching and cleanup."""
        ...

    async def on_file_created(self, file_path: Path) -> None:
        """Handle new file detection."""
        ...

    def validate_audio_file(self, file_path: Path) -> bool:
        """Validate file is processable audio."""
        ...

    def parse_filename(self, filename: str) -> tuple[datetime, Device]:
        """Extract timestamp and device from filename.

        Expected format: {timestamp}_{device}.m4a
        Example: 2026-01-20T143022_watch.m4a
        """
        ...
```

**File Detection Logic:**

1. `watchdog` detects file creation event
2. Wait `file_settle_delay` seconds (file may still be syncing)
3. Verify file size is stable (not still being written)
4. Validate audio format (check magic bytes, not just extension)
5. Parse filename for metadata
6. Insert into `captures` table with `status=pending`
7. Move file to `/processing/` directory
8. Emit event for processor to pick up

**Decision:** Files with unexpected naming format are processed anyway with `captured_at = file mtime` and `device = unknown`. Aligns with PRD's "graceful fallback" principle — never lose content.

### 4.2 Transcription Service

**Module:** `src/transcription/transcription.py`

**Design Pattern:** Strategy pattern with abstract interface for swappable backends

```python
from abc import ABC, abstractmethod

class TranscriptionBackend(ABC):
    """Abstract interface for transcription backends."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> TranscriptionResult:
        """Transcribe audio file to text."""
        ...

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """Return list of supported audio formats."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        ...


class WhisperAPIBackend(TranscriptionBackend):
    """OpenAI Whisper API implementation."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        timeout: float = 120.0
    ):
        ...

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Call OpenAI Whisper API.

        Handles:
        - File upload
        - Response parsing
        - Duration and language extraction
        """
        ...


class LocalWhisperBackend(TranscriptionBackend):
    """Local Whisper model implementation (for future use)."""

    def __init__(
        self,
        model_size: str = "base",  # tiny, base, small, medium, large
        device: str = "cuda"       # cuda, cpu
    ):
        ...


class TranscriptionService:
    """Facade for transcription operations."""

    def __init__(
        self,
        backend: TranscriptionBackend,
        max_retries: int = 3,
        base_backoff: float = 5.0
    ):
        ...

    async def transcribe_with_retry(
        self,
        audio_path: Path
    ) -> TranscriptionResult:
        """Transcribe with exponential backoff retry."""
        ...
```

**Error Handling:**

| Error Type | Detection | Action |
|------------|-----------|--------|
| API timeout | `asyncio.TimeoutError` | Retry with backoff |
| Rate limit | HTTP 429 | Retry after `Retry-After` header |
| Invalid audio | HTTP 400 with format error | Fail immediately (no retry) |
| Server error | HTTP 5xx | Retry with backoff |
| Network error | `aiohttp.ClientError` | Retry with backoff |

**Decision:** Skip confidence tracking for transcription entirely. Whisper is highly accurate for clear speech; bad transcriptions will be apparent when viewed. Classification confidence (from Claude) is the meaningful quality gate. Remove `transcript_confidence` field from data model.

### 4.3 Classification Service

**Module:** `src/classification/classification.py`

**Responsibilities:**
- Load template configurations from YAML
- Build dynamic classification prompt
- Call Claude API for classification
- Parse and validate LLM response
- Handle confidence threshold fallback

```python
class TemplateLoader:
    """Loads and validates template configurations."""

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self._templates: Dict[str, TemplateConfig] = {}

    def load_all(self) -> None:
        """Load all .yaml files from templates directory."""
        ...

    def get_template(self, name: str) -> Optional[TemplateConfig]:
        ...

    def get_enabled_templates(self) -> List[TemplateConfig]:
        ...

    def build_classification_prompt_context(self) -> str:
        """Generate template definitions for LLM prompt."""
        ...


@dataclass
class TemplateConfig:
    name: str
    display_name: str
    description: str
    enabled: bool
    triggers: TriggersConfig
    fields: List[FieldConfig]
    notion_database_id: str
    page_body_template: str


class ClassificationService:
    """Handles transcript classification and field extraction."""

    def __init__(
        self,
        anthropic_client: Anthropic,
        template_loader: TemplateLoader,
        model: str = "claude-sonnet-4-20250514",
        confidence_threshold: float = 0.7,
        max_retries: int = 3
    ):
        ...

    async def classify(
        self,
        transcript: str,
        metadata: CaptureMetadata
    ) -> ClassificationResult:
        """
        Classify transcript and extract template fields.

        Returns ClassificationResult with:
        - template_name: Selected template or "general" if below threshold
        - confidence: 0.0-1.0
        - fields: Dict of extracted field values
        - title: Suggested page title
        - tags: List of topic tags
        """
        ...

    def _build_prompt(
        self,
        transcript: str,
        metadata: CaptureMetadata
    ) -> str:
        """Construct classification prompt with template definitions."""
        ...

    def _parse_response(self, response: str) -> ClassificationResult:
        """Parse and validate LLM JSON response."""
        ...
```

**Classification Prompt Structure:**

```
You are classifying and structuring voice capture transcripts for a personal knowledge management system.

## Available Templates

{for each enabled template}
### {template.display_name}
**Purpose:** {template.description}
**Trigger patterns:** {template.triggers.patterns}
**Semantic indicators:** {template.triggers.indicators}

**Fields to extract:**
{for each field}
- {field.name} ({field.type}): {field.description}
  Extraction guidance: {field.extraction}
{end for}
{end for}

## Classification Rules

1. Select the template that best matches the transcript content
2. Confidence should reflect how well the transcript fits the template
3. If no template fits with confidence >= 0.7, use "general"
4. Extract all relevant fields for the selected template
5. Generate a concise, descriptive title (5-15 words)
6. Generate 2-5 relevant topic tags

## Overlap Handling

- Meeting with action items: If primarily about the task, use Task; if primarily reflection, use Journal
- Client work: Classify by content type (Task, Idea, Product), not by client context
- Learning while building: If about the product, use Product; if broader learning, use Research

## Transcript Metadata

- Captured: {timestamp}
- Duration: {duration} seconds
- Device: {device}

## Transcript

"""
{transcript_text}
"""

## Response Format

Respond with valid JSON only:
{
  "template": "template_name",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of classification choice",
  "title": "Suggested page title",
  "tags": ["tag1", "tag2", "tag3"],
  "fields": {
    "field_name": "extracted_value",
    ...
  }
}
```

**Response Validation:**

1. Parse JSON (retry with corrective prompt if invalid)
2. Verify `template` exists in loaded templates or is "general"
3. Verify `confidence` is 0.0-1.0
4. Verify all required fields are present for selected template
5. Apply defaults for missing optional fields

### 4.4 Notion Integration Service

**Module:** `src/notion/notion_client.py`

```python
class NotionService:
    """Handles all Notion API interactions."""

    def __init__(
        self,
        api_key: str,
        database_id: str,  # Main Voice Captures database
        max_retries: int = 3
    ):
        ...

    async def create_capture_page(
        self,
        classification: ClassificationResult,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
        template: TemplateConfig
    ) -> NotionPage:
        """
        Create a new page in the Voice Captures database.

        Returns NotionPage with id and url.
        """
        ...

    def _build_properties(
        self,
        classification: ClassificationResult,
        metadata: CaptureMetadata,
        template: TemplateConfig
    ) -> Dict[str, Any]:
        """Map extracted fields to Notion property format."""
        ...

    def _build_page_content(
        self,
        classification: ClassificationResult,
        transcription: TranscriptionResult,
        template: TemplateConfig
    ) -> List[Dict[str, Any]]:
        """Build page body blocks from template."""
        ...

    async def query_captures_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[NotionPage]:
        """Query captures for weekly synthesis."""
        ...
```

**Notion Property Type Mapping:**

| Template Field Type | Notion Property Type | Notes |
|---------------------|---------------------|-------|
| title | title | Page title |
| date | date | ISO 8601 format |
| select | select | Must match existing options |
| multi_select | multi_select | Auto-creates new options |
| rich_text | rich_text | Plain text blocks |
| number | number | Numeric value |
| checkbox | checkbox | Boolean |

**Page Content Structure:**

All pages follow this body structure:

```markdown
## Summary
{LLM-generated summary based on template}

## {Template-specific section if any}
{Template-specific content}

## Raw Transcript
{Full transcript text}

---
*Processed: {timestamp} | Device: {device} | Duration: {duration}s*
```

**Decision:** Truncate at 2000 chars with "..." indicator. Expected recordings are under 120 seconds (~1500 chars), well under the limit. Edge cases for 5+ minute recordings are rare and can be enhanced later if needed.

### 4.5 Notification Service

**Module:** `src/notifications/pushover.py`

```python
class PushoverService:
    """Pushover notification integration."""

    def __init__(
        self,
        api_token: str,
        user_key: str,
        device: Optional[str] = None  # Specific device, or all if None
    ):
        ...

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: int = 0,  # -2 to 2
        url: Optional[str] = None,
        url_title: Optional[str] = None
    ) -> bool:
        """Send a Pushover notification."""
        ...

    async def notify_processing_failure(
        self,
        capture: CaptureRecord,
        error: str
    ) -> None:
        """Notify about a processing failure."""
        ...

    async def send_daily_summary(
        self,
        stats: DailyStats
    ) -> None:
        """Send daily health summary."""
        ...
```

**Notification Events:**

| Event | Priority | Message Format |
|-------|----------|----------------|
| Processing failure (after retries) | 0 (Normal) | "Failed: {filename}\nError: {error}\nStage: {stage}" |
| Daily summary | -1 (Low) | "{completed} processed, {failed} failed\nQueue: {pending} pending" |
| High failure rate (>20%) | 1 (High) | "Alert: {failure_rate}% failure rate today" |
| Queue backup (>10 items) | 0 (Normal) | "Queue backed up: {count} items pending" |

---

## 5. Processing Pipeline

### 5.1 Pipeline Orchestrator

**Module:** `src/pipeline/orchestrator.py`

```python
class PipelineOrchestrator:
    """Coordinates the end-to-end processing pipeline."""

    def __init__(
        self,
        db: Database,
        transcription: TranscriptionService,
        classification: ClassificationService,
        notion: NotionService,
        notifications: PushoverService,
        config: PipelineConfig
    ):
        ...

    async def process_capture(self, capture_id: int) -> ProcessingResult:
        """
        Execute full pipeline for a single capture.

        State transitions:
        pending -> transcribing -> classifying -> posting -> complete

        On error: increment retry_count, stay in current state, log error
        After max retries: -> failed, notify
        """
        ...

    async def process_pending_queue(self) -> None:
        """Process all pending captures in queue."""
        ...

    async def retry_failed(self, capture_id: int) -> ProcessingResult:
        """Manually retry a failed capture."""
        ...
```

**State Machine:**

```
                    ┌─────────────────────────────────────────────┐
                    │                                             │
                    ▼                                             │
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────┴─────┐
│ pending  │───▶│ transcribing │───▶│ classifying  │───▶│   posting   │
└──────────┘    └──────┬───────┘    └──────┬───────┘    └──────┬──────┘
                       │                   │                   │
                       │ ERROR             │ ERROR             │ ERROR
                       ▼                   ▼                   ▼
                 ┌─────────┐         ┌─────────┐         ┌─────────┐
                 │ retry?  │         │ retry?  │         │ retry?  │
                 └────┬────┘         └────┬────┘         └────┬────┘
                      │                   │                   │
              ┌───────┴───────┐   ┌───────┴───────┐   ┌───────┴───────┐
              │ YES           │   │ YES           │   │ YES           │
              ▼               ▼   ▼               ▼   ▼               ▼
         (back to same   ┌────────┐         (back to same   ┌────────┐
          state)         │ failed │          state)         │ failed │
                         └────────┘                         └────────┘
                              │                                  │
                              ▼                                  ▼
                         ┌─────────┐                        ┌─────────┐
                         │ notify  │                        │ notify  │
                         └─────────┘                        └─────────┘

                                    ┌──────────┐
           posting success ───────▶│ complete │
                                    └────┬─────┘
                                         │
                                         ▼
                                    ┌───────────┐
                                    │ delete    │
                                    │ source    │
                                    │ audio     │
                                    └───────────┘
```

### 5.2 Retry Configuration

```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0  # 5 minutes
    backoff_multiplier: float = 2.0

    def get_backoff(self, retry_count: int) -> float:
        """Calculate exponential backoff with jitter."""
        backoff = min(
            self.base_backoff_seconds * (self.backoff_multiplier ** retry_count),
            self.max_backoff_seconds
        )
        # Add 10% jitter
        jitter = backoff * 0.1 * random.random()
        return backoff + jitter
```

### 5.3 Concurrency Model

**Decision:** Single-threaded sequential processing. Expected volume is 1-10 captures/day. With async I/O for API calls, each capture takes ~30-60 seconds; 10 captures = 10 minutes total, well within SLA. No concurrency complexity needed.

---

## 6. Configuration Management

### 6.1 Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
NOTION_API_KEY=secret_...
NOTION_VOICE_CAPTURES_DB_ID=...
NOTION_WEEKLY_SUMMARIES_DB_ID=...
PUSHOVER_API_TOKEN=...
PUSHOVER_USER_KEY=...

# Optional with defaults
VOICE_CAPTURE_INBOX_PATH=/home/user/voice-capture/inbox
VOICE_CAPTURE_PROCESSING_PATH=/home/user/voice-capture/processing
VOICE_CAPTURE_FAILED_PATH=/home/user/voice-capture/failed
VOICE_CAPTURE_DB_PATH=/home/user/voice-capture/data/voice_capture.db
VOICE_CAPTURE_LOG_PATH=/home/user/voice-capture/logs
VOICE_CAPTURE_LOG_LEVEL=INFO

# Tuning
WHISPER_MODEL=whisper-1
CLAUDE_MODEL=claude-sonnet-4-20250514
CLASSIFICATION_CONFIDENCE_THRESHOLD=0.7
MAX_RETRIES=3
FILE_SETTLE_DELAY_SECONDS=2.0
RCLONE_SYNC_INTERVAL=180
```

### 6.2 Configuration File

**File:** `config/settings.yaml`

```yaml
# Application settings (overridable by environment variables)

paths:
  inbox: ${VOICE_CAPTURE_INBOX_PATH:/home/user/voice-capture/inbox}
  processing: ${VOICE_CAPTURE_PROCESSING_PATH:/home/user/voice-capture/processing}
  failed: ${VOICE_CAPTURE_FAILED_PATH:/home/user/voice-capture/failed}
  database: ${VOICE_CAPTURE_DB_PATH:/home/user/voice-capture/data/voice_capture.db}
  logs: ${VOICE_CAPTURE_LOG_PATH:/home/user/voice-capture/logs}
  templates: ./config/templates

logging:
  level: ${VOICE_CAPTURE_LOG_LEVEL:INFO}
  format: "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
  max_bytes: 10485760  # 10MB
  backup_count: 5

transcription:
  backend: whisper_api
  model: ${WHISPER_MODEL:whisper-1}
  timeout_seconds: 120

classification:
  model: ${CLAUDE_MODEL:claude-sonnet-4-20250514}
  confidence_threshold: ${CLASSIFICATION_CONFIDENCE_THRESHOLD:0.7}
  max_tokens: 2048

pipeline:
  max_retries: ${MAX_RETRIES:3}
  base_backoff_seconds: 5.0
  max_backoff_seconds: 300.0
  file_settle_delay_seconds: ${FILE_SETTLE_DELAY_SECONDS:2.0}

watcher:
  valid_extensions:
    - .m4a
    - .wav
    - .mp3
  polling_interval_seconds: 1.0

health_check:
  schedule: "0 21 * * *"  # 9 PM daily
  failure_rate_threshold: 0.2
  queue_backup_threshold: 10

audio:
  max_size_mb: 100
  max_duration_seconds: 3600  # 1 hour
```

### 6.3 Global Classification Settings

**File:** `config/classification.yaml`

```yaml
# Global classification behavior settings

confidence_threshold: 0.7
fallback_template: general

# If multiple templates have similar confidence, prefer in this order
template_priority:
  - task      # Tasks are actionable, prioritize identification
  - product   # Product work is specific
  - research  # Research has clear indicators
  - idea      # Ideas are more free-form
  - journal   # Journal is a broader catch-all

# Prompt customization
system_context: |
  You are classifying voice captures for Troy Davis, a technology consultant.
  His captures often relate to:
  - Consulting projects and client work
  - Personal productivity and daily planning
  - Technical learning and research
  - Product ideas and development work

# Additional context can be added here for better classification
```

---

## 7. API Interfaces

### 7.1 OpenAI Whisper API

**Endpoint:** `POST https://api.openai.com/v1/audio/transcriptions`

**Request:**
```python
# Using openai Python SDK
from openai import OpenAI

client = OpenAI(api_key=api_key)

with open(audio_path, "rb") as audio_file:
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",  # Includes segments and duration
        language="en"  # Optional: force language
    )
```

**Response:**
```json
{
  "task": "transcribe",
  "language": "english",
  "duration": 45.2,
  "text": "Full transcript text here...",
  "segments": [
    {
      "id": 0,
      "seek": 0,
      "start": 0.0,
      "end": 5.2,
      "text": "First segment text",
      "tokens": [50364, 293, ...],
      "temperature": 0.0,
      "avg_logprob": -0.25,
      "compression_ratio": 1.5,
      "no_speech_prob": 0.01
    }
  ]
}
```

### 7.2 Anthropic Claude API

**Endpoint:** `POST https://api.anthropic.com/v1/messages`

**Request:**
```python
from anthropic import Anthropic

client = Anthropic(api_key=api_key)

message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2048,
    messages=[
        {
            "role": "user",
            "content": classification_prompt
        }
    ]
)
```

**Response:**
```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "{\n  \"template\": \"task\",\n  \"confidence\": 0.85,\n  ...}"
    }
  ],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 1250,
    "output_tokens": 180
  }
}
```

### 7.3 Notion API

**Create Page:**
```python
# POST https://api.notion.com/v1/pages

{
  "parent": {
    "database_id": "database-id-here"
  },
  "properties": {
    "Title": {
      "title": [
        {
          "text": {
            "content": "Task: Review quarterly report"
          }
        }
      ]
    },
    "Type": {
      "select": {
        "name": "Task"
      }
    },
    "Date": {
      "date": {
        "start": "2026-01-20T14:30:22.000Z"
      }
    },
    "Priority": {
      "select": {
        "name": "High"
      }
    },
    "Tags": {
      "multi_select": [
        {"name": "work"},
        {"name": "quarterly-review"}
      ]
    }
  },
  "children": [
    {
      "object": "block",
      "type": "heading_2",
      "heading_2": {
        "rich_text": [{"type": "text", "text": {"content": "Summary"}}]
      }
    },
    {
      "object": "block",
      "type": "paragraph",
      "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": "LLM summary here..."}}]
      }
    },
    {
      "object": "block",
      "type": "heading_2",
      "heading_2": {
        "rich_text": [{"type": "text", "text": {"content": "Raw Transcript"}}]
      }
    },
    {
      "object": "block",
      "type": "paragraph",
      "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": "Full transcript..."}}]
      }
    }
  ]
}
```

### 7.4 Pushover API

**Send Notification:**
```python
# POST https://api.pushover.net/1/messages.json

{
  "token": "app_token",
  "user": "user_key",
  "title": "Voice Capture: Processing Failed",
  "message": "Failed to process 2026-01-20T143022_watch.m4a\nError: Notion API timeout",
  "priority": 0,
  "url": "https://notion.so/page-id",
  "url_title": "View in Notion"
}
```

---

## 8. Deployment

### 8.1 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 20.04+ / Debian 11+ | Ubuntu 22.04 LTS |
| Python | 3.10 | 3.11+ |
| RAM | 512MB | 1GB |
| Storage | 1GB | 5GB (for logs and temp files) |
| Network | Reliable broadband | Reliable broadband |

### 8.2 Installation

```bash
# 1. Clone repository
git clone https://github.com/davistroy/voice-capture.git
cd voice-capture

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create directory structure
mkdir -p ~/voice-capture/{inbox,processing,failed,logs,data}

# 5. Configure rclone (if not already done)
rclone config
# Follow prompts to set up Google Drive remote named 'gdrive'

# 6. Set up environment variables
cp .env.example .env
# Edit .env with your API keys and paths

# 7. Initialize database
python -m src.db.init

# 8. Verify configuration
python -m src.cli.verify_config
```

### 8.3 Systemd Service

**File:** `/etc/systemd/system/voice-capture.service`

```ini
[Unit]
Description=Voice Capture Processing Service
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/voice-capture
Environment="PATH=/home/user/voice-capture/venv/bin"
EnvironmentFile=/home/user/voice-capture/.env
ExecStart=/home/user/voice-capture/venv/bin/python -m src.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 8.4 Cron Jobs

```cron
# rclone sync every minute
* * * * * rclone sync gdrive:/VoiceCaptures/inbox /home/user/voice-capture/inbox --checksum --log-file=/home/user/voice-capture/logs/rclone.log --log-level=INFO

# Daily health check at 9 PM
0 21 * * * /home/user/voice-capture/venv/bin/python -m src.cli.health_check

# Log rotation (if not using logrotate)
0 0 * * * find /home/user/voice-capture/logs -name "*.log" -mtime +90 -delete
```

### 8.5 Docker Deployment

**Decision:** Docker with docker-compose is the primary deployment method. Rationale:
- Home server is UNRAID 7.1, which is Docker-native
- Future portability to AWS/GCP/VPS is desired
- Docker is the natural fit for UNRAID's ecosystem

**Docker Configuration:**

```yaml
# docker-compose.yml
version: '3.8'

services:
  voice-capture:
    build: .
    container_name: voice-capture
    restart: unless-stopped
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - NOTION_API_KEY=${NOTION_API_KEY}
      - NOTION_VOICE_CAPTURES_DB_ID=${NOTION_VOICE_CAPTURES_DB_ID}
      - PUSHOVER_API_TOKEN=${PUSHOVER_API_TOKEN}
      - PUSHOVER_USER_KEY=${PUSHOVER_USER_KEY}
    volumes:
      - ./data:/app/data
      - ./config:/app/config:ro
      - ./logs:/app/logs
      - voice-capture-inbox:/app/inbox
      - voice-capture-processing:/app/processing
      - voice-capture-failed:/app/failed
    networks:
      - voice-capture-net

  rclone:
    image: rclone/rclone:latest
    container_name: voice-capture-rclone
    restart: unless-stopped
    entrypoint: /bin/sh
    command: >
      -c "while true; do
        rclone sync gdrive:/VoiceCaptures/inbox /data/inbox --checksum -v;
        sleep ${RCLONE_SYNC_INTERVAL:-180};
      done"
    environment:
      - RCLONE_SYNC_INTERVAL=${RCLONE_SYNC_INTERVAL:-180}
    volumes:
      - ./rclone-config:/config/rclone:ro
      - voice-capture-inbox:/data/inbox
    networks:
      - voice-capture-net

volumes:
  voice-capture-inbox:
  voice-capture-processing:
  voice-capture-failed:

networks:
  voice-capture-net:
```

**Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

CMD ["python", "-m", "src.main"]
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Coverage Targets:**
- `src/watcher/` - File validation, filename parsing
- `src/transcription/` - Response parsing, error handling
- `src/classification/` - Prompt building, response parsing, template matching
- `src/notion/` - Property mapping, page content building
- `src/pipeline/` - State transitions, retry logic

**Mocking Strategy:**
- Mock all external APIs (OpenAI, Anthropic, Notion, Pushover)
- Use fixture files for sample API responses
- Use temp directories for file operations

### 9.2 Integration Tests

**Test Scenarios:**
1. Happy path: Sample audio → complete Notion page
2. Transcription retry: Mock 2 failures, then success
3. Classification fallback: Low confidence → generic template
4. Notion rate limit: Mock 429, verify backoff
5. File corruption: Invalid audio → moved to /failed/

### 9.3 End-to-End Tests

**Manual Test Protocol:**

1. **Capture Flow Test:**
   - Record via Apple Watch
   - Verify file appears in Google Drive
   - Verify sync to local inbox
   - Verify processing completes
   - Verify Notion page created with correct template

2. **Failure Recovery Test:**
   - Process file with Notion API key temporarily invalid
   - Verify retries and failure notification
   - Re-enable API key
   - Run manual retry command
   - Verify successful completion

3. **Classification Accuracy Test:**
   - Process 20 representative captures
   - Manually score template selection
   - Target: >80% correct

### 9.4 Test Data

**Fixture Files:**
```
tests/fixtures/
├── audio/
│   ├── sample_task.m4a           # "I need to review the quarterly report by Friday"
│   ├── sample_journal.m4a        # "Today was productive, got through the backlog"
│   ├── sample_idea.m4a           # "What if we could automate the reporting process"
│   ├── sample_research.m4a       # "I want to learn more about vector databases"
│   ├── sample_product.m4a        # "Feature idea for the dashboard: add filters"
│   └── sample_ambiguous.m4a      # Mixed content, should go to general
├── transcripts/
│   ├── sample_task.json
│   └── ...
├── classifications/
│   ├── sample_task.json
│   └── ...
└── api_responses/
    ├── whisper_success.json
    ├── whisper_error.json
    ├── claude_success.json
    ├── notion_success.json
    └── notion_rate_limit.json
```

---

## 10. Monitoring & Observability

### 10.1 Logging

**Log Format:**
```
2026-01-20 14:30:22 | INFO | watcher | New file detected: 2026-01-20T143022_watch.m4a
2026-01-20 14:30:24 | INFO | pipeline | Processing capture_id=42, status=transcribing
2026-01-20 14:30:45 | INFO | transcription | Transcribed capture_id=42, duration=23.5s, language=en
2026-01-20 14:30:46 | INFO | classification | Classified capture_id=42, template=task, confidence=0.87
2026-01-20 14:30:48 | INFO | notion | Created page capture_id=42, page_id=abc123
2026-01-20 14:30:48 | INFO | pipeline | Completed capture_id=42, total_time=26.2s
```

**Log Levels:**
- DEBUG: Detailed processing info, API request/response bodies
- INFO: Normal operations, state transitions, completions
- WARNING: Retries, low confidence, fallback to generic
- ERROR: Failed operations, API errors, invalid responses

### 10.2 Metrics

**Decision:** No Prometheus-style metrics export. SQLite `daily_stats` table + Pushover notifications are sufficient for single-digit daily volume. Can add metrics endpoint later if dashboards become desirable.

### 10.3 Health Check Script

**File:** `src/cli/health_check.py`

```python
async def run_health_check() -> HealthCheckResult:
    """
    Daily health check that reports via Pushover.

    Checks:
    1. Database connectivity
    2. API reachability (Whisper, Claude, Notion, Pushover)
    3. Directory permissions (inbox, processing, failed)
    4. Processing statistics for last 24 hours
    5. Queue status
    """
    ...
```

---

## 11. Security Considerations

### 11.1 API Key Management

- All API keys stored in `.env` file (not in code or config)
- `.env` file permissions: `chmod 600`
- Environment variables loaded at runtime only

### 11.2 File Permissions

| Path | Permissions | Owner |
|------|-------------|-------|
| `/inbox/` | 750 | user:user |
| `/processing/` | 750 | user:user |
| `/failed/` | 750 | user:user |
| `/data/` | 700 | user:user |
| `.env` | 600 | user:user |

### 11.3 Data Privacy

- Audio files deleted immediately after successful Notion post
- No audio content retained locally beyond processing
- Transcripts stored only in Notion (user-controlled)
- Processing logs contain filenames but not content

### 11.4 Network Security

- All API calls over HTTPS
- No incoming network connections required
- rclone uses OAuth for Google Drive auth

---

## 12. Error Recovery Procedures

### 12.1 Manual Retry

```bash
# Retry a specific failed capture
python -m src.cli.retry --capture-id 42

# Retry all failed captures
python -m src.cli.retry --all-failed

# Reprocess from a specific stage
python -m src.cli.retry --capture-id 42 --from-stage classifying
```

### 12.2 Manual File Recovery

```bash
# Move file back to inbox for reprocessing
mv /home/user/voice-capture/failed/2026-01-20T143022_watch.m4a \
   /home/user/voice-capture/inbox/

# Clear failed status in database
python -m src.cli.reset_capture --filename "2026-01-20T143022_watch.m4a"
```

### 12.3 Database Recovery

```bash
# Export database to SQL
sqlite3 /home/user/voice-capture/data/voice_capture.db .dump > backup.sql

# Rebuild database from scratch
python -m src.db.init --force

# Re-import if needed
sqlite3 /home/user/voice-capture/data/voice_capture.db < backup.sql
```

---

## 13. Weekly Synthesis (Phase 4)

### 13.1 Claude Skill Specification

**Skill Name:** `weekly-voice-synthesis`

**Trigger:** Manual invocation via Claude Code or Claude Desktop

**Prerequisites:**
- Notion MCP configured and connected
- Access to Voice Captures database

**Skill Flow:**

1. Query Notion for captures from last 7 days
2. Group by template type
3. If < 3 captures, prompt for supplemental input
4. Generate synthesis using weekly summary template
5. Create new page in Weekly Summaries database
6. Return summary to user

**Decision:** Manual invocation via Claude Code CLI or Claude Desktop with Notion MCP. Weekly reflection is an intentional ritual — manual invocation allows adding context or asking follow-up questions. No scheduled automation.

### 13.2 Synthesis Prompt Structure

```
You are synthesizing a week's worth of voice captures into a reflection summary.

## This Week's Captures

{grouped_captures_by_type}

## Synthesis Guidelines

1. **Accomplishments**: Extract completed work, wins, and progress from Task and Journal entries
2. **Key Activities**: Summarize significant meetings, decisions, and work sessions
3. **Challenges**: Note any mentioned blockers, frustrations, or unresolved issues
4. **Ideas**: Highlight captured ideas with links to original pages
5. **Insights**: Identify patterns, lessons learned, recurring themes
6. **Upcoming**: Extract mentioned future plans and infer priorities

## Output Format

Generate the summary using the Weekly Summary Template format.
Include capture statistics at the end.
Link to original Notion pages where relevant using page IDs.
```

---

## 14. Implementation Checklist

### Phase 1: Core Pipeline (MVP)

- [ ] **Infrastructure**
  - [ ] Directory structure created
  - [ ] rclone configured and tested
  - [ ] Cron job for sync running
  - [ ] iOS Shortcut configured and tested

- [ ] **Database**
  - [ ] SQLite schema created
  - [ ] Database initialization script
  - [ ] Basic CRUD operations

- [ ] **Watcher Service**
  - [ ] File detection with watchdog
  - [ ] File validation
  - [ ] Filename parsing
  - [ ] Queue insertion

- [ ] **Transcription**
  - [ ] Whisper API integration
  - [ ] Retry logic
  - [ ] Result parsing

- [ ] **Notion Integration (Basic)**
  - [ ] Generic template only
  - [ ] Page creation
  - [ ] Source file deletion on success

- [ ] **Pipeline**
  - [ ] State machine implementation
  - [ ] Basic error handling
  - [ ] File logging

**Exit Criteria:** Watch recording appears in Notion within 5 minutes

### Phase 2: Classification & Templates

- [ ] **Template System**
  - [ ] YAML schema defined
  - [ ] Template loader implemented
  - [ ] All 6 templates created
  - [ ] Template validation

- [ ] **Classification**
  - [ ] Claude API integration
  - [ ] Dynamic prompt generation
  - [ ] Response parsing
  - [ ] Confidence threshold logic

- [ ] **Notion Integration (Full)**
  - [ ] Template-specific property mapping
  - [ ] Dynamic page content from template

**Exit Criteria:** >80% correct template classification

### Phase 3: Reliability & Notifications

- [ ] **Notifications**
  - [ ] Pushover integration
  - [ ] Failure notifications
  - [ ] Daily summary notifications

- [ ] **Health Checks**
  - [ ] Daily health check script
  - [ ] API connectivity tests
  - [ ] Failure rate alerting

- [ ] **Recovery**
  - [ ] Manual retry commands
  - [ ] Failed file recovery workflow

**Exit Criteria:** No silent failures

### Phase 4: Weekly Synthesis

- [ ] **Claude Skill**
  - [ ] Skill definition created
  - [ ] Notion MCP integration tested
  - [ ] Weekly query logic
  - [ ] Synthesis prompt finalized

- [ ] **Summary Generation**
  - [ ] Weekly template applied
  - [ ] Summary page creation
  - [ ] Sparse week handling

**Exit Criteria:** Useful weekly synthesis on demand

---

## 15. Resolved Clarifications

All technical clarifications have been resolved. Summary of decisions:

| Item | Decision |
|------|----------|
| **Filename handling** | Process with `captured_at = file mtime`, `device = unknown` — never lose content |
| **Transcription confidence** | Skip tracking — Whisper is accurate; classification confidence is the meaningful gate |
| **Notion text limits** | Truncate at 2000 chars with "..." — typical recordings are under 1500 chars |
| **Processing concurrency** | Single-threaded sequential — sufficient for 1-10 captures/day |
| **Docker deployment** | Yes, docker-compose — native fit for UNRAID, portable to cloud |
| **Metrics export** | No — SQLite stats + Pushover sufficient for low volume |
| **Weekly synthesis** | Manual invocation via Claude Code/Desktop with Notion MCP |
| **Templating engine** | Jinja2 — native to Python, already used in examples |
| **rclone sync interval** | 180 seconds via wrapper script with sleep loop — configurable, self-contained |
| **Weekly Summaries DB** | Separate database with `NOTION_WEEKLY_SUMMARIES_DB_ID` env var |
| **Test fixtures** | Mock API for unit tests; TTS-generated audio for integration tests |
| **Supporting classes** | Define during implementation — core models are specified |

---

## Appendix A: Dependencies

```
# requirements.txt

# Core
python-dotenv>=1.0.0
pyyaml>=6.0
pydantic>=2.0

# Async
aiohttp>=3.9
aiofiles>=23.0

# File watching
watchdog>=4.0

# Database
aiosqlite>=0.19

# APIs
openai>=1.0
anthropic>=0.18
notion-client>=2.0
python-pushover>=0.4

# CLI
click>=8.0
rich>=13.0

# Testing
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=4.0
```

---

## Appendix B: Sample Configuration Files

### .env.example

```bash
# API Keys (required)
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
NOTION_API_KEY=secret_your-key-here
PUSHOVER_API_TOKEN=your-token-here
PUSHOVER_USER_KEY=your-user-key-here

# Notion Database IDs (required)
NOTION_VOICE_CAPTURES_DB_ID=your-database-id-here
NOTION_WEEKLY_SUMMARIES_DB_ID=your-database-id-here

# Paths (optional - defaults shown)
# VOICE_CAPTURE_INBOX_PATH=/home/user/voice-capture/inbox
# VOICE_CAPTURE_PROCESSING_PATH=/home/user/voice-capture/processing
# VOICE_CAPTURE_FAILED_PATH=/home/user/voice-capture/failed
# VOICE_CAPTURE_DB_PATH=/home/user/voice-capture/data/voice_capture.db

# Logging (optional)
# VOICE_CAPTURE_LOG_LEVEL=INFO
```

### config/templates/_template.yaml

```yaml
# Template: {Name}
# Copy this file and customize for new template types

name: template_name           # lowercase, no spaces
display_name: Template Name   # Human-readable
description: What this template captures
enabled: true

triggers:
  patterns:
    - "phrase pattern 1"
    - "phrase pattern 2"
  indicators:
    - semantic indicator 1
    - semantic indicator 2

fields:
  - name: title
    type: title
    description: Page title
    extraction: How to generate the title
    required: true

  - name: date
    type: date
    description: Capture timestamp
    extraction: Use capture metadata
    required: true

  # Add more fields as needed...

  - name: tags
    type: multi_select
    description: Topic tags
    extraction: Generate 2-5 relevant topic tags

notion:
  database_id: ${NOTION_VOICE_CAPTURES_DB_ID}

page_body_template: |
  ## Summary
  {{ summary }}

  ## Raw Transcript
  {{ transcript }}
```

---

*Document generated: January 2026*
*All technical clarifications resolved — ready for implementation*
