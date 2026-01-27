# Summarize Feedback Skill

A Claude Code skill that reads employee feedback entries from the Notion Voice Captures database, synthesizes an evidence-based assessment, and generates a professional `.docx` document.

## Overview

This skill queries your Notion Voice Captures database for entries with Type="Feedback" matching a specified employee name. It synthesizes strengths, areas for development, patterns, and recommendations into a structured assessment, then produces a Word document suitable for performance review preparation.

Notion is read-only. Output is a local `.docx` file.

## Prerequisites

### 1. Notion MCP Server

The Notion MCP (Model Context Protocol) server must be configured and connected to Claude Code.

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

### 2. Notion Database

The Voice Captures database must be accessible and contain Feedback-type entries.

| Database | Environment Variable | Purpose |
|----------|---------------------|---------|
| Voice Captures | `NOTION_VOICE_CAPTURES_DB_ID` | Source of feedback entries |

**Required Feedback Entry Properties:**
- Title (title) — "Employee Name - Brief Topic"
- Date (date) — Capture timestamp
- Type (select) — Must be "Feedback"
- Related To (rich_text) — Employee name
- Tags (multi_select) — Employee first name + topic tags
- Comments (rich_text) — Full transcript

**Page Body Sections** (parsed from Markdown):
- `## Summary` — Feedback type and 2-3 sentence summary
- `## Context` — Project/situation context (optional)
- `## Actionable Items` — Specific behaviors to continue/improve (optional)
- `## Raw Transcript` — Original voice capture text

### 3. python-docx

The `python-docx` package must be installed:
```bash
pip install python-docx>=1.0
```

## Usage

### Basic Invocation

```
/summarize-feedback employee_name="Sarah Chen"
```

Or use aliases:
```
/sf employee_name="Sarah Chen"
/feedback employee_name="Sarah Chen"
```

### With Parameters

```
# Last 6 months instead of default 365 days
/summarize-feedback employee_name="Sarah Chen" days=180

# Specific date range
/summarize-feedback employee_name="Sarah Chen" start_date=2025-07-01 end_date=2026-01-27

# Custom output path
/summarize-feedback employee_name="Sarah Chen" output_path="./reviews/sarah_q4.docx"
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `employee_name` | string | *(required)* | Employee name to match against "Related To" property. Partial matches supported. |
| `days` | integer | 365 | Lookback period in days |
| `start_date` | date | *(calculated)* | Override start date (ISO 8601) |
| `end_date` | date | *(calculated)* | Override end date (ISO 8601) |
| `output_path` | string | `./output/Feedback_Summary_{name}_{datetime}.docx` | Output file path |

## Output Structure

The generated `.docx` document contains:

1. **Title Page** — Employee name, assessment period, generation date, entry count
2. **Executive Summary** — 3-5 sentence overall assessment with trajectory indication
3. **Strengths** — Each with description, frequency rating, and dated evidence citations
4. **Areas for Development** — Each with description, pattern type, and dated evidence
5. **Patterns and Themes** — Trends over time, relationships between observations, situational patterns
6. **Recommendations** — Grouped by type:
   - **Continue** — Behaviors to maintain and reinforce
   - **Develop** — Areas needing improvement with specific actions
   - **Stretch** — Growth opportunities building on existing strengths
7. **Appendix: Individual Feedback Entries** — Chronological listing with date, type, summary, context, actionable items, and raw transcript

**Styling:** Calibri 11pt body, dark blue headings, grey metadata text, page break before appendix.

**Filename Convention:** `Feedback_Summary_{Employee_Name}_{YYYY-MM-DD_HHMMSS}.docx`
- Spaces in employee name replaced with underscores
- Datetime is the generation timestamp

## Execution Flow

When invoked, Claude Code:

1. Checks prerequisites (Notion MCP connected, python-docx installed)
2. Computes the date range (today minus `days`, or uses explicit `start_date`/`end_date`)
3. Queries Notion for pages where Type="Feedback" and Related To contains the employee name
4. Filters by date range
5. Fetches full page content for each matching entry
6. Parses page Markdown into structured fields (Summary, Context, Actionable Items, Transcript)
7. Feeds all entries to Claude for synthesis (strengths, weaknesses, patterns, recommendations)
8. Combines synthesis + entries into JSON, writes to temp file
9. Runs `python scripts/generate_feedback_docx.py` to produce the `.docx`
10. Reports the output file path

## Standalone Script Usage

The `.docx` generator can be run independently:

```bash
# From a JSON file
python scripts/generate_feedback_docx.py --input data.json --output report.docx

# From stdin
cat data.json | python scripts/generate_feedback_docx.py --output report.docx
```

See `skill.yaml` for the full input JSON schema.

## Error Handling

| Error | Resolution |
|-------|------------|
| No entries found | Check employee name spelling, expand date range, or list all employees with Feedback entries |
| Notion connection failed | Verify MCP configuration and API key |
| python-docx missing | Run `pip install python-docx>=1.0` |
| Document generation failed | Run the script directly with `--input` to see the full error |

## Troubleshooting

### "No Feedback entries found"

1. Verify the employee name matches the "Related To" property (try first name only)
2. Check that feedback entries exist with Type="Feedback" in the Voice Captures database
3. Expand the date range with a larger `days` value

### "Notion MCP not connected"

1. Verify the MCP server is configured in your Claude settings
2. Check that `@modelcontextprotocol/server-notion` is installed
3. Restart Claude Code after configuration changes

### "python-docx not installed"

```bash
pip install python-docx>=1.0
```

### Document looks wrong or empty

1. Run the script directly to check for errors:
   ```bash
   python scripts/generate_feedback_docx.py --input temp.json --output test.docx
   ```
2. Inspect the intermediate JSON file to verify data was extracted correctly
3. Ensure Notion pages have the expected Markdown section headers (`## Summary`, etc.)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-27 | Initial release |

## Author

Troy Davis / Stratfield Consulting

## Related Documentation

- [Voice Capture Pipeline PRD](../../docs/prd.md)
- [Feedback Template](../../config/templates/feedback.yaml)
- [Weekly Voice Synthesis Skill](../weekly-voice-synthesis/README.md)
