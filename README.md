# Syllabus-to-Study-Plan MCP Server

[![CI](https://github.com/Kangaeruhito14/Syllabus-to-Study-Plan-MCP-Server/actions/workflows/ci.yml/badge.svg)](https://github.com/Kangaeruhito14/Syllabus-to-Study-Plan-MCP-Server/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP%20stdio-green.svg)](https://modelcontextprotocol.io)

> **Drop a syllabus PDF. Get a complete, personalised day-by-day study plan — with spaced repetition, exam countdowns, and one-click sync to Google Calendar or Notion.**

Works inside **Cursor, VS Code, Claude Desktop, Windsurf**, and any MCP-compatible AI editor.  
No paid API keys required. Runs entirely on your machine.

---

## What it does

1. **Reads any syllabus** — PDF (text or scanned), or plain-text paste
2. **Understands the structure** — handles 4 common formats automatically
3. **Builds a realistic schedule** — spaced repetition, buffer days, configurable hours/days-off
4. **Gives you a polished report** — exam countdown, weekly hours, priority topics
5. **Syncs where you work** — exports ICS calendar, or pushes directly to Google Calendar / Notion

---

## Supported syllabus formats

| Format | Example |
|---|---|
| Week/Module prefix | `Week 1: Introduction to Python` |
| Date-column table | `Jan 13   SQL Basics   Ch. 1` |
| Course Objectives bullets | `● Nouns  ● Pronouns  ● Verbs` |
| Numbered schedule list | `1. Variables  2. Loops  3. Functions` |
| Scanned PDF | OCR fallback via Tesseract |

If extraction misses something, `apply_course_corrections` lets you fix it in one call. When it's unclear, `get_raw_text` returns the full PDF text so you (or the AI) can read it directly and correct it — no API cost.

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
| **Cursor** | Open folder → Settings → Tools & MCP → `syllabus-to-study-plan` appears automatically |
| **VS Code** | `.vscode/mcp.json` included — open folder and the extension picks it up |
| **Claude Desktop** | See [docs/client-setup.md](docs/client-setup.md) |
| **Windsurf** | See [docs/client-setup.md](docs/client-setup.md) |

### 3. Use it

Ask your AI:

```
Call full_pipeline with:
- content_type: "pdf_base64"
- content: <paste your syllabus.b64>
- timezone: "Asia/Kolkata"
- manual_exam_dates: {"Final Exam": "2026-09-10"}
- hours_per_day: 1.5
- days_off: ["fri"]
- export_format: "ics"
```

That's it. You get a full study plan, a readable report, and an ICS file to import into any calendar.

---

## Tools reference

The server exposes **10 tools** over MCP stdio.

### One-call tool (recommended starting point)

| Tool | What it does |
|---|---|
| `full_pipeline` | PDF/text → complete plan → report → ICS/JSON in a single call. Accepts `manual_exam_dates` for week-based syllabi. |

### Step-by-step tools (for full control)

| Tool | Input → Output |
|---|---|
| `get_raw_text` | PDF/text → full extracted text + syllabus confidence score. Use this when `parse_syllabus` misses something — read the text yourself and fix with `apply_course_corrections`. |
| `parse_syllabus` | PDF/text → `CourseModel` (title, topics, assessments, confidence scores, constraints) |
| `detect_exam_dates` | `CourseModel` → refined assessments with confidence and missing-date warnings |
| `apply_course_corrections` | `CourseModel` + fixes → corrected `CourseModel`. Fix title, add/remove topics, add/update/remove assessments, set exam dates. |
| `weight_topics` | `CourseModel` → topics with importance scores and rationale |
| `generate_study_plan` | `CourseModel` + preferences → day-by-day `StudyPlan` with spaced repetition |
| `build_plan_report` | `CourseModel` + `StudyPlan` → polished Markdown report with exam countdown, weekly hours, priority topics, first sessions |
| `export_plan` | `StudyPlan` → `ics` / `json` / `google_calendar` / `notion` |
| `setup_notion_database` | Notion token + page ID → auto-creates the required Notion database with all columns |

### Typical step-by-step flow

```
parse_syllabus
    ↓
detect_exam_dates
    ↓
apply_course_corrections   ← fix anything wrong or missing
    ↓
weight_topics
    ↓
generate_study_plan
    ↓
build_plan_report          ← readable summary
    ↓
export_plan                ← ics / google_calendar / notion
```

---

## Study plan features

- **Spaced repetition**: every new topic gets follow-up review sessions at +1d, +3d, +7d, +14d, +28d intervals (compressed when exam is close)
- **Buffer days**: built-in catch-up sessions every 8 study days (configurable by intensity)
- **Days-off support**: specify days you cannot study — no sessions placed on those days
- **Intensity presets**: `light` / `standard` / `intense` — adjusts buffer cadence
- **Exam-driven window**: plan end date is driven by your earliest exam date
- **Week-based syllabi**: provide `manual_exam_dates` and the plan adapts automatically

---

## Export options

| Format | What you get | Credentials needed |
|---|---|---|
| `ics` | `.ics` file — import into Google Calendar, Apple Calendar, Outlook, any calendar app | None |
| `json` | Raw structured data (all sessions, dates, topics, metadata) | None |
| `google_calendar` | Push sessions directly to your Google Calendar (idempotent — re-sync is safe) | OAuth access token |
| `notion` | Push sessions to a Notion database (idempotent — re-sync never duplicates) | Notion integration token + database ID |

---

## Google Calendar setup

**What you need to provide:**
- `client_id` and `client_secret` — from Google Cloud Console (free)
- `access_token` — short-lived (1 hour), generated once via OAuth
- `refresh_token` — long-lived, lets the server renew the access token automatically

**Step-by-step to get these:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project (or use existing)
2. **APIs & Services → Library** → search **Google Calendar API** → **Enable**
3. **APIs & Services → Credentials** → **Create Credentials → OAuth client ID**
4. Choose **Desktop app** → give it a name → **Create** → **Download JSON**
5. Run this script once (inside your `.venv`):

```python
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",   # the file you downloaded
    scopes=["https://www.googleapis.com/auth/calendar.events"],
)
creds = flow.run_local_server(port=0)

print("access_token: ", creds.token)
print("refresh_token:", creds.refresh_token)
print("client_id:    ", creds.client_id)
print("client_secret:", creds.client_secret)
```

6. Provide all four values when calling `export_plan` with `format: "google_calendar"`.

See [docs/integrations.md](docs/integrations.md) for the full payload example.

---

## Notion setup

**What you need to provide:**
- `notion_token` — your Notion integration secret (starts with `secret_...`)
- `database_id` — created automatically by the `setup_notion_database` tool, or manually

**Step-by-step:**

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Name it (e.g. "Study Plan"), select your workspace → **Submit**
3. Copy the **Internal Integration Token** (`secret_...`) — this is your `notion_token`
4. Open any Notion page where you want the database → copy the page ID from the URL (last 32 characters)
5. Call the `setup_notion_database` tool — it creates all required columns automatically and returns the `database_id`
6. Open the new database in Notion → **... → Connections** → connect your integration
7. Use `notion_token` + `database_id` in `export_plan` with `format: "notion"`.

See [docs/integrations.md](docs/integrations.md) for the full payload example.

---

## Running tests

```bash
pytest tests/ -v
```

51 tests across extraction logic, planner, and all 10 server tools.

```
tests/test_extract.py        — PDF/text extraction, 4 format types, non-syllabus detection
tests/test_planner.py        — weight_topics, schedule generation, spaced repetition
tests/test_server_tools.py   — all 10 MCP tools end-to-end
```

---

## Local smoke test (no MCP client needed)

```bash
./.venv/bin/python scripts/test_local.py
```

Parses a sample syllabus, generates a plan, prints an ICS preview. Runs in ~1 second.

---

## Privacy

- Processes syllabus data **in-memory only** — nothing is stored to disk by default
- No data is sent to any third party (except Google Calendar / Notion when you explicitly provide credentials)
- No external API calls — works fully offline except for the optional calendar/Notion integrations

---

## Project structure

```
syllabus_mcp/
  server.py      — FastMCP server, all 10 tool definitions
  extract.py     — PDF/text → CourseModel (4 extraction strategies + non-syllabus detection)
  planner.py     — schedule generation with spaced repetition
  exporters.py   — ICS generation + Notion push (idempotent)
  gcal.py        — Google Calendar push (idempotent)
  ocr.py         — OCR fallback for scanned PDFs (Tesseract)
  models.py      — Pydantic data models (CourseModel, StudyPlan, etc.)

tests/
  test_extract.py        — extraction unit tests
  test_planner.py        — planner unit tests
  test_server_tools.py   — integration tests for all tools

docs/
  client-setup.md   — setup guide for Cursor, VS Code, Claude Desktop, Windsurf
  demo.md           — usage examples and walkthrough
  integrations.md   — Google Calendar + Notion credential setup
  marketplace.md    — MCPize marketplace listing
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
