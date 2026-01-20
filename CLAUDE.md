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

## Implementation Phases

Build in order — each phase has exit criteria in the PRD:

1. **Phase 1 (MVP)**: Basic pipeline with generic template only. Exit: Watch recording → Notion page within 5 minutes.
2. **Phase 2**: LLM classification and all templates. Exit: >80% classification accuracy.
3. **Phase 3**: Reliability hardening, Pushover notifications, daily health checks. Exit: No silent failures.
4. **Phase 4**: Weekly synthesis Claude skill via Notion MCP.

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

## File Structure (Planned)

```
voice-capture/
├── docs/
│   └── prd.md              # Source of truth for requirements
├── src/
│   ├── watcher/            # Folder monitoring service
│   ├── transcription/      # Whisper API integration
│   ├── classification/     # LLM classification service (reads template configs)
│   ├── notion/             # Notion API integration
│   └── notifications/      # Pushover integration
├── config/
│   ├── templates/          # Template definitions (YAML) - add new templates here
│   │   ├── _template.yaml  # Blank template for creating new ones
│   │   ├── journal.yaml
│   │   ├── task.yaml
│   │   ├── idea.yaml
│   │   ├── research.yaml
│   │   ├── product.yaml
│   │   └── general.yaml    # Fallback template
│   └── classification.yaml # Global settings (threshold, etc.)
├── scripts/
│   └── rclone/             # Sync scripts and cron setup
└── tests/
```

## Development Notes

- Mock Notion API and transcription service for local testing before pointing at real services
- Test folder watcher and queue logic with sample audio files
- The PRD Section 6.4 contains the LLM prompt structure for classification
- Error handling strategy is detailed in PRD Section 9
