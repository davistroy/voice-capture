# Voice Capture to Notion Pipeline

A hands-free system to capture ephemeral thoughts via Apple Watch/iPhone, automatically transcribe and classify them, then store them in Notion with structured templates.

## Overview

Press the action button on your Apple Watch to start recording. Press again to stop. The system handles everything else:

1. **Capture** — iOS Shortcut saves recording to Google Drive
2. **Sync** — Home server pulls files via rclone
3. **Transcribe** — OpenAI Whisper API converts speech to text
4. **Classify** — Claude Sonnet categorizes into one of 6 templates
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
| General | Fallback for unclassified content |

## Status

**Version:** 1.0 (PRD Complete)
**Phase:** Ready for Implementation

See [`docs/prd.md`](docs/prd.md) for full specification.

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
│   └── prd.md              # Product Requirements Document
├── src/                    # (to be implemented)
│   ├── watcher/            # Folder monitoring
│   ├── transcription/      # Whisper integration
│   ├── classification/     # Claude classification
│   ├── notion/             # Notion API
│   └── notifications/      # Pushover
├── config/
│   └── templates/          # Template definitions (YAML)
└── reference/              # Requirements Q&A artifacts
```

## Implementation Phases

1. **Phase 1 (MVP)** — Basic pipeline, generic template only
2. **Phase 2** — Full classification with all 6 templates
3. **Phase 3** — Reliability hardening, notifications
4. **Phase 4** — Weekly synthesis Claude skill

## License

Private project — Troy Davis / Stratfield Consulting
