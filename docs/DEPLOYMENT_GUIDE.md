# Voice Capture to Notion Pipeline - Complete Setup Guide

## Overview

This system captures voice recordings from Apple Watch/iPhone, automatically transcribes them using OpenAI Whisper, classifies them into structured templates using Claude, and stores them in Notion. It runs on Docker (ideal for UNRAID, home server, or VPS).

---

## Prerequisites

| Requirement | Source | Cost |
|-------------|--------|------|
| Docker & Docker Compose | docker.com | Free |
| OpenAI API Key | platform.openai.com | Pay per use (~$0.006/min) |
| Anthropic API Key | console.anthropic.com | Pay per use (~$0.003/1K tokens) |
| Notion API Key | notion.so/my-integrations | Free |
| Pushover Account | pushover.net | $5 one-time |
| Google Account | For Drive sync | Free |
| iPhone/Apple Watch | For capture | — |
| "Just Press Record" app | App Store | $4.99 |

---

## Part 1: Notion Setup

### 1.1 Create Voice Captures Database

In Notion, create a new database with these properties:

| Property | Type | Values/Notes |
|----------|------|--------------|
| Title | Title | Auto-generated from transcript |
| Date | Date | Capture timestamp |
| Type | Select | Journal, Task, Idea, Research, Product, General |
| Device | Select | Watch, Phone |
| Tags | Multi-select | Auto-populated from classification |
| Mood | Select | (for Journal only) Great, Good, Okay, Difficult, Rough |
| Priority | Select | (for Task/Product) High, Medium, Low |
| Status | Select | (for Task/Research) Not Started, In Progress, Complete |

### 1.2 Create Weekly Summaries Database

Create a second database for weekly synthesis:

| Property | Type |
|----------|------|
| Title | Title |
| Week Start | Date |
| Week End | Date |
| Capture Count | Number |
| Supplemental Input | Checkbox |

### 1.3 Create Notion Integration

1. Go to **notion.so/my-integrations**
2. Click **New Integration**
3. Name it "Voice Capture Pipeline"
4. Select your workspace
5. Copy the **Internal Integration Secret** (starts with `secret_`)
6. **Grant Access**: Open each database, click `...` → **Connections** → Add your integration

### 1.4 Get Database IDs

For each database:
1. Open the database as a full page
2. Copy the URL: `https://notion.so/workspace/DATABASE_ID?v=...`
3. The DATABASE_ID is the 32-character hex string before `?v=`

---

## Part 2: API Keys Setup

### 2.1 OpenAI API Key (Whisper)

1. Go to **platform.openai.com/api-keys**
2. Create new secret key
3. Copy it (starts with `sk-`)

### 2.2 Anthropic API Key (Claude)

1. Go to **console.anthropic.com/settings/keys**
2. Create key
3. Copy it (starts with `sk-ant-`)

### 2.3 Pushover Setup (Notifications)

1. Go to **pushover.net** and create account ($5 one-time)
2. Note your **User Key** on the dashboard
3. **Create an Application** → Get the **API Token**

---

## Part 3: Server Deployment

### 3.1 Clone and Configure

```bash
# Clone the repository
git clone https://github.com/davistroy/voice-capture.git
cd voice-capture

# Copy environment template
cp .env.example .env
```

### 3.2 Edit .env File

```bash
nano .env  # or your preferred editor
```

Fill in all values:

```env
# Required API Keys
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
NOTION_API_KEY=secret_your-notion-key
PUSHOVER_API_TOKEN=your-pushover-app-token
PUSHOVER_USER_KEY=your-pushover-user-key

# Required Notion Database IDs
NOTION_VOICE_CAPTURES_DB_ID=your-32-char-database-id
NOTION_WEEKLY_SUMMARIES_DB_ID=your-32-char-database-id

# Optional (defaults shown)
VOICE_CAPTURE_LOG_LEVEL=INFO
RCLONE_SYNC_INTERVAL=180
```

### 3.3 Configure rclone (Google Drive Sync)

**If your server has a browser:**
```bash
./scripts/rclone/setup.sh
```

**If headless (UNRAID, NAS):**
```bash
./scripts/rclone/setup.sh --headless
```

This will:
1. Walk you through Google OAuth
2. Create the `gdrive` remote
3. Create `/VoiceCaptures/inbox` folder on Drive
4. Copy `rclone.conf` to `rclone-config/`

**Test the configuration:**
```bash
./scripts/rclone/setup.sh --test
# Or manually:
rclone ls gdrive:/VoiceCaptures/inbox
```

### 3.4 Start the Services

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

### 3.5 Verify Configuration

```bash
# Run config verification
docker-compose exec voice-capture python -m src.cli.verify_config
```

This checks:
- All environment variables
- API connectivity (OpenAI, Claude, Notion, Pushover)
- Directory permissions

---

## Part 4: iOS Capture Setup

### 4.1 Install Just Press Record

1. Download **Just Press Record** from App Store ($4.99)
2. Enable iCloud sync in app settings
3. Configure: Audio Quality = High, Format = M4A

### 4.2 Create iOS Shortcut

Create a Shortcut that:
1. Records audio using Just Press Record
2. Saves file to Google Drive `/VoiceCaptures/inbox/`

**Basic Shortcut Steps:**
1. Open **Shortcuts** app
2. Create new shortcut
3. Add: **Just Press Record: Start Recording**
4. Add: **Wait to Return** (records until you return to Shortcuts)
5. Add: **Get Latest Recording** from Just Press Record
6. Add: **Save File** to Google Drive path: `/VoiceCaptures/inbox/`
7. Name it "Voice Capture" and add to Home Screen / Watch

### 4.3 Apple Watch Complication

1. In Shortcuts app, select your shortcut
2. Tap the `...` menu → **Add to Apple Watch**
3. Add complication to your watch face

**Usage:** Tap the complication → speak → tap again to stop. File syncs automatically.

---

## Part 5: Using the System

### 5.1 Daily Capture Flow

1. **Tap** the Watch complication (or iPhone shortcut)
2. **Speak** your thought
3. **Tap** to stop recording
4. **Done** — file syncs to Google Drive, then to your server, transcribed, classified, and posted to Notion

**Typical latency:** 2-5 minutes from capture to Notion page

### 5.2 Monitor Processing

```bash
# View real-time logs
docker-compose logs -f voice-capture

# Check queue status
docker-compose exec voice-capture python -m src.cli.queue_status
```

### 5.3 Handle Failures

```bash
# View failed items
docker-compose exec voice-capture python -m src.cli.queue_status

# Retry a specific capture
docker-compose exec voice-capture python -m src.cli.retry --capture-id 42

# Retry all failed
docker-compose exec voice-capture python -m src.cli.retry --all-failed

# Reset a capture to reprocess from scratch
docker-compose exec voice-capture python -m src.cli.reset_capture --filename "file.m4a"
```

### 5.4 Health Monitoring

```bash
# Run health check manually
docker-compose exec voice-capture python -m src.cli.health_check
```

The system sends daily health summaries via Pushover at 9 PM (configurable). Alerts trigger for:
- Failure rate > 20%
- Queue backup > 10 items
- Any API unreachable

---

## Part 6: Weekly Synthesis

The weekly synthesis skill requires **Notion MCP** configured in Claude Code or Claude Desktop.

### 6.1 Configure Notion MCP

**Claude Code** (`~/.claude.json`):
```json
{
  "mcpServers": {
    "notion": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-notion"],
      "env": {
        "NOTION_API_KEY": "secret_your-notion-api-key"
      }
    }
  }
}
```

### 6.2 Run Weekly Synthesis

```bash
# In Claude Code
claude "Run weekly-voice-synthesis"

# Or with options
claude "Run weekly-voice-synthesis with days=14"
claude "Run weekly-voice-synthesis with save_to_notion=false"
```

The skill will:
1. Query captures from the past 7 days
2. Group by template type
3. If sparse (< 3 captures), ask supplemental questions
4. Generate structured summary
5. Save to Weekly Summaries database

---

## Part 7: Template Reference

### Template Types & Triggers

| Template | Trigger Phrases | Key Fields |
|----------|-----------------|------------|
| **Journal** | "Today I...", "I feel...", "Reflecting on..." | Mood, Summary, People |
| **Task** | "I need to...", "Remind me to...", "Don't forget..." | Due Date, Priority, Status |
| **Idea** | "What if...", "Idea:", "I'm thinking..." | Core Concept, Potential Value |
| **Research** | "Learn about...", "Research...", "I wonder..." | Question, Why It Matters, Status |
| **Product** | "Feature request:", "Bug:", "[Project name]..." | Product, Type, User Impact |
| **General** | (fallback for < 0.7 confidence) | Summary, Suggested Template |

### Adding Custom Templates

1. Create `config/templates/your_template.yaml` using `_template.yaml` as reference
2. Define triggers, fields, and Notion property mappings
3. Restart the service: `docker-compose restart voice-capture`

---

## Part 8: UNRAID-Specific Setup

### 8.1 Using Docker Compose on UNRAID

1. Install **Docker Compose Manager** plugin from Community Applications
2. Clone repo to `/mnt/user/appdata/voice-capture/`
3. Configure `.env` as described above
4. In Docker Compose Manager, add the compose file

### 8.2 Persistent Storage

The docker-compose uses named volumes which persist across container restarts. For UNRAID, you may want to map to specific paths:

```yaml
volumes:
  - /mnt/user/appdata/voice-capture/data:/app/data
  - /mnt/user/appdata/voice-capture/logs:/app/logs
```

---

## Part 9: Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Files not syncing from Drive | Run `rclone ls gdrive:/VoiceCaptures/inbox` to test. Reconnect with `rclone config reconnect gdrive:` |
| Transcription failing | Check OpenAI API key and billing. Verify audio format is M4A/WAV/MP3 |
| Classification wrong template | Adjust confidence threshold in `config/classification.yaml`. Check trigger patterns in templates |
| Notion page not created | Verify database ID and integration has access. Check rate limiting in logs |
| No notifications | Verify Pushover tokens. Test with `python -m src.cli.health_check` |

### View Logs

```bash
# All services
docker-compose logs -f

# Voice capture only
docker-compose logs -f voice-capture

# rclone sync only
docker-compose logs -f rclone

# Check rclone log file
docker-compose exec rclone cat /data/logs/rclone.log
```

### Database Inspection

```bash
# Enter container
docker-compose exec voice-capture bash

# Use sqlite3
sqlite3 /app/data/voice_capture.db
> SELECT id, filename, status, retry_count FROM captures ORDER BY id DESC LIMIT 10;
> SELECT * FROM failure_log ORDER BY id DESC LIMIT 5;
> .quit
```

---

## Part 10: Maintenance

### Regular Tasks

| Task | Frequency | Command |
|------|-----------|---------|
| Check health | Daily (automatic) | Pushover notification |
| Review failed captures | Weekly | `python -m src.cli.queue_status` |
| Update Docker images | Monthly | `docker-compose pull && docker-compose up -d` |
| Refresh OAuth tokens | As needed | `rclone config reconnect gdrive:` |
| Backup database | Weekly | Copy `voice_capture.db` from data volume |

### Updating the System

```bash
cd voice-capture
git pull
docker-compose build
docker-compose up -d
```

---

## Quick Reference Card

```
CAPTURE:     Tap Watch complication → Speak → Tap to stop
MONITOR:     docker-compose logs -f voice-capture
QUEUE:       docker-compose exec voice-capture python -m src.cli.queue_status
RETRY:       docker-compose exec voice-capture python -m src.cli.retry --all-failed
HEALTH:      docker-compose exec voice-capture python -m src.cli.health_check
SYNTHESIS:   claude "Run weekly-voice-synthesis"
```

---

## Architecture Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Apple Watch    │     │    iPhone       │     │  Just Press     │
│  Complication   │────▶│    Shortcut     │────▶│    Record       │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │  Google Drive   │
                                               │ /VoiceCaptures/ │
                                               │     inbox/      │
                                               └────────┬────────┘
                                                         │ rclone sync
                                                         ▼
┌────────────────────────────────────────────────────────────────────┐
│                        Docker Host (UNRAID)                        │
│  ┌──────────────┐     ┌──────────────────────────────────────┐    │
│  │   rclone     │────▶│         voice-capture                │    │
│  │   service    │     │  ┌────────┐  ┌────────┐  ┌────────┐ │    │
│  └──────────────┘     │  │Watcher │─▶│Whisper │─▶│Claude  │ │    │
│                       │  └────────┘  │  API   │  │  API   │ │    │
│                       │              └────────┘  └───┬────┘ │    │
│                       │                              │      │    │
│                       │              ┌───────────────▼────┐ │    │
│                       │              │    Notion API      │ │    │
│                       │              └────────────────────┘ │    │
│                       └──────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │     Notion      │
                                               │ Voice Captures  │
                                               │    Database     │
                                               └─────────────────┘
```

---

*Guide version: 1.0.0 | Last updated: 2026-01-21*
