# Voice Capture to Notion Pipeline
## Product Requirements Document

**Version:** 0.1 (Draft)  
**Author:** Troy Davis / Stratfield Consulting  
**Date:** January 2026  
**Status:** Requirements Gathering

---

## 1. Problem Statement

Capturing thoughts, ideas, meeting notes, and daily observations throughout the day requires the lowest possible friction. Typing into apps creates cognitive overhead and context-switching costs. Voice capture via Apple Watch/iPhone action button removes that friction — but raw audio recordings sitting in a folder have zero utility without transcription, organization, and retrieval capability.

This system transforms ephemeral voice captures into structured, searchable, synthesizable knowledge stored in Notion.

---

## 2. Goals

- **Frictionless capture:** Single button press starts recording; single press stops it. No app navigation, no decisions at capture time.
- **Fire and forget:** Once recorded, the user never thinks about it again until retrieval.
- **Intelligent organization:** System classifies and structures content into appropriate Notion templates without user intervention.
- **Graceful fallback:** Unclassifiable content goes to a generic page rather than failing or requiring intervention.
- **Weekly synthesis:** On-demand summarization of the week's captures into a reflection/planning format.
- **Reliable operation:** Errors are handled gracefully with notifications; no silent failures.

## 3. Non-Goals

- Real-time transcription or immediate feedback
- Mobile app development (leveraging existing apps)
- Multi-user support (single-user system)
- Complex workflow routing or approvals
- Audio editing or enhancement

---

## 4. User Stories

**Daily Capture:**
> As Troy, I press the action button on my Apple Watch while walking to capture a thought. I press again when done. I never think about it again until I want to retrieve or synthesize that information.

**Retrieval:**
> As Troy, I browse my Notion database to find a specific idea I captured last Tuesday, or I ask Claude (via Notion MCP) to find captures related to a specific topic.

**Weekly Synthesis:**
> As Troy, I invoke a Claude skill on Sunday evening that synthesizes my week's captures into a structured reflection: accomplishments, challenges, upcoming priorities.

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CAPTURE LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   iPhone 15 Pro Max / Apple Watch Ultra 2                               │
│   Action Button → Just Press Record                                      │
│                          │                                               │
│                          ▼                                               │
│   iOS Shortcut (on recording complete) → Save to Google Drive folder    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         PROCESSING LAYER                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Home Server (always-on)                                               │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  Folder Watcher Service                                          │   │
│   │  - Monitors Google Drive sync folder for new .m4a/.wav files    │   │
│   │  - Sync via rclone (polling every 60 seconds)                   │   │
│   │  - Queues files for processing                                   │   │
│   │  - Handles retries on failure                                    │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  Transcription Service                                           │   │
│   │  [NEEDS CLARIFICATION: Which transcription endpoint?]            │   │
│   │  Option A: OpenAI Whisper API (simplest, ~$0.006/min)           │   │
│   │  Option B: Deepgram API (fast, good accuracy)                   │   │
│   │  Option C: Local Whisper on Jetson Orin (free, medium model)    │   │
│   │  Option D: Local Whisper on dual RTX 3090 rig (large-v3)        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  Classification & Structuring Service (LLM)                      │   │
│   │  [NEEDS CLARIFICATION: Which LLM?]                               │   │
│   │  Option A: Claude API (Sonnet for cost/quality balance)         │   │
│   │  Option B: Local LLM on RTX 3090 rig                            │   │
│   │  Option C: OpenAI GPT-4o-mini                                   │   │
│   │                                                                  │   │
│   │  - Classifies content type                                       │   │
│   │  - Extracts structured fields per template                       │   │
│   │  - Falls back to generic if no template fits                     │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  Notion Integration Service                                      │   │
│   │  - Creates page in appropriate database                          │   │
│   │  - Applies template structure                                    │   │
│   │  - Stores original transcript as property or page content        │   │
│   │  - On success: deletes source audio file                         │   │
│   │  - On failure: retries, then notifies                            │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          STORAGE LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Notion Workspace                                                       │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  Voice Captures Database                                         │   │
│   │  - Date/time captured                                            │   │
│   │  - Content type (template used)                                  │   │
│   │  - Structured fields (vary by template)                          │   │
│   │  - Raw transcript                                                │   │
│   │  - Source device (Watch/Phone)                                   │   │
│   │  - Processing metadata                                           │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SYNTHESIS LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Claude Skill (on-demand)                                              │
│   - Queries Notion for week's captures via MCP                          │
│   - Synthesizes into weekly reflection format                           │
│   - Prompts for input on sparse weeks                                   │
│   - Creates Weekly Summary page in Notion                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Component Specifications

### 6.1 Capture Layer

**Hardware:**
- iPhone 15 Pro Max (primary capture device)
- Apple Watch Ultra 2 (convenience capture)

**Software:**
- Just Press Record (handles recording, transcription not used)
- iOS Shortcuts (triggered on recording complete)

**Shortcut Logic:**
```
TRIGGER: Just Press Record recording completed
ACTION 1: Get latest recording from Just Press Record
ACTION 2: Save file to Google Drive folder: /VoiceCaptures/inbox/
ACTION 3: (Optional) Haptic confirmation
```

[NEEDS CLARIFICATION: Do you want a notification/haptic when the file is saved to Google Drive, confirming the handoff worked?]

**File Naming Convention:**
`{timestamp}_{device}.m4a`
Example: `2026-01-20T143022_watch.m4a`

### 6.2 Google Drive Sync & Folder Watcher Service

**Sync Technology:** rclone with Google Drive

**rclone Setup:**
```bash
# One-time configuration
rclone config  # Follow prompts to authenticate with Google Drive

# Cron job for sync (every 60 seconds)
* * * * * rclone sync gdrive:/VoiceCaptures/inbox /home/user/voice-captures/inbox --checksum

# Alternative: rclone mount for FUSE filesystem (always-on)
rclone mount gdrive:/VoiceCaptures /home/user/gdrive --vfs-cache-mode writes
```

**Folder Watcher Technology:** Python with watchdog library (or Node.js with chokidar)

**Behavior:**
- Monitors `/home/user/voice-captures/inbox/` (local rclone sync target)
- On new file detected:
  - Waits 2 seconds for file write completion
  - Validates file is audio format
  - Moves to `/processing/` folder
  - Enqueues for transcription
- Maintains processing queue with retry logic
- Logs all operations

**Latency Note:** With cron-based rclone sync, expect 30-90 seconds from iOS save to local file availability. This is acceptable for batch processing.

**State Management:**
- SQLite database tracking: filename, status, timestamps, retry count, error messages
- Statuses: `pending`, `transcribing`, `classifying`, `posting`, `complete`, `failed`

### 6.3 Transcription Service

[NEEDS CLARIFICATION: Select primary transcription approach]

**Recommendation:** Start with OpenAI Whisper API for simplicity and accuracy. Migrate to local if volume/cost justifies it.

**Interface:**
```python
def transcribe(audio_path: str) -> TranscriptionResult:
    """
    Returns:
        TranscriptionResult:
            text: str  # Full transcript
            segments: list  # Timestamped segments (if available)
            confidence: float  # Overall confidence score
            duration_seconds: float
            language: str
    """
```

**Error Handling:**
- Retry 3x with exponential backoff on API errors
- On persistent failure: move file to `/failed/`, notify user

### 6.4 Classification & Structuring Service

**Input:** Raw transcript text + metadata (duration, timestamp, device)

**Process:**
1. Send transcript to LLM with template definitions
2. LLM returns: selected template + structured fields
3. If confidence below threshold or no template fits: use generic template

**LLM Prompt Structure:**
```
You are classifying and structuring voice capture transcripts.

Available templates:
{template_definitions}

Transcript metadata:
- Captured: {timestamp}
- Duration: {duration}
- Device: {device}

Transcript:
"""
{transcript_text}
"""

Respond with JSON:
{
  "template": "template_name" | "generic",
  "confidence": 0.0-1.0,
  "fields": { ... template-specific fields ... },
  "title": "suggested page title",
  "tags": ["tag1", "tag2"]
}
```

### 6.5 Notion Integration Service

**Authentication:** Notion API key (internal integration)

**Operations:**
- Create page in Voice Captures database
- Set properties based on template
- Add page content (structured + raw transcript)
- On success: delete source audio, update status
- On failure: retry 3x, then notify

[NEEDS CLARIFICATION: Should the raw transcript be stored as a page property, in the page body, or both?]

### 6.6 Notification Service

**Channels:**
[NEEDS CLARIFICATION: Preferred notification method(s)]
- Option A: Pushover (simple, reliable push notifications)
- Option B: Email
- Option C: Slack/Discord webhook
- Option D: iOS Shortcuts notification via webhook
- Option E: Notion page in an "Errors" database

**Events to Notify:**
- Processing failure after retries exhausted
- Daily summary: X captures processed successfully, Y failed
- (Optional) Each successful capture confirmation

**Recommendation:** Pushover for failures + daily summary; skip per-capture confirmations to maintain fire-and-forget experience.

---

## 7. Template Definitions

[NEEDS CLARIFICATION: Review and refine these templates]

### 7.1 Meeting Note

**Trigger Patterns:** "meeting with...", "just finished talking to...", "call with...", discussion of attendees, action items

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Meeting Title | Title | Auto-generated from context |
| Date | Date | Capture timestamp |
| Attendees | Multi-select / Text | People mentioned |
| Summary | Rich text | 2-3 sentence summary |
| Key Points | Rich text | Bulleted main discussion points |
| Action Items | Rich text | Extracted commitments/tasks |
| Decisions | Rich text | Any decisions made |
| Follow-ups | Rich text | Next steps mentioned |
| Raw Transcript | Rich text | Full original text |

### 7.2 Idea / Brain Dump

**Trigger Patterns:** "idea:", "what if...", "I'm thinking...", speculative language, concept exploration

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Idea Title | Title | Core concept in 5-10 words |
| Date | Date | Capture timestamp |
| Category | Select | [NEEDS CLARIFICATION: What categories? Tech, Business, Personal, Creative, etc.] |
| Core Concept | Rich text | 1-2 sentence distillation |
| Elaboration | Rich text | Supporting thoughts, context |
| Related To | Relation | Link to related pages if identifiable |
| Potential Value | Select | High / Medium / Low / Unknown |
| Next Steps | Rich text | Any mentioned follow-ups |
| Raw Transcript | Rich text | Full original text |

### 7.3 Task / To-Do

**Trigger Patterns:** "I need to...", "don't forget to...", "remind me to...", "task:", imperative statements

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Task | Title | Action item |
| Date Created | Date | Capture timestamp |
| Due Date | Date | If mentioned, otherwise empty |
| Priority | Select | High / Medium / Low (inferred or stated) |
| Context | Rich text | Why, for whom, related project |
| Status | Select | Not Started (default) |
| Raw Transcript | Rich text | Full original text |

[NEEDS CLARIFICATION: Do you want tasks to also sync to a dedicated task manager (Reminders, Todoist, etc.) or Notion-only?]

### 7.4 Journal / Reflection

**Trigger Patterns:** "today I...", "feeling...", "reflecting on...", first-person narrative about experiences or emotions

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Entry Title | Title | Date + brief theme |
| Date | Date | Capture timestamp |
| Mood | Select | [NEEDS CLARIFICATION: Do you want mood tracking? Options?] |
| Summary | Rich text | Brief summary |
| Full Entry | Rich text | Narrative content |
| Gratitude | Rich text | If mentioned |
| Challenges | Rich text | If mentioned |
| Raw Transcript | Rich text | Full original text |

### 7.5 Project Update

**Trigger Patterns:** "project update:", mentions of specific project names, progress language, blockers

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Project | Title / Relation | Project name |
| Date | Date | Capture timestamp |
| Status Summary | Rich text | Current state |
| Progress | Rich text | What's been accomplished |
| Blockers | Rich text | Issues or obstacles |
| Next Steps | Rich text | Planned work |
| Raw Transcript | Rich text | Full original text |

[NEEDS CLARIFICATION: Do you have an existing Notion projects database to link to?]

### 7.6 Client / Consulting Note

**Trigger Patterns:** Client names, "engagement", "deliverable", billable work context

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Title | Title | Client + topic |
| Client | Select / Relation | Client name |
| Date | Date | Capture timestamp |
| Type | Select | Meeting, Insight, Issue, Opportunity |
| Summary | Rich text | Key content |
| Action Required | Checkbox | Is follow-up needed? |
| Follow-up | Rich text | Specific next steps |
| Raw Transcript | Rich text | Full original text |

[NEEDS CLARIFICATION: List of current/recent clients to recognize?]

### 7.7 Generic (Fallback)

**Trigger:** No other template matches with sufficient confidence

**Structured Fields:**
| Field | Type | Description |
|-------|------|-------------|
| Title | Title | Auto-generated from first sentence or summary |
| Date | Date | Capture timestamp |
| Duration | Number | Recording length in seconds |
| Device | Select | Watch / Phone |
| Summary | Rich text | LLM-generated 2-3 sentence summary |
| Content | Rich text | Full transcript, lightly formatted |
| Suggested Category | Select | LLM's best guess at category |
| Raw Transcript | Rich text | Full original text |

---

## 8. Weekly Synthesis Specification

### 8.1 Claude Skill Definition

**Skill Name:** Weekly Voice Capture Synthesis

**Trigger:** User invokes manually (e.g., "Synthesize my week" or "Weekly summary")

**Skill Behavior:**

1. **Query Notion** via MCP for all Voice Captures from the past 7 days
2. **Assess volume:**
   - If < 3 captures: Prompt user for additional context
     - "I found only {N} captures this week. What else was significant that you didn't record?"
   - If >= 3 captures: Proceed with synthesis
3. **Generate Weekly Summary** with the following structure:

### 8.2 Weekly Summary Template

```markdown
# Week of {start_date} - {end_date}

## Overview
{2-3 sentence summary of the week's themes and focus areas}

## Accomplishments
- {Bullet list of completed work, wins, progress}

## Key Activities
{Narrative of significant meetings, work sessions, decisions}

## Challenges & Blockers
- {Issues encountered}
- {Unresolved problems}

## Ideas Generated
{Summary of any ideas captured, with links to original pages}

## Insights & Reflections
{Patterns noticed, lessons learned}

## Upcoming / Next Week
- {Extracted from captures that mention future plans}
- {Inferred priorities based on open items}

## Capture Statistics
- Total captures: {N}
- By type: {breakdown}
- Total recording time: {X minutes}

---
*Generated from {N} voice captures*
```

### 8.3 Sparse Week Handling

When captures are sparse, Claude should:

1. Present what was captured
2. Ask targeted questions:
   - "What were your main work focuses this week?"
   - "Any significant meetings or conversations?"
   - "What's carrying over to next week?"
3. Incorporate verbal responses into the synthesis
4. Note in the summary that it includes supplemental input

---

## 9. Error Handling Strategy

### 9.1 Error Categories & Responses

| Error Type | Detection | Response | User Notification |
|------------|-----------|----------|-------------------|
| Google Drive sync failure | File not appearing within 5 min of recording | N/A (outside system control) | None (user will notice) |
| rclone sync failure | Cron job errors, no new files syncing | Check rclone logs, re-auth if needed | Daily summary if persistent |
| File corruption | Invalid audio format | Move to `/failed/`, log | Daily summary |
| Transcription API down | HTTP 5xx, timeout | Retry 3x, 5min backoff | After 3 failures |
| Transcription quality issue | Confidence < 0.5 | Process anyway, flag in Notion | None |
| LLM API failure | HTTP error, timeout | Retry 3x | After 3 failures |
| LLM invalid response | JSON parse failure | Retry with different prompt | After 3 failures |
| Notion API failure | HTTP error | Retry 3x, exponential backoff | After 3 failures |
| Notion rate limit | HTTP 429 | Backoff per Retry-After header | None |

### 9.2 Failed Processing Recovery

Files that fail all retries:
1. Move to `/failed/` directory
2. Create entry in `failures` SQLite table with error details
3. Send notification with filename and error
4. User can manually review and re-queue via admin script

### 9.3 Daily Health Check

Scheduled job (e.g., 9 PM daily):
- Count: captures received, processed successfully, failed
- Alert if: failure rate > 20% OR queue backed up > 10 items
- Send daily summary notification with stats

---

## 10. Technical Requirements

### 10.1 Home Server Requirements

- **OS:** Linux (Ubuntu/Debian) or macOS
- **Python:** 3.10+
- **Storage:** Minimal (audio deleted after processing)
- **Network:** Reliable internet for API calls
- **Uptime:** Should be always-on; captures queue in Google Drive if server offline

### 10.2 External Services

| Service | Purpose | Authentication | Cost |
|---------|---------|----------------|------|
| Google Drive | File sync | OAuth (via rclone) | Free tier sufficient |
| OpenAI Whisper API | Transcription | API key | ~$0.006/min |
| [LLM Provider] | Classification | API key | Varies |
| Notion | Storage | Integration token | Free tier likely sufficient |
| Pushover | Notifications | API key + user key | $5 one-time |

### 10.3 Notion Setup

**Required:**
- Notion workspace
- Internal integration with capabilities: Read/Write content, Read/Write databases
- Voice Captures database with schema matching template fields
- Weekly Summaries database (or page location)

[NEEDS CLARIFICATION: Existing Notion workspace structure? Create new dedicated area or integrate into existing?]

### 10.4 Data Retention

| Data Type | Retention | Location |
|-----------|-----------|----------|
| Audio files | Deleted on successful Notion post | Google Drive (transient) |
| Processing logs | 90 days | Home server |
| Failed audio | Until manual review | `/failed/` folder |
| Transcripts | Permanent | Notion |
| Weekly summaries | Permanent | Notion |

---

## 11. Implementation Phases

### Phase 1: Core Pipeline (MVP)
- [ ] Google Drive folder structure setup
- [ ] rclone configuration and cron sync job
- [ ] iOS Shortcut for Just Press Record → Google Drive
- [ ] Folder watcher service
- [ ] Transcription integration (Whisper API)
- [ ] Generic template only (no classification)
- [ ] Basic Notion page creation
- [ ] Simple error logging

**Exit Criteria:** Voice capture on Watch → appears in Notion within 5 minutes

### Phase 2: Classification & Templates
- [ ] LLM classification service
- [ ] Template definitions finalized
- [ ] Structured field extraction
- [ ] Template-specific Notion pages
- [ ] Fallback to generic template

**Exit Criteria:** Captures auto-categorize correctly >80% of the time

### Phase 3: Reliability & Notifications
- [ ] Pushover integration
- [ ] Retry logic hardening
- [ ] Daily health check job
- [ ] Failed file recovery workflow
- [ ] Processing dashboard (optional)

**Exit Criteria:** No silent failures; user always knows system status

### Phase 4: Weekly Synthesis
- [ ] Claude skill definition
- [ ] Notion MCP integration testing
- [ ] Weekly summary template
- [ ] Sparse week prompting logic

**Exit Criteria:** On-demand weekly synthesis produces useful output

---

## 12. Open Questions

[NEEDS CLARIFICATION] items consolidated:

1. **Transcription endpoint:** OpenAI Whisper API (recommended), Deepgram, local Whisper on Jetson, or local on RTX 3090?

2. **LLM for classification:** Claude API, local LLM, or OpenAI?

3. **Confirmation feedback:** Do you want haptic/notification on successful Google Drive save?

4. **Notification method:** Pushover, email, Slack, or other?

5. **Raw transcript storage:** Property, page body, or both?

6. **Idea categories:** What categories for the Idea template?

7. **Task sync:** Notion-only or also sync to Reminders/Todoist?

8. **Mood tracking:** Include in Journal template? What options?

9. **Existing Notion projects database:** Do you have one to link Project Updates to?

10. **Client list:** Current clients to recognize in transcripts?

11. **Notion workspace structure:** New area or integrate into existing?

---

## 13. Success Metrics

- **Capture friction:** Time from thought to recording started < 3 seconds
- **Processing latency:** Recording complete to Notion page < 5 minutes (95th percentile)
- **Classification accuracy:** >80% correct template selection (spot-check weekly)
- **System reliability:** <1% capture loss rate
- **Usage:** Sustained capture rate over 30 days indicates value

---

## Appendix A: Alternative Architectures Considered

### A.1 Shortcuts → API Direct
Rejected: Network reliability issues, timeout constraints, no offline tolerance.

### A.2 iCloud Folder Watch
Rejected: Linux iCloud access is fragile; authentication issues.

### A.3 Dropbox Sync
Considered: Dropbox has real-time sync with Linux client. However, the Dropbox Linux client has had reliability issues, and user already has Google Drive connected to other tools (Claude MCP). Google Drive via rclone is more predictable.

### A.4 Vercel Serverless
Rejected: Timeout constraints (60s max) may be exceeded by long recordings + LLM processing.

### A.5 Just Press Record Built-in Transcription
Not used for pipeline: Quality is good but no structured output or API access to transcripts.

---

## Appendix B: Just Press Record Settings

Recommended settings for pipeline compatibility:
- **Recording Format:** [NEEDS CLARIFICATION: M4A vs WAV? M4A is smaller, WAV is lossless]
- **iCloud Sync:** Disabled (using Google Drive via Shortcuts instead)
- **Auto-Transcribe:** Optional (not used by pipeline)
- **Apple Watch Complication:** Add to watch face for quick access
