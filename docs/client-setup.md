# Client Setup Guide

This server uses **stdio transport** — the standard MCP protocol that every major AI code editor supports.
It works **locally** on your machine. No internet, no API keys needed for the core features.

## Prerequisites (install once)

```bash
# 1. Clone or download the repo
cd "your/path/to/MCP Server"

# 2. Create virtualenv and install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Install system dependencies for OCR (needed for scanned PDFs)
# Ubuntu/Debian:
sudo apt-get install tesseract-ocr poppler-utils
# macOS:
brew install tesseract poppler
# Windows: download Tesseract installer from UB Mannheim, add to PATH
```

---

## Cursor

Config file already included at `.cursor/mcp.json`.

1. Open this folder in Cursor
2. Go to **Settings → Tools & MCP**
3. You should see `syllabus-to-study-plan` — enable it
4. Reload if needed

---

## VS Code (with GitHub Copilot or Claude extension)

Config file at `.vscode/mcp.json` is already included.

```json
{
  "mcpServers": {
    "syllabus-to-study-plan": {
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "syllabus_mcp.server"]
    }
  }
}
```

1. Open this folder in VS Code
2. The extension auto-detects `.vscode/mcp.json` — no extra configuration needed
3. Check your extension's MCP panel to confirm `syllabus-to-study-plan` appears

---

## Claude Desktop (Mac / Windows)

Edit your Claude Desktop config file:
- **Mac**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add this block (replace the path with your actual install path):

```json
{
  "mcpServers": {
    "syllabus-to-study-plan": {
      "command": "/YOUR/PATH/TO/MCP Server/.venv/bin/python",
      "args": ["-m", "syllabus_mcp.server"]
    }
  }
}
```

Windows example:
```json
{
  "mcpServers": {
    "syllabus-to-study-plan": {
      "command": "C:\\Users\\YourName\\MCP Server\\.venv\\Scripts\\python.exe",
      "args": ["-m", "syllabus_mcp.server"]
    }
  }
}
```

Restart Claude Desktop after saving.

---

## Windsurf (Codeium)

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "syllabus-to-study-plan": {
      "command": "/YOUR/PATH/TO/MCP Server/.venv/bin/python",
      "args": ["-m", "syllabus_mcp.server"]
    }
  }
}
```

Restart Windsurf after saving.

---

## Any other MCP-compatible client

All MCP clients that support **stdio transport** will work.
The config pattern is always the same:

```json
{
  "command": "/path/to/.venv/bin/python",
  "args": ["-m", "syllabus_mcp.server"]
}
```

---

## Verify it's working

After enabling in any client, ask the AI:

> "List all tools from the syllabus-to-study-plan MCP server"

You should see 10 tools:
`get_raw_text`, `parse_syllabus`, `detect_exam_dates`, `apply_course_corrections`,
`weight_topics`, `generate_study_plan`, `build_plan_report`, `export_plan`,
`setup_notion_database`, `full_pipeline`

Then run a quick test:

> "Call full_pipeline with content_type='text', content='CS101\nFinal Exam: June 10, 2026\nWeek 1: Intro\nWeek 2: Variables\nWeek 3: Functions', timezone='UTC'"

---

## Troubleshooting

**Server not showing up?**
- Make sure `.venv` exists and `pip install -e .` ran without errors
- Check the python path in the config points to `.venv/bin/python`

**OCR not working on scanned PDF?**
- Run `tesseract --version` to confirm it is installed
- On Ubuntu: `sudo apt-get install tesseract-ocr`

**`parse_syllabus` produces wrong topics?**
- Call `get_raw_text` with the same input — read the full text yourself
- Then call `apply_course_corrections` to fix title/topics/assessments manually
