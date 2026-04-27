from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from notion_client import Client as NotionClient

from syllabus_mcp.models import StudyPlan, StudySession


def _ics_escape(text: str) -> str:
    # RFC5545 escaping for TEXT values
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _ics_dt(dt: datetime) -> str:
    # UTC timestamp in basic format
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def _ics_uid(plan: StudyPlan, s: StudySession) -> str:
    base = _stable_key(plan, s)
    # keep UID safe-ish
    safe = re.sub(r"[^a-zA-Z0-9._:-]+", "-", base)[:160]
    return f"{safe}@syllabus-mcp"


def plan_to_ics(plan: StudyPlan) -> str:
    """
    Generate an RFC5545-ish ICS calendar without external dependencies.

    We emit UTC timestamps. Events are placed at 12:00 local-ish to avoid DST edge cases.
    """
    now = datetime.now(timezone.utc)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Syllabus-to-Study-Plan MCP//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(plan.course_title or 'Study Plan')}",
    ]

    for s in plan.sessions:
        start = datetime.combine(s.session_date, datetime.min.time()).replace(hour=12, tzinfo=timezone.utc)
        end = start + timedelta(minutes=int(s.estimated_minutes))
        summary = f"[{s.session_type.value}] {s.topic_title}"
        desc = "\n".join(s.rationale) if s.rationale else ""
        uid = _ics_uid(plan, s)

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_ics_escape(uid)}",
                f"DTSTAMP:{_ics_dt(now)}",
                f"DTSTART:{_ics_dt(start)}",
                f"DTEND:{_ics_dt(end)}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(desc)}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@dataclass(frozen=True)
class NotionPushResult:
    created: int
    updated: int
    database_id: str
    page_ids: list[str]


def _stable_key(plan: StudyPlan, s: StudySession) -> str:
    title = (plan.course_title or "course").strip().lower().replace(" ", "-")
    return f"{title}:{s.session_date.isoformat()}:{s.session_type.value}:{s.topic_title.strip().lower()}"


def _plan_key(plan: StudyPlan) -> str:
    title = (plan.course_title or "course").strip().lower().replace(" ", "-")
    return f"{title}:{plan.start_date.isoformat()}:{plan.end_date.isoformat()}:{plan.timezone}"


def push_plan_to_notion(
    plan: StudyPlan,
    *,
    notion_token: str,
    database_id: str,
    prune_stale: bool = True,
) -> NotionPushResult:
    """
    Idempotent-ish Notion push using a stable key stored in a 'Key' property.

    Expected Notion DB properties (create this template in docs):
    - Name (title)
    - Date (date)
    - Type (select)
    - Minutes (number)
    - Key (rich_text)
    - Rationale (rich_text) [optional]
    """
    client = NotionClient(auth=notion_token)

    created = 0
    updated = 0
    page_ids: list[str] = []
    plan_key = _plan_key(plan)
    active_keys: set[str] = set()
    supports_plan_key = True

    for s in plan.sessions:
        key = _stable_key(plan, s)
        active_keys.add(key)

        # Query existing by Key
        existing = client.databases.query(
            database_id=database_id,
            filter={
                "property": "Key",
                "rich_text": {"equals": key},
            },
            page_size=1,
        )
        props: dict[str, Any] = {
            "Name": {"title": [{"text": {"content": f"[{s.session_type.value}] {s.topic_title}"}}]},
            "Date": {"date": {"start": s.session_date.isoformat()}},
            "Type": {"select": {"name": s.session_type.value}},
            "Minutes": {"number": int(s.estimated_minutes)},
            "Key": {"rich_text": [{"text": {"content": key}}]},
        }
        if supports_plan_key:
            props["PlanKey"] = {"rich_text": [{"text": {"content": plan_key}}]}
        if s.rationale:
            props["Rationale"] = {"rich_text": [{"text": {"content": "\n".join(s.rationale)[:2000]}}]}

        if existing.get("results"):
            page_id = existing["results"][0]["id"]
            try:
                client.pages.update(page_id=page_id, properties=props)
            except Exception:
                # Backward compatible with DBs that don't yet have PlanKey property.
                supports_plan_key = False
                props.pop("PlanKey", None)
                client.pages.update(page_id=page_id, properties=props)
            updated += 1
            page_ids.append(page_id)
        else:
            try:
                page = client.pages.create(
                    parent={"database_id": database_id},
                    properties=props,
                )
            except Exception:
                supports_plan_key = False
                props.pop("PlanKey", None)
                page = client.pages.create(
                    parent={"database_id": database_id},
                    properties=props,
                )
            created += 1
            page_ids.append(page["id"])

    if prune_stale and supports_plan_key:
        # Best effort: archive pages from the same plan key that are no longer present.
        cursor: str | None = None
        while True:
            page = client.databases.query(
                database_id=database_id,
                filter={"property": "PlanKey", "rich_text": {"equals": plan_key}},
                start_cursor=cursor,
                page_size=100,
            )
            results = page.get("results", [])
            for item in results:
                props = item.get("properties", {})
                key_prop = props.get("Key", {})
                key_text = ""
                if key_prop.get("rich_text"):
                    key_text = "".join([x.get("plain_text", "") for x in key_prop["rich_text"]]).strip()
                if key_text and key_text not in active_keys:
                    client.pages.update(page_id=item["id"], archived=True)
            cursor = page.get("next_cursor")
            if not page.get("has_more"):
                break

    return NotionPushResult(
        created=created, updated=updated, database_id=database_id, page_ids=page_ids
    )

