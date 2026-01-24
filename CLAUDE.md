# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Voice Capture to Notion Pipeline** — A hands-free system to capture ephemeral thoughts via Apple Watch/iPhone (single button press), automatically transcribe and classify them, then store them in Notion with structured templates. Includes weekly synthesis capability via Claude.

**Core UX Principle:** Fire-and-forget. Capture friction must be near-zero. Every addition should pass that test.

## Architecture

Five-layer pipeline running on a home server:

1. **Capture Layer**: iPhone/Apple Watch → Just Press Record app → iOS Shortcut saves to Google Drive `/VoiceCaptures/inbox/`
2. **Processing Layer**: Home server with rclone sync (60s polling) → folder watcher → transcription → classification → Notion integration
3. **Storage Layer**: Notion Voice Captures database with template-specific properties
4. **Synthesis Layer**: On-demand Claude skill for weekly reflection synthesis via Notion MCP
5. **Notifications**: Pushover for errors and daily summaries

**Technology Stack:**
- Python 3.10+ with watchdog for folder monitoring
- rclone for Google Drive sync
- OpenAI Whisper API for transcription (recommended starting point)
- Claude API (Sonnet) for classification
- Notion API for storage
- SQLite for processing state/queue
- Pushover for notifications

## Key Design Decisions

- **No silent failures** — All errors must be logged and surface via notification
- **Graceful fallback** — If classification fails, use generic template (never lose content)
- **Audio deleted on success** — Files removed from Google Drive after successful Notion post
- **Configuration-driven** — All API keys, Notion DB IDs, folder paths via environment variables
- **State machine**: `pending` → `transcribing` → `classifying` → `posting` → `complete` (or `failed` with 3x retry + exponential backoff)

## Templates

Six content types, each with specific Notion properties (see `docs/prd.md` Section 7):
1. **Journal** — Personal reflections, daily observations, meeting reflections, mood tracking
2. **Task** — Action items, to-dos, reminders, commitments
3. **Idea** — Brain dumps, speculative concepts, creative possibilities
4. **Research** — Topics to explore, questions to investigate, learning goals
5. **Product** — Features, bugs, enhancements for things being built
6. **General** — Fallback for anything not matching above (confidence < 0.7)

**Extensibility:** Templates are config-driven (YAML in `config/templates/`). Adding a new template = add YAML file + Notion properties. No code changes. See PRD Section 7.8.

## Implementation Status

**Status:** Complete (v1.0, 2026-01-21)

All four phases implemented:
1. **Phase 1 (MVP)**: Core pipeline — watcher, transcription, Notion integration, orchestrator
2. **Phase 2**: Classification — Claude Sonnet, 6 YAML templates, dynamic property mapping
3. **Phase 3**: Reliability — Pushover notifications, health checks, retry hardening, recovery CLI
4. **Phase 4**: Synthesis — Weekly summary generation via Claude skill

## Resolved Decisions

All architectural decisions have been made. See `docs/prd.md` Section 12 for the full decision log.

| Decision | Choice |
|----------|--------|
| Transcription | OpenAI Whisper API (with abstraction for future local swap) |
| Classification LLM | Claude Sonnet |
| Capture confirmation | Haptic + banner notification |
| System notifications | Pushover |
| Task sync | Notion-only for MVP |
| Notion structure | Dedicated area, single database with Type property |
| Audio format | M4A (native Just Press Record default) |
| Templates | 6 types (Journal, Task, Idea, Research, Product, General) |
| Transcript storage | Page body under `## Raw Transcript` |
| Classification threshold | 0.7 confidence |

## File Structure

```
voice-capture/
├── docs/
│   ├── prd.md              # Product Requirements Document
│   ├── TDD.md              # Technical Design Document
│   ├── DEPLOYMENT_GUIDE.md # Deployment instructions
│   └── IOS_SHORTCUT_HTTP.md # iOS Shortcut for HTTP uploads
├── src/
│   ├── watcher/            # Folder monitoring (watchdog)
│   ├── transcription/      # Whisper API integration
│   ├── classification/     # Claude classification + template loader
│   ├── notion/             # Notion API + property mapper
│   ├── notifications/      # Pushover integration
│   ├── health/             # Health check system
│   ├── synthesis/          # Weekly synthesis engine
│   ├── pipeline/           # Orchestrator + retry logic
│   ├── http/               # HTTP server for direct uploads
│   ├── cli/                # CLI commands (verify, retry, reset, queue, health)
│   ├── db/                 # SQLite database layer
│   ├── models/             # Domain models
│   ├── config/             # Pydantic settings
│   └── main.py             # Application entry point
├── config/
│   ├── templates/          # Template definitions (6 YAML files)
│   ├── settings.yaml       # Application configuration
│   └── classification.yaml # Classification settings
├── skills/
│   └── weekly-voice-synthesis/  # Claude skill for synthesis
├── scripts/
│   └── rclone/             # Google Drive sync scripts
└── tests/                  # Comprehensive test suite
```

## CLI Commands

```bash
# Run the pipeline
python -m src.main

# Verify configuration
python -m src.cli.verify_config

# Check queue status
python -m src.cli.queue_status

# Retry failed captures
python -m src.cli.retry --capture-id 42
python -m src.cli.retry --all-failed

# Reset a capture (move back to inbox)
python -m src.cli.reset_capture --filename "filename.m4a"

# Run health check
python -m src.cli.health_check
```

## Development Notes

- Mock Notion API and transcription service for local testing before pointing at real services
- Test folder watcher and queue logic with sample audio files
- Run tests with `pytest` (all tests use mocked APIs)
- The PRD Section 6.4 contains the LLM prompt structure for classification
- Error handling strategy is detailed in PRD Section 9
