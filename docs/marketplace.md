# MCPize Marketplace Listing

## Title
Syllabus-to-Study-Plan: PDF → Day-by-Day Study Schedule + Google Calendar + Notion

## One-liner
Upload any course syllabus (PDF or text, including scanned PDFs) and get a personalised day-by-day study plan with spaced repetition — exported to ICS, Google Calendar, or Notion in one call.

## Who it's for
- University and college students
- Bootcamp learners
- Certification candidates (AWS, Azure, CompTIA, PMP, etc.)
- Anyone who needs to turn a raw course outline into a real daily schedule

## The problem
Students receive a 10–30 page syllabus and have no idea how to turn it into "what do I study today?". Manual planning takes hours, most people either cram the night before or give up. A single structured study plan — tied to real exam dates — can be the difference between passing and failing.

## What this server does
1. Parses any syllabus PDF (text or scanned via OCR) or plain-text paste
2. Extracts topics, assessments, and exam dates with confidence scores
3. Lets you correct missing dates or noisy topics in one tool call
4. Weights topics by importance cues (exam frequency, keywords)
5. Generates a realistic day-by-day schedule with spaced repetition and buffer days
6. Exports a polished readable report + pushes to tools students actually use

## Tools (11 total)

### Quick start — one call does everything
- `full_pipeline`: Syllabus → plan → export in one call. Supports coverage mode, spaced repetition mode, tutorial scheduling, all export formats, and dynamic re-sync. **Start here.**

### Step-by-step tools (for fine control — spaced repetition mode only)
- `get_raw_text`: Returns extracted text of any input + `is_likely_syllabus` confidence score
- `parse_syllabus`: PDF (base64) or plain text → CourseModel with topics, assessments, confidence scores
- `detect_exam_dates`: Refine assessments and exam dates; warns about missing dates
- `apply_course_corrections`: Fix course title, add/remove topics, add/remove/update assessments and exam dates
- `weight_topics`: Assign importance scores to topics with rationale
- `generate_study_plan`: Day-by-day schedule with spaced repetition (use `full_pipeline` for coverage mode)
- `build_plan_report`: Polished markdown summary with exam countdown, weekly hours, priority topics
- `export_plan`: Export to `json` | `ics` | `google_calendar` | `notion` (not `notion_daily` — use `full_pipeline`)
- `setup_notion_database`: Create Notion DB for session-based export (one row per session)
- `setup_daily_notion_database`: Create Notion DB for daily plan (one row per day: Topics, Details, Total Minutes, Done checkbox)

## Typical flow

```
full_pipeline(content_type="pdf_base64", content=<base64>, timezone="Asia/Kolkata",
              manual_exam_dates={"Final Exam": "2026-09-10"})
→ report (markdown) + ics calendar ready to import
```

Or step-by-step for full control:
```
parse_syllabus → detect_exam_dates → apply_course_corrections
→ weight_topics → generate_study_plan → build_plan_report → export_plan
```

## Outputs
- Readable markdown study plan report (exam countdown, weekly summary, priority topics)
- JSON schedule (always available)
- ICS calendar file (importable into Google Calendar, Apple Calendar, Outlook, etc.)
- Google Calendar push (OAuth access token required)
- Notion database push (integration token + database ID required)

## Privacy
- Processes syllabus data in-memory by default
- No raw PDF storage unless you explicitly add it
- No data sent to third parties (except Google Calendar / Notion when you provide credentials)

## Pricing suggestion
- Free: text input + JSON/ICS export (up to 5 plans/day)
- Pro: OCR for scanned PDFs + Google Calendar + Notion push + unlimited plans
- Team/School: bulk plan generation + shared course templates + priority support
