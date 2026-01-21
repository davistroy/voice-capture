# Weekly Voice Synthesis Skill

A Claude Code skill that synthesizes voice captures from the past week into a structured reflection summary.

## Overview

This skill queries your Notion Voice Captures database for entries from the last 7 days, groups them by template type (Journal, Task, Idea, Research, Product, General), and generates a comprehensive weekly summary. The summary is optionally saved to a dedicated Weekly Summaries database in Notion.

## Prerequisites

Before using this skill, ensure the following are configured:

### 1. Notion MCP Server

The Notion MCP (Model Context Protocol) server must be configured and connected to Claude Code or Claude Desktop.

**Claude Code Configuration** (`~/.claude.json`):
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

**Claude Desktop Configuration** (`claude_desktop_config.json`):
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

### 2. Notion Databases

Two Notion databases are required:

| Database | Environment Variable | Purpose |
|----------|---------------------|---------|
| Voice Captures | `NOTION_VOICE_CAPTURES_DB_ID` | Source of voice capture entries |
| Weekly Summaries | `NOTION_WEEKLY_SUMMARIES_DB_ID` | Destination for generated summaries |

**Voice Captures Database Properties:**
- Title (title) - Capture title
- Date (date) - Capture timestamp
- Type (select) - Template type (Journal, Task, Idea, Research, Product, General)
- Tags (multi_select) - Topic tags
- Device (select) - Capture device (Watch, Phone)

**Weekly Summaries Database Properties:**
- Title (title) - "Weekly Summary: [date range]"
- Week Start (date) - Start of summary period
- Week End (date) - End of summary period
- Capture Count (number) - Total captures in period
- Supplemental Input (checkbox) - Whether user provided additional input

### 3. Notion Integration Access

Your Notion integration must have access to both databases. In Notion:
1. Open each database
2. Click the three-dot menu (...)
3. Select "Connections"
4. Add your integration

## Usage

### Basic Invocation

```bash
# Using Claude Code
claude "Run weekly-voice-synthesis"

# Or use the alias
claude "Run weekly"
```

### With Parameters

```bash
# Specify a different number of days
claude "Run weekly-voice-synthesis with days=14"

# Use specific date range
claude "Run weekly-voice-synthesis with start_date=2026-01-07 end_date=2026-01-14"

# Generate summary without saving to Notion
claude "Run weekly-voice-synthesis with save_to_notion=false"

# Lower the sparse week threshold
claude "Run weekly-voice-synthesis with sparse_threshold=5"
```

### Interactive Mode

When invoked, the skill will:

1. **Query Notion** - Retrieve all voice captures from the specified date range
2. **Group by Type** - Organize captures by their template type
3. **Check for Sparse Week** - If fewer than 3 captures (configurable):
   - Prompt you for supplemental input
   - Ask targeted questions about the week
   - Incorporate your responses into the synthesis
4. **Generate Summary** - Create a structured weekly reflection
5. **Save to Notion** - Optionally create a page in Weekly Summaries database
6. **Return Results** - Display the summary and provide the Notion page URL

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | integer | 7 | Number of days to include |
| `start_date` | date | (calculated) | Override start date (ISO 8601) |
| `end_date` | date | (calculated) | Override end date (ISO 8601) |
| `save_to_notion` | boolean | true | Save summary to Notion |
| `sparse_threshold` | integer | 3 | Minimum captures before prompting for input |

## Output Structure

The generated summary follows this structure:

```markdown
# Weekly Summary: 2026-01-14 to 2026-01-21

## Overview
[2-3 sentence summary of the week]

## Accomplishments
- [Completed items and wins]

## Key Activities
[Narrative about significant work]

## Challenges & Blockers
- [Challenges encountered]

## Ideas Generated
- [Idea title] - [Description] ([Notion link])

## Insights & Reflections
[Patterns and lessons learned]

## Upcoming / Next Week
- [Priorities and upcoming items]

## Capture Statistics
| Type | Count |
|------|-------|
| Journal | X |
| Task | X |
| ... | ... |
| **Total** | **X** |

---
*Generated: [timestamp]*
```

## Sparse Week Handling

When fewer than 3 captures are found (configurable via `sparse_threshold`), the skill prompts for supplemental input:

**Questions asked:**
1. "What were your main work focuses this week?"
2. "Any significant meetings or conversations worth noting?"
3. "What's carrying over to next week?"
4. "Any wins or accomplishments not captured in voice notes?"
5. "Any challenges or blockers you're facing?"

You can respond verbally or type your answers. The supplemental input is incorporated into the synthesis, with a note indicating it was included.

## Error Handling

| Error | Resolution |
|-------|------------|
| No captures found | Skill offers to expand date range or create summary from verbal input |
| Notion connection failed | Verify MCP configuration and API key |
| Database not found | Check database ID and integration access |

## Examples

### Example 1: Standard Weekly Review

```
User: Run weekly-voice-synthesis

Claude: I'll generate your weekly summary for the past 7 days.

[Queries Notion, finds 8 captures]

# Weekly Summary: 2026-01-14 to 2026-01-21

## Overview
This was a productive week focused on client deliverables and the voice capture
project. Good progress on the quarterly planning despite a mid-week blocker.

## Accomplishments
- Completed Q1 planning deck for Acme Corp
- Shipped voice capture pipeline MVP
- Resolved authentication issue in dashboard

...

[Summary saved to Notion: https://notion.so/...]
```

### Example 2: Sparse Week with Supplemental Input

```
User: Run weekly-voice-synthesis

Claude: I found only 2 captures for the past 7 days. Let me ask a few questions
to fill in the gaps.

What were your main work focuses this week?

User: Mostly heads-down on the voice capture project. Had a good strategy session
with the Acme team on Tuesday.

Claude: Any significant meetings or conversations worth noting?

User: The Acme strategy session was the big one. Also had a quick sync with my
accountant about quarterly taxes.

...

[Generates summary incorporating the supplemental input]
```

### Example 3: Custom Date Range

```
User: Run weekly-voice-synthesis with start_date=2026-01-01 end_date=2026-01-07

Claude: I'll generate a summary for January 1-7, 2026.

[Generates summary for the specified date range]
```

## Integration with Voice Capture Pipeline

This skill is designed to work with the Voice Capture to Notion Pipeline. The pipeline automatically:

1. Captures audio from Apple Watch/iPhone
2. Transcribes via OpenAI Whisper
3. Classifies into templates via Claude
4. Creates structured pages in Notion

The weekly synthesis skill then aggregates these captures into actionable weekly reflections.

## Troubleshooting

### "Notion MCP not connected"

1. Verify the MCP server is configured in your Claude settings
2. Check that `@modelcontextprotocol/server-notion` is installed
3. Restart Claude Code/Desktop after configuration changes

### "Database not accessible"

1. Verify the database ID is correct (32-character hex string)
2. Check that your Notion integration has access to the database
3. Ensure the environment variable is set correctly

### "No captures found" (unexpected)

1. Verify captures exist in the Voice Captures database
2. Check that the Date property is populated correctly
3. Ensure the date range parameters are in ISO 8601 format

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-21 | Initial release |

## Author

Troy Davis / Stratfield Consulting

## Related Documentation

- [Voice Capture Pipeline PRD](../../docs/PRD.md)
- [Technical Design Document](../../docs/TDD.md)
- [Implementation Plan](../../IMPLEMENTATION_PLAN.md)
