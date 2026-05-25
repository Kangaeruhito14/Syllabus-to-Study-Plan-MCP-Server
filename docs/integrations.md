# Integration Setup Guide

## Google Calendar

### What you need
An `access_token` (and optionally `refresh_token` + `client_id` + `client_secret` for auto-refresh).

### Step-by-step: get an access token (one-time setup)

**Step 1 — Create a Google Cloud project**
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. In the left menu: **APIs & Services → Library**
4. Search for **Google Calendar API** → click **Enable**

**Step 2 — Create OAuth credentials**
1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app** (simplest for personal use)
4. Give it a name, click **Create**
5. Download the JSON file — it contains your `client_id` and `client_secret`

**Step 3 — Get your access token (run once locally)**

Install the Google auth library if not already installed:
```bash
pip install google-auth-oauthlib
```

Then run this small script once to get your tokens:
```python
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",   # the file you downloaded in Step 2
    scopes=SCOPES,
)
creds = flow.run_local_server(port=0)

print("access_token:", creds.token)
print("refresh_token:", creds.refresh_token)
print("client_id:", creds.client_id)
print("client_secret:", creds.client_secret)
```

**Step 4 — Use the token in export_plan**

```json
{
  "plan": "<your generated plan>",
  "format": "google_calendar",
  "target": {
    "access_token": "<paste access_token>",
    "refresh_token": "<paste refresh_token>",
    "client_id": "<paste client_id>",
    "client_secret": "<paste client_secret>",
    "calendar_id": "primary",
    "prune_stale": true
  }
}
```

`calendar_id: "primary"` uses your main calendar. To use a different calendar, paste the calendar ID from Google Calendar settings.

### Notes
- `access_token` expires after ~1 hour. Providing `refresh_token` + `client_id` + `client_secret` lets the server refresh it automatically.
- `prune_stale: true` removes old plan events when you re-sync after changes.

---

## Notion

### What you need
1. A Notion integration token
2. A Notion database ID (or create one with the `setup_notion_database` tool)

### Step-by-step

**Step 1 — Create a Notion integration**
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Name it (e.g. "Study Plan MCP"), select your workspace, click **Submit**
4. Copy the **Internal Integration Token** (starts with `secret_...`)

**Step 2 — Create the study plan database (recommended: use the tool)**

Call the MCP tool `setup_notion_database`:
```json
{
  "notion_token": "secret_...",
  "parent_page_id": "<ID of any Notion page you want the DB inside>",
  "database_title": "My Study Plan"
}
```

The tool creates all required columns automatically and returns a `database_id`.

> **How to find a page ID:** Open the page in Notion → copy the URL.
> The ID is the last part after the final `/` (32 hex characters, e.g. `a1b2c3d4e5f6...`).

**Step 3 — Share the database with your integration**
1. Open the newly created database in Notion
2. Click **...** (top right) → **Connections** → Add your integration

**Step 4 — Use in export_plan**

```json
{
  "plan": "<your generated plan>",
  "format": "notion",
  "target": {
    "notion_token": "secret_...",
    "database_id": "<database_id from setup_notion_database>",
    "prune_stale": true
  }
}
```

### Required database columns
If you prefer to create the database manually, it must have these exact property names:

| Property | Type    |
|----------|---------|
| Name     | Title   |
| Date     | Date    |
| Type     | Select  |
| Minutes  | Number  |
| Key      | Text    |
| PlanKey  | Text    |
| Rationale| Text    |

`setup_notion_database` creates all of these automatically.

### Notes
- `prune_stale: true` archives old sessions when you re-sync after regenerating the plan.
- The `Key` and `PlanKey` columns are used for idempotency — re-syncing the same plan never creates duplicates.
