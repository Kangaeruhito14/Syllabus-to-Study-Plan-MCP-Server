# Syllabus-to-Study-Plan MCP Server

[![CI](https://github.com/Kangaeruhito14/Syllabus-to-Study-Plan-MCP-Server/actions/workflows/ci.yml/badge.svg)](https://github.com/Kangaeruhito14/Syllabus-to-Study-Plan-MCP-Server/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCPize](https://mcpize.com/badge/@Kangaeruhito14/syllabus-to-study-plan)](https://mcpize.com/mcp/syllabus-to-study-plan)
[![MCP](https://img.shields.io/badge/protocol-MCP%20stdio-green.svg)](https://modelcontextprotocol.io)

> **Upload your syllabus (PDF, DOCX, HTML, or text). Tell it your semester dates. Get a day-by-day study plan with interleaved review, tutorial-aware scheduling, and live sync to Google Calendar and Notion.**

Works inside **Cursor, VS Code, Claude Desktop, Windsurf**, and any MCP-compatible AI editor.  
No paid API keys required. Runs entirely on your machine.

---

## What it actually does (honest)

### Input
Accepts: **PDF** (text or scanned), **DOCX**, **HTML**, **URL**, or **plain text paste**.  
Handles: single-course syllabi, multi-course program documents (4-year plans, semester guides).

### What it extracts
- Course title and subjects
- Topic list (in curriculum order, from any of 5 detected formats)
- Assessments and exam dates (when present in the document)
- A `courses_list` grouping for multi-course program syllabi

### What it builds
Two planning modes:

**Coverage mode** (`plan_mode="coverage"`) — *for most students*  
No exam dates needed. Give it a start and end date; it distributes all topics evenly.  
Default behaviour: **learn a topic today → review it tomorrow** (25 min), then learn the next topic.  
This is the interleaved schedule, not "learn everything then review at the end".

**Spaced repetition mode** (`plan_mode="spaced_repetition"`)  
Anchored to exam dates. Reviews at +1d, +3d, +7d, +14d, +28d intervals. Buffer days every 8 sessions.

### Tutorial-aware scheduling
When you know tutorial/test dates (even if you find out mid-semester), pass them as `tutorial_dates`.  
The MCP automatically blocks those days and converts the N days before each tutorial into focused prep sessions for that exact topic. Re-run anytime — Notion and Calendar update themselves.

### Where it puts the plan
| Export | What you get |
|---|---|
| `ics` | `.ics` file — import into any calendar app |
| `json` | Raw structured data |
| `notion_daily` | One Notion page per day: Date, Topics, Details (`[review] X — 25 min` / `[learn] Y — 60 min`), Total Minutes, Done checkbox |
| `notion` | One Notion page per session (original format) |
| `google_calendar` | Live events pushed to your Google Calendar, stacked in the evening (default 8 PM) |

**Dynamic re-sync:** Call `full_pipeline` again with changed parameters (new tutorial dates, different days-off, different study hour, etc.) — it updates Notion rows and Google Calendar events in-place, deletes stale ones, creates new ones. No manual editing.

---

## Honest limitations

| Limitation | Detail |
|---|---|
| **Multi-course syllabi** | For 4-year program PDFs, the tool extracts topics from the whole document. To plan one semester, your AI assistant must first identify which pages cover that semester (e.g. via `get_raw_text`), then pass only that section as text. |
| **Extraction accuracy** | ~80–90% for well-formatted syllabi. Very non-standard layouts may need manual fixes via `apply_course_corrections`. |
| **No exam dates in PDF** | Common for university syllabi. Use `plan_mode="coverage"` — no exam date needed. Add tutorials later via `tutorial_dates`. |
| **Google Advanced Protection** | If you are enrolled in Google's Advanced Protection Program, the OAuth flow may require additional steps. Access tokens may expire faster and re-authorization may be needed more frequently. The `client_secret.json` + `refresh_token` flow described below still works, but expect occasional re-auth prompts. |
| **Notion token format** | Both `secret_...` (internal integration) and `ntn_...` (OAuth/native) tokens work. |
| **Notion push speed** | Notion's API rate-limits at ~3 requests/second. A 96-day plan takes ~35 seconds to push. The MCP handles this automatically with back-off and retry — you just wait. |
| **Scanned PDFs** | OCR via Tesseract. Quality depends on scan resolution. Works for most university scans; very low-quality scans may miss topics. |

---

## Quick start

### 1. Install

```bash
git clone https://github.com/Kangaeruhito14/Syllabus-to-Study-Plan-MCP-Server.git
cd Syllabus-to-Study-Plan-MCP-Server

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# For scanned PDF support (optional):
# Ubuntu/Debian: sudo apt-get install tesseract-ocr poppler-utils
# macOS:         brew install tesseract poppler
```

### 2. Connect to your AI editor

| Editor | How |
|---|---|
| **Cursor** | Settings → Tools & MCP → add the server entry (see `docs/client-setup.md`) |
| **VS Code** | `.vscode/mcp.json` included — open the folder and the extension picks it up |
| **Claude Desktop** | See [docs/client-setup.md](docs/client-setup.md) |
| **Windsurf** | See [docs/client-setup.md](docs/client-setup.md) |

### 3. Use it — everyday student flow

```
Ask your AI:

"Parse my syllabus for 3rd year 2nd semester.
 Study period: 24 May to 27 August.
 No exam dates yet — I'll add tutorials when I know them.
 Push the plan to my Google Calendar (evening study, 8 PM)
 and to Notion as a daily checklist."
```

The AI calls `full_pipeline` with:

```json
{
  "content_type": "pdf_base64",
  "content": "<base64 of your PDF>",
  "plan_mode": "coverage",
  "course_start_date": "2025-05-24",
  "study_end_date": "2025-08-27",
  "study_start_hour": 20,
  "next_day_review": true,
  "review_minutes": 25,
  "session_minutes": 60,
  "export_format": "notion_daily",
  "notion_token": "ntn_...",
  "notion_daily_database_id": "...",
  "gcal_access_token": "ya29...",
  "gcal_refresh_token": "1//...",
  "gcal_client_id": "...",
  "gcal_client_secret": "..."
}
```

**Later, when you know your tutorial dates:**

```
"Tutorial for Microprocessors on July 10. Prep me 4 days before."
```

The AI re-calls `full_pipeline` with:

```json
{
  "tutorial_dates": [
    {"date": "2025-07-10", "topic_hint": "Microprocessors", "prep_days": 4}
  ]
}
```

Google Calendar and Notion update automatically. No manual edits.

---

## Tools reference

**11 tools** exposed over MCP stdio.

### One-call tool (start here)

| Tool | What it does |
|---|---|
| `full_pipeline` | Syllabus → plan → export in one call. Supports both planning modes, all export formats, inline credentials, tutorial scheduling, and dynamic re-sync. |

### Step-by-step tools (for fine control)

> **Important:** The step-by-step chain below only supports **spaced repetition mode**.
> Coverage mode (interleaved review, tutorial-aware scheduling, `notion_daily` export) is available
> **exclusively through `full_pipeline`**. If you want coverage mode, use `full_pipeline` — not this chain.

| Tool | What it does |
|---|---|
| `get_raw_text` | Returns the full extracted text of any input (PDF/DOCX/HTML/URL/text). Use this when extraction looks wrong — read the text yourself and fix with `apply_course_corrections`. Also returns `is_likely_syllabus` confidence score. |
| `parse_syllabus` | PDF/text → `CourseModel` (title, topics, assessments, confidence scores). Returns `courses_list` for multi-course documents. |
| `detect_exam_dates` | Refines assessments and exam dates with confidence and missing-date warnings. |
| `apply_course_corrections` | Fix anything in a `CourseModel`: title, timezone, add/remove topics, add/update/remove assessments, override dates. |
| `weight_topics` | Assigns importance scores to topics (used by spaced repetition mode to prioritise). |
| `generate_study_plan` | `CourseModel` + `StudyPreferences` → `StudyPlan` with **spaced repetition only**. For coverage mode (interleaved review, tutorial scheduling) use `full_pipeline` instead. |
| `build_plan_report` | `CourseModel` + `StudyPlan` → polished Markdown report (exam countdown, weekly hours, priority topics, first 7 sessions). |
| `export_plan` | `StudyPlan` → ICS / JSON / Notion (sessions) / Google Calendar. Requires credentials for live exports. Does **not** support `notion_daily` — use `full_pipeline` for that. |
| `setup_notion_database` | Creates a Notion database for session-based export (one row per session). Run once, use the returned `database_id`. |
| `setup_daily_notion_database` | Creates a Notion database for the daily plan (one row per day: Date, Topics, Details, Total Minutes, Done checkbox). Run once, use the returned `database_id` as `notion_daily_database_id`. |

### Step-by-step flow (spaced repetition mode only)

```
parse_syllabus
    ↓
detect_exam_dates          ← exam dates required for this mode
    ↓
apply_course_corrections   ← fix anything wrong or missing
    ↓
weight_topics
    ↓
generate_study_plan        ← spaced repetition mode only
    ↓
build_plan_report
    ↓
export_plan → ics / json / notion / google_calendar
              (notion_daily not available here — use full_pipeline)
```

### Coverage mode flow (use full_pipeline)

```
full_pipeline (plan_mode="coverage")
  ├─ content_type + content   ← your syllabus
  ├─ course_start_date + study_end_date
  ├─ next_day_review=true     ← interleaved learn+review (default)
  ├─ tutorial_dates           ← optional, add anytime
  ├─ export_format            ← notion_daily / google_calendar / ics / json
  └─ credentials              ← notion_token / gcal_* tokens
```

---

## Study plan features

### Coverage mode (everyday student)
- **One topic per day** (when days ≥ topics); packed per day when the semester is short
- **Next-day review** (default on): 25 min recap of yesterday's topic, shown first in the day — then the new topic. Not "review everything at the end"
- **Tutorial-aware**: provide `tutorial_dates` at any time; prep days and tutorial days are auto-inserted and the rest of the plan adjusts
- **Revision tail**: after all topics are covered, remaining days become revision/mixed-practice sessions

### Spaced repetition mode (exam-driven)
- Review intervals: +1d, +3d, +7d, +14d, +28d (compressed when exam is close)
- Buffer days every 8 sessions (configurable by intensity: light/standard/intense)
- Topics weighted by importance cues (midterm mentions, exam proximity, custom keywords)

### Calendar scheduling
- `study_start_hour` (default 20 = 8 PM): all events start at this hour
- Days with both review + learn stack cleanly:  
  e.g. `20:00–20:25 [review]` → `20:30–21:30 [learn]`
- Tutorial prep and tutorial days appear as separate event types

---

## Google Calendar setup

**What you need:**
- `client_id` and `client_secret` — from Google Cloud Console (free)
- `access_token` — short-lived (~1 hour); generated once via OAuth
- `refresh_token` — long-lived; lets the server renew automatically

**Step-by-step:**

1. [console.cloud.google.com](https://console.cloud.google.com) → new or existing project
2. **APIs & Services → Library** → search **Google Calendar API** → **Enable**
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
4. Choose **Desktop app** → **Create** → **Download JSON** (save as `client_secret.json`)
5. Run this script once (inside your `.venv`):

```python
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
)
creds = flow.run_local_server(port=0)

print("access_token: ", creds.token)
print("refresh_token:", creds.refresh_token)
print("client_id:    ", creds.client_id)
print("client_secret:", creds.client_secret)
```

6. Paste all four values into `full_pipeline` (`gcal_access_token`, `gcal_refresh_token`, `gcal_client_id`, `gcal_client_secret`).

> **Google Advanced Protection users:** The standard OAuth flow above still works, but you may need to re-authorize more often. If the MCP reports an auth error, re-run step 5 to get a fresh `access_token` and `refresh_token`. Store them securely — do not commit them to git.

---

## Notion setup

**What you need:**
- `notion_token` — your integration secret (`secret_...` or `ntn_...` format both work)
- `notion_daily_database_id` — for the daily plan (created by `setup_daily_notion_database`)
- `notion_database_id` — for session-based export (created by `setup_notion_database`)

**Step-by-step (daily plan):**

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Name it (e.g. "Study Plan"), select your workspace → **Submit**
3. Copy the **Internal Integration Token** — this is your `notion_token`
4. Open any Notion page where you want the plan → copy the page ID from the URL  
   (last 32 hex characters after the final `/`)
5. Call `setup_daily_notion_database` with your token + page ID → copy the returned `database_id`
6. Open the new database in Notion → **... → Connections** → connect your integration
7. Use `notion_token` + `notion_daily_database_id` in `full_pipeline` with `export_format: "notion_daily"`

The database schema created:

| Column | Type | Content |
|---|---|---|
| Name | Title | `2025-05-25 — Sunday` |
| Date | Date | the calendar date |
| Day | Text | `Sunday, 25 May 2025` |
| Topics | Text | topic titles for that day (newline-separated) |
| Details | Text | `[review] Topic X — 25 min` / `[learn] Topic Y — 60 min` |
| Total Minutes | Number | total study time that day |
| Done | Checkbox | tick off when done |

---

## Running tests

```bash
pytest tests/ -v
```

51 tests across extraction, planner, and all server tools.

```
tests/test_extract.py        — PDF/text extraction, 5 format types, non-syllabus detection
tests/test_planner.py        — weight_topics, schedule generation, spaced repetition
tests/test_server_tools.py   — all 11 MCP tools end-to-end
```

---

## Project structure

```
syllabus_mcp/
  server.py      — FastMCP server, all 11 tool definitions
  extract.py     — PDF/text → CourseModel (5 extraction strategies + non-syllabus detection)
  planner.py     — coverage plan (interleaved review + tutorial-aware) + spaced repetition plan
  exporters.py   — ICS export + Notion push (session and daily, idempotent, rate-limited)
  gcal.py        — Google Calendar push (idempotent, evening scheduling, multi-session stacking)
  ocr.py         — OCR fallback for scanned PDFs (Tesseract)
  models.py      — Pydantic data models (CourseModel, StudyPlan, SessionType, etc.)

tests/
  test_extract.py        — extraction unit tests (21 real syllabus files)
  test_planner.py        — planner unit tests
  test_server_tools.py   — integration tests for all tools

docs/
  client-setup.md   — setup guide for Cursor, VS Code, Claude Desktop, Windsurf
  integrations.md   — Google Calendar + Notion credential setup in full detail
```

---

## Privacy

- Processes syllabus data **in-memory only** — nothing is stored to disk by default
- No data is sent to any third party except Google Calendar / Notion when you explicitly provide credentials and call those exports
- Works fully offline except for the optional calendar/Notion integrations

---

## License

MIT — see [LICENSE](LICENSE) for details.
