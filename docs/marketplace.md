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

## Tools (8 total)

### Quick start — one call does everything
- `full_pipeline`: Upload syllabus → get complete plan + readable report + ICS export in a single tool call. Accepts `manual_exam_dates` for week-based syllabi. **Start here.**

### Step-by-step tools (for more control)
- `parse_syllabus`: PDF (base64) or plain text → normalized CourseModel with topics, assessments, confidence scores, and constraints
- `detect_exam_dates`: Refine assessments and exam dates; warns about missing dates
- `apply_course_corrections`: Fix course title, add/remove topics, add/remove/update assessments and exam dates — the human-in-the-loop correction step
- `weight_topics`: Assign importance scores to topics with rationale (uses keyword cues + boost_keywords)
- `generate_study_plan`: Build a day-by-day schedule with spaced repetition, buffer days, and configurable hours/days-off/intensity
- `build_plan_report`: Generate a polished natural-language summary with exam countdown, weekly hours view, priority topic list, and first sessions preview
- `export_plan`: Export to `json` | `ics` | `google_calendar` | `notion`

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
