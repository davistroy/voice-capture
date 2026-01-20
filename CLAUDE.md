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

Seven content types, each with specific Notion properties (see `docs/prd.md` Section 7):
1. Meeting Note
2. Idea / Brain Dump
3. Task / To-Do
4. Journal / Reflection
5. Project Update
6. Client / Consulting Note
7. Generic (fallback)

## Implementation Phases

Build in order — each phase has exit criteria in the PRD:

1. **Phase 1 (MVP)**: Basic pipeline with generic template only. Exit: Watch recording → Notion page within 5 minutes.
2. **Phase 2**: LLM classification and all templates. Exit: >80% classification accuracy.
3. **Phase 3**: Reliability hardening, Pushover notifications, daily health checks. Exit: No silent failures.
4. **Phase 4**: Weekly synthesis Claude skill via Notion MCP.

## Open Questions (Resolve Before Heavy Development)

The PRD (`docs/prd.md` Section 12) lists 11 architectural decisions needing clarification:
1. Transcription endpoint selection
2. LLM provider for classification
3. Haptic confirmation on capture
4. Notification method preferences
5. Raw transcript storage location
6. Idea categories
7. Task sync to external apps
8. Mood tracking in Journal
9. Existing Notion projects DB to link
10. Client list for recognition
11. Notion workspace structure

## File Structure (Planned)

```
voice-capture/
├── docs/
│   └── prd.md              # Source of truth for requirements
├── src/
│   ├── watcher/            # Folder monitoring service
│   ├── transcription/      # Whisper API integration
│   ├── classification/     # LLM classification service
│   ├── notion/             # Notion API integration
│   └── notifications/      # Pushover integration
├── config/
│   └── templates/          # Template definitions for classification prompts
├── scripts/
│   └── rclone/             # Sync scripts and cron setup
└── tests/
```

## Development Notes

- Mock Notion API and transcription service for local testing before pointing at real services
- Test folder watcher and queue logic with sample audio files
- The PRD Section 6.4 contains the LLM prompt structure for classification
- Error handling strategy is detailed in PRD Section 9
