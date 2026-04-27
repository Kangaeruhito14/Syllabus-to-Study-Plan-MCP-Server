from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from syllabus_mcp.models import StudyPlan, StudySession


@dataclass(frozen=True)
class GoogleCalendarPushResult:
    calendar_id: str
    created: int
    updated: int
    deleted: int
    event_ids: list[str]


def _plan_key(plan: StudyPlan) -> str:
    raw = f"{plan.course_title}|{plan.start_date.isoformat()}|{plan.end_date.isoformat()}|{plan.timezone}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _session_key(s: StudySession) -> str:
    raw = f"{s.session_date.isoformat()}|{s.session_type.value}|{s.topic_title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _event_id(plan: StudyPlan, s: StudySession) -> str:
    # Google Calendar eventId requirements: 5-1024 chars, allowed [a-v0-9]
    raw = f"{_plan_key(plan)}|{_session_key(s)}"
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()  # 40 hex chars
    return f"stp{h}"


def _build_event(s: StudySession, timezone: str) -> dict[str, Any]:
    # Use timed events to represent study blocks
    start_dt = datetime.combine(s.session_date, datetime.min.time()).replace(hour=12)
    minutes = int(s.estimated_minutes)
    end_dt = start_dt + timedelta(minutes=minutes)
    return {
        "summary": f"[{s.session_type.value}] {s.topic_title}",
        "description": "\n".join(s.rationale) if s.rationale else None,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone,
        },
    }


def push_plan_to_google_calendar(
    plan: StudyPlan,
    *,
    access_token: str,
    refresh_token: str | None = None,
    token_uri: str = "https://oauth2.googleapis.com/token",
    client_id: str | None = None,
    client_secret: str | None = None,
    calendar_id: str = "primary",
    prune_stale: bool = True,
) -> GoogleCalendarPushResult:
    """
    Push plan sessions to Google Calendar using OAuth credentials.

    Idempotency is achieved via deterministic event IDs.

    MVP auth model:
    - caller provides access_token (and optionally refresh_token+client_id+client_secret)
    - server does not run an interactive OAuth browser flow (keeps MCP tool non-interactive)
    """
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )
    service = build("calendar", "v3", credentials=creds)

    created = 0
    updated = 0
    deleted = 0
    event_ids: list[str] = []
    plan_key = _plan_key(plan)

    for s in plan.sessions:
        eid = _event_id(plan, s)
        body = _build_event(s, plan.timezone)
        body["id"] = eid
        body["extendedProperties"] = {
            "private": {
                "syllabus_plan_key": plan_key,
                "syllabus_session_key": _session_key(s),
            }
        }

        try:
            service.events().get(calendarId=calendar_id, eventId=eid).execute()
            service.events().update(calendarId=calendar_id, eventId=eid, body=body).execute()
            updated += 1
        except Exception:
            service.events().insert(calendarId=calendar_id, body=body).execute()
            created += 1

        event_ids.append(eid)

    if prune_stale:
        seen = set(event_ids)
        page_token: str | None = None
        while True:
            resp = service.events().list(
                calendarId=calendar_id,
                privateExtendedProperty=f"syllabus_plan_key={plan_key}",
                maxResults=250,
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                eid = item.get("id")
                if eid and eid not in seen:
                    service.events().delete(calendarId=calendar_id, eventId=eid).execute()
                    deleted += 1
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    return GoogleCalendarPushResult(
        calendar_id=calendar_id, created=created, updated=updated, deleted=deleted, event_ids=event_ids
    )

