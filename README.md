# Voice Capture to Notion Pipeline

A hands-free system to capture ephemeral thoughts via Apple Watch/iPhone, automatically transcribe and classify them, then store them in Notion with structured templates.

## Overview

Press the action button on your Apple Watch to start recording. Press again to stop. The system handles everything else:

1. **Capture** — iOS Shortcut saves recording to Google Drive
2. **Sync** — Home server pulls files via rclone
3. **Transcribe** — OpenAI Whisper API converts speech to text
4. **Classify** — Claude Sonnet categorizes into one of 8 templates
5. **Store** — Structured page created in Notion
6. **Synthesize** — Weekly summary via Claude skill (on-demand)

## Templates

| Template | Purpose |
|----------|---------|
| Journal | Reflections, observations, mood tracking |
| Task | Action items, to-dos, reminders |
| Idea | Brain dumps, speculative concepts |
| Research | Topics to explore, learning goals |
| Product | Features, bugs, product notes |
| Feedback | Employee performance observations |
| Quick Update | Daily work status reports |
| General | Fallback for unclassified content |

## Status

**Version:** 1.0 (Implementation Complete)
**Completed:** 2026-01-21

All four phases implemented and operational.

See [`docs/prd.md`](docs/prd.md) for specification, [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) for deployment.

## Architecture

```
iPhone/Watch → Google Drive → Home Server → Notion
     ↓              ↓              ↓           ↓
Just Press    iOS Shortcut    Python      Voice Captures
  Record        + rclone     Pipeline       Database
```

**Stack:** Python 3.10+, Whisper API, Claude API, Notion API, Pushover, SQLite

## Project Structure

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
│   ├── common/             # Shared utilities (backoff, datetime, secrets)
│   ├── interfaces/         # Abstract interfaces for services
│   └── main.py             # Application entry point
├── config/
│   ├── templates/          # Template definitions (8 YAML files)
│   ├── settings.yaml       # Application configuration
│   └── classification.yaml # Classification settings
├── skills/
│   ├── weekly-voice-synthesis/  # Claude skill for weekly synthesis
│   └── summarize-feedback/      # Claude skill for feedback assessment docs
├── scripts/
│   ├── generate_feedback_docx.py # Feedback assessment document generator
│   └── rclone/             # Google Drive sync scripts
└── tests/                  # Comprehensive test suite
```

## Implementation Phases (Complete)

1. **Phase 1 (MVP)** — Core pipeline: watcher, transcription, Notion integration, orchestrator
2. **Phase 2** — Classification: Claude Sonnet, 8 YAML templates, dynamic property mapping
3. **Phase 3** — Reliability: Pushover notifications, health checks, retry hardening, recovery CLI
4. **Phase 4** — Synthesis: Weekly summary generation, Notion query, sparse week handling

## License

Private project — Troy Davis / Stratfield Consulting
