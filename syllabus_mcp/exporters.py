from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests as _requests

from syllabus_mcp.models import StudyPlan, StudySession

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


_NOTION_TIMEOUT = 60  # seconds — Notion API can be slow under load


def _notion_query_db(token: str, database_id: str, body: dict) -> dict:
    resp = _requests.post(
        f"{_NOTION_BASE}/databases/{database_id}/query",
        headers=_notion_headers(token),
        json=body,
        timeout=_NOTION_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _notion_create_page(token: str, payload: dict) -> dict:
    resp = _requests.post(
        f"{_NOTION_BASE}/pages",
        headers=_notion_headers(token),
        json=payload,
        timeout=_NOTION_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _notion_update_page(token: str, page_id: str, properties: dict) -> dict:
    resp = _requests.patch(
        f"{_NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(token),
        json={"properties": properties},
        timeout=_NOTION_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _notion_archive_page(token: str, page_id: str) -> None:
    _requests.patch(
        f"{_NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(token),
        json={"archived": True},
        timeout=_NOTION_TIMEOUT,
    )


def _notion_request_with_retry(fn, *args, max_retries: int = 6, **kwargs):
    """Call a Notion API function with exponential back-off on rate-limit, server, and timeout errors."""
    import time as _time
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except _requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (429, 500, 502, 503) and attempt < max_retries - 1:
                _time.sleep(delay)
                delay = min(delay * 2, 16)
                continue
            raise
        except (_requests.exceptions.ReadTimeout, _requests.exceptions.ConnectionError):
            if attempt < max_retries - 1:
                _time.sleep(delay)
                delay = min(delay * 2, 16)
                continue
            raise


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _ics_dt(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def _ics_uid(plan: StudyPlan, s: StudySession) -> str:
    base = _stable_key(plan, s)
    safe = re.sub(r"[^a-zA-Z0-9._:-]+", "-", base)[:160]
    return f"{safe}@syllabus-mcp"


# Priority order within a day (matches gcal.py)
_ICS_SESSION_ORDER: dict[str, int] = {
    "review": 0, "tutorial_prep": 1, "learn": 2,
    "practice": 3, "buffer": 4, "mock_exam": 5, "tutorial": 6,
}


def plan_to_ics(plan: StudyPlan, *, study_start_hour: int = 20, session_gap_minutes: int = 5) -> str:
    """
    Export plan to iCalendar format.

    Multiple sessions on the same day are stacked starting at study_start_hour
    (default 20 = 8 PM), review-first, with session_gap_minutes between them.
    """
    from collections import defaultdict as _dd

    now = datetime.now(timezone.utc)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Syllabus-to-Study-Plan MCP//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(plan.course_title or 'Study Plan')}",
    ]

    sessions_by_date: dict = _dd(list)
    for s in plan.sessions:
        sessions_by_date[s.session_date].append(s)

    for day_date in sorted(sessions_by_date.keys()):
        day_sessions = sorted(
            sessions_by_date[day_date],
            key=lambda s: _ICS_SESSION_ORDER.get(s.session_type.value, 9),
        )

        current_hour = study_start_hour
        current_minute = 0

        for s in day_sessions:
            day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
            offset_mins = current_hour * 60 + current_minute
            start = day_start + timedelta(minutes=offset_mins)
            end = start + timedelta(minutes=int(s.estimated_minutes))
            summary = f"[{s.session_type.value}] {s.topic_title}"
            desc = "\n".join(s.rationale) if s.rationale else ""
            uid = _ics_uid(plan, s)

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{_ics_escape(uid)}",
                f"DTSTAMP:{_ics_dt(now)}",
                f"DTSTART:{_ics_dt(start)}",
                f"DTEND:{_ics_dt(end)}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(desc)}",
                "END:VEVENT",
            ])

            total_mins = current_minute + s.estimated_minutes + session_gap_minutes
            current_hour += total_mins // 60
            current_minute = total_mins % 60

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@dataclass(frozen=True)
class NotionPushResult:
    created: int
    updated: int
    database_id: str
    page_ids: list[str]


@dataclass(frozen=True)
class DailyNotionPushResult:
    created: int
    updated: int
    database_id: str
    page_ids: list[str]
    days_total: int


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
    created = 0
    updated = 0
    page_ids: list[str] = []
    plan_key = _plan_key(plan)
    active_keys: set[str] = set()
    supports_plan_key = True

    import time as _time

    for s in plan.sessions:
        key = _stable_key(plan, s)
        active_keys.add(key)

        existing = _notion_request_with_retry(
            _notion_query_db, notion_token, database_id,
            {"filter": {"property": "Key", "rich_text": {"equals": key}}, "page_size": 1},
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
                _notion_request_with_retry(_notion_update_page, notion_token, page_id, props)
            except Exception:
                supports_plan_key = False
                props.pop("PlanKey", None)
                _notion_request_with_retry(_notion_update_page, notion_token, page_id, props)
            updated += 1
            page_ids.append(page_id)
        else:
            payload: dict[str, Any] = {
                "parent": {"database_id": database_id},
                "properties": props,
            }
            try:
                page = _notion_request_with_retry(_notion_create_page, notion_token, payload)
            except Exception:
                supports_plan_key = False
                props.pop("PlanKey", None)
                payload["properties"] = props
                page = _notion_request_with_retry(_notion_create_page, notion_token, payload)
            created += 1
            page_ids.append(page["id"])

        _time.sleep(0.35)  # stay within Notion's ~3 req/s rate limit

    if prune_stale and supports_plan_key:
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "PlanKey", "rich_text": {"equals": plan_key}},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            page_resp = _notion_query_db(notion_token, database_id, body)
            for item in page_resp.get("results", []):
                key_prop = item.get("properties", {}).get("Key", {})
                key_text = "".join(
                    x.get("plain_text", "") for x in key_prop.get("rich_text", [])
                ).strip()
                if key_text and key_text not in active_keys:
                    _notion_archive_page(notion_token, item["id"])
            cursor = page_resp.get("next_cursor")
            if not page_resp.get("has_more"):
                break

    return NotionPushResult(
        created=created, updated=updated, database_id=database_id, page_ids=page_ids
    )


def _day_key(plan: StudyPlan, d: "date") -> str:
    title = (plan.course_title or "course").strip().lower().replace(" ", "-")
    return f"daily:{title}:{d.isoformat()}"


def push_daily_plan_to_notion(
    plan: StudyPlan,
    *,
    notion_token: str,
    database_id: str,
    prune_stale: bool = True,
) -> DailyNotionPushResult:
    """
    Push the study plan to Notion as a daily calendar — one page per day.

    Each page: Name (date + weekday) | Date | Day | Topics | Details | Total Minutes | Done
    """
    from collections import defaultdict
    from datetime import date as _date

    sessions_by_date: dict[_date, list[StudySession]] = defaultdict(list)
    for s in plan.sessions:
        sessions_by_date[s.session_date].append(s)

    import time as _time

    created = 0
    updated = 0
    page_ids: list[str] = []
    active_keys: set[str] = set()
    plan_key = _plan_key(plan)

    for day_date in sorted(sessions_by_date.keys()):
        day_sessions = sessions_by_date[day_date]
        key = _day_key(plan, day_date)
        active_keys.add(key)

        # "Monday, 02 Jun 2026"
        day_label = day_date.strftime("%A, %d %b %Y")

        # Deduplicated topic titles in session order
        seen_titles: set[str] = set()
        topics_list: list[str] = []
        for s in day_sessions:
            if s.topic_title not in seen_titles:
                topics_list.append(s.topic_title)
                seen_titles.add(s.topic_title)
        topics_text = "\n".join(topics_list)

        # One line per session: "[learn] Topic — 60 min"
        details_lines = [
            f"[{s.session_type.value}] {s.topic_title} — {s.estimated_minutes} min"
            for s in day_sessions
        ]
        details_text = "\n".join(details_lines)

        total_minutes = sum(s.estimated_minutes for s in day_sessions)
        name = f"{day_date.isoformat()} — {day_date.strftime('%A')}"

        props: dict = {
            "Name": {"title": [{"text": {"content": name}}]},
            "Date": {"date": {"start": day_date.isoformat()}},
            "Day": {"rich_text": [{"text": {"content": day_label}}]},
            "Topics": {"rich_text": [{"text": {"content": topics_text[:2000]}}]},
            "Details": {"rich_text": [{"text": {"content": details_text[:2000]}}]},
            "Total Minutes": {"number": total_minutes},
            "Done": {"checkbox": False},
            "Key": {"rich_text": [{"text": {"content": key}}]},
            "PlanKey": {"rich_text": [{"text": {"content": plan_key}}]},
        }

        existing = _notion_request_with_retry(
            _notion_query_db, notion_token, database_id,
            {"filter": {"property": "Key", "rich_text": {"equals": key}}, "page_size": 1},
        )

        if existing.get("results"):
            page_id = existing["results"][0]["id"]
            _notion_request_with_retry(_notion_update_page, notion_token, page_id, props)
            updated += 1
            page_ids.append(page_id)
        else:
            payload: dict = {"parent": {"database_id": database_id}, "properties": props}
            page = _notion_request_with_retry(_notion_create_page, notion_token, payload)
            created += 1
            page_ids.append(page["id"])

        _time.sleep(0.35)  # stay within Notion's ~3 req/s rate limit

    if prune_stale:
        cursor: str | None = None
        while True:
            body: dict = {
                "filter": {"property": "PlanKey", "rich_text": {"equals": plan_key}},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            page_resp = _notion_query_db(notion_token, database_id, body)
            for item in page_resp.get("results", []):
                key_prop = item.get("properties", {}).get("Key", {})
                key_text = "".join(
                    x.get("plain_text", "") for x in key_prop.get("rich_text", [])
                ).strip()
                if key_text and key_text not in active_keys:
                    _notion_archive_page(notion_token, item["id"])
            cursor = page_resp.get("next_cursor")
            if not page_resp.get("has_more"):
                break

    return DailyNotionPushResult(
        created=created,
        updated=updated,
        database_id=database_id,
        page_ids=page_ids,
        days_total=len(sessions_by_date),
    )
