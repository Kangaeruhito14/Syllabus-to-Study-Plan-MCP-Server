# Demo walkthrough

## Goal
Turn a syllabus into a study schedule and export it as an ICS calendar.

## Local quick test (no Cursor integration)

From the project root:

```bash
./.venv/bin/python scripts/test_local.py
```

This will:
- parse a sample syllabus text
- extract topics + exam dates
- weight topics
- generate a day-by-day plan
- export an ICS calendar and print a preview

## Cursor MCP test (Custom MCP Tools)

This repo includes `.cursor/mcp.json` so Cursor can run the server as a local MCP server.

Steps:
1) Open this folder in Cursor: `/home/anup/All_Types_of_Codes/MCP Server`
2) Go to Settings → Tools & MCP
3) Ensure the MCP server `syllabus-to-study-plan` is detected/available
4) Ask your agent to call the tool `parse_syllabus` with pasted syllabus text (or a base64 PDF)

## Example MCP call payloads

### Parse from text

```json
{
  "content_type": "text",
  "content": "CS101\\nFinal Exam: May 20, 2026\\nWeek 1: Intro\\nWeek 2: Arrays\\n",
  "timezone": "UTC"
}
```

### Export to ICS
Call `export_plan` with:

- `format`: `"ics"`
- `plan`: returned from `generate_study_plan`

