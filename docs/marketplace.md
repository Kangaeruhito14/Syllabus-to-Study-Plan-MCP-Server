# MCPize Marketplace Listing (Draft)

## Title
Syllabus-to-Study-Plan: PDF → Calendar + Notion Study Schedule

## One-liner
Upload any syllabus PDF (even scanned) and get a day-by-day study plan with spaced repetition, then export to ICS or push to Google Calendar + Notion.

## Who it’s for
- University students and exam candidates
- Bootcamp learners
- Certification prep (AWS, Azure, CompTIA, etc.)

## The problem
Syllabi are long and unstructured; students don’t know how to turn “20 pages” into “what to do today”. Planning takes hours, and most people either cram late or give up.

## What this server does
1) Parses syllabus PDF/text (OCR for scanned PDFs)
2) Extracts topics, assessments, exam dates (with confidence)
3) Weights topics by importance cues
4) Generates a realistic schedule with spaced repetition + buffer days
5) Exports/pushes to tools students actually use

## Tools
- `parse_syllabus`: PDF/text → normalized course model
- `detect_exam_dates`: refine exams/assessments with confidence
- `weight_topics`: compute topic weights with rationale
- `generate_study_plan`: generate daily plan (learn/practice/review)
- `export_plan`: `json | ics | google_calendar | notion`

## Outputs
- JSON schedule (always)
- ICS calendar (works without any integrations)
- Google Calendar push (OAuth token)
- Notion database push (token + database ID)

## Privacy
- Designed to process syllabus data in-memory by default
- No raw PDF storage unless you explicitly add it

## Pricing suggestion
- Free: text input + JSON/ICS export (limited runs)
- Pro: OCR + Notion/Google Calendar + unlimited plans
- Team/School: bulk plans + shared templates

