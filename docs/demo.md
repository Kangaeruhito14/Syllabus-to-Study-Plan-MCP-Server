# Demo & Walkthrough

## Recommended: one-call quick start

The fastest way to use this server is `full_pipeline` — it runs everything in a single call.

### From text (paste syllabus content)
```json
{
  "content_type": "text",
  "content": "CS101\nMidterm Exam: March 30, 2026\nFinal Exam: May 20, 2026\nWeek 1: Intro to Python\nWeek 2: Data Structures\nWeek 3: Algorithms\nWeek 4: Testing",
  "timezone": "Asia/Kolkata",
  "hours_per_day": 1.5,
  "days_off": ["fri"],
  "export_format": "ics"
}
```

### From PDF (base64-encoded)
```bash
# Convert your PDF to base64 first
base64 -w 0 syllabus.pdf > syllabus.b64
```
Then call `full_pipeline` with:
```json
{
  "content_type": "pdf_base64",
  "content": "<paste full contents of syllabus.b64>",
  "timezone": "Asia/Kolkata",
  "hours_per_day": 2,
  "days_off": ["fri", "sat"],
  "export_format": "ics"
}
```

### Week-based syllabus (no explicit dates)
If your syllabus uses "Week 1, Week 2, ..." instead of real dates, provide them manually:
```json
{
  "content_type": "pdf_base64",
  "content": "<base64>",
  "timezone": "Asia/Kolkata",
  "manual_exam_dates": {
    "Midterm Exam": "2026-07-15",
    "Final Exam": "2026-09-10"
  },
  "export_format": "ics"
}
```

---

## Step-by-step flow (for full control)

Use these 7 tools in order when you want to inspect or correct each step:

1. `parse_syllabus` — PDF/text → CourseModel (topics, assessments, warnings)
2. `detect_exam_dates` — Refine assessment confidence
3. `apply_course_corrections` — Fix missing dates, noisy topics, wrong title
4. `weight_topics` — Score topics by importance
5. `generate_study_plan` — Generate day-by-day schedule
6. `build_plan_report` — Readable markdown report with exam countdown
7. `export_plan` — Export to `ics` / `json` / `google_calendar` / `notion`

---

## Local quick test (no MCP client needed)

From the project root:
```bash
./.venv/bin/python scripts/test_local.py
```

This parses a sample text syllabus, generates a plan, and prints an ICS preview.

---

## Cursor MCP test

This repo includes `.cursor/mcp.json` so Cursor auto-detects the server.

1. Open folder: `/home/anup/All_Types_of_Codes/MCP Server`
2. Go to **Settings → Tools & MCP**
3. Confirm `syllabus-to-study-plan` is enabled (should show "9 tools enabled")
4. In chat, ask: *"Call full_pipeline with content_type='text', content='CS101\nFinal Exam: June 10, 2026\nWeek 1: Intro\nWeek 2: Variables', timezone='UTC'"*

---

## Integrations

See [docs/integrations.md](integrations.md) for step-by-step setup of:
- Google Calendar OAuth
- Notion integration token + `setup_notion_database` tool
