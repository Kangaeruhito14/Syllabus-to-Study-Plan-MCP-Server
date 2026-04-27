# Syllabus-to-Study-Plan MCP Server

Convert any course syllabus (PDF or text) into a day-by-day study plan with topic weighting and spaced repetition, then export to **JSON/ICS** and push to **Google Calendar** and **Notion**.

## MCP Tools

- `parse_syllabus`: PDF/text → normalized course model (topics, assessments, dates, constraints) with confidence scores
- `detect_exam_dates`: refine assessments/exam dates and confidence
- `apply_course_corrections`: fix title, dates, topics, and schedule inputs after parsing
- `weight_topics`: compute topic weights with rationale
- `generate_study_plan`: generate daily plan (learn/practice/review) with spaced repetition
- `build_plan_report`: generate a polished natural-language study summary
- `export_plan`: export to `json | ics | google_calendar | notion`

## Current Progress

The project is in a solid MVP-plus state.

- PDF syllabus parsing works for text PDFs, with OCR fallback for scanned PDFs
- Study plans can be generated and exported to ICS
- Google Calendar and Notion export flows are implemented
- A correction loop now exists so users can fix missing exam dates or noisy topics
- A natural-language report tool now summarizes the plan in a readable format

Known gaps still being improved:

- extraction quality varies across syllabus layouts
- some PDFs still need manual correction for exam dates/topics
- Google Calendar and Notion sync require real credentials for end-to-end validation

## Quickstart (local)

1) Create a virtualenv and install dependencies.

2) Run the server:

```bash
python -m syllabus_mcp.server
```

FastMCP defaults to STDIO transport. (HTTP transport can be enabled later.)

## Walkthrough

Typical tool flow:

1. `parse_syllabus`
2. `detect_exam_dates`
3. `apply_course_corrections` if anything is missing or wrong
4. `weight_topics`
5. `generate_study_plan`
6. `build_plan_report`
7. `export_plan`

For a ready-to-follow local test and Cursor MCP usage example, see `docs/demo.md`.

## Configuration

Integrations are optional and require credentials:

- Google Calendar: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (and token storage)
- Notion: `NOTION_TOKEN`, `NOTION_DATABASE_ID` (optional, can be created)

## Privacy

By default, the server is designed to process syllabi in-memory and return structured outputs without persisting the raw PDF/text unless you explicitly enable storage.

