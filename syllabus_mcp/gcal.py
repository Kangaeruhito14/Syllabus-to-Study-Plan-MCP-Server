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


def _build_event(s: StudySession, start_dt: datetime, timezone: str) -> dict[str, Any]:
    end_dt = start_dt + timedelta(minutes=int(s.estimated_minutes))
    return {
        "summary": f"[{s.session_type.value}] {s.topic_title}",
        "description": "\n".join(s.rationale) if s.rationale else None,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
    }


# Priority order within a day: review first → prep → learn → practice → buffer → tutorial
_SESSION_DAY_ORDER: dict[str, int] = {
    "review": 0, "tutorial_prep": 1, "learn": 2,
    "practice": 3, "buffer": 4, "mock_exam": 5, "tutorial": 6,
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
    study_start_hour: int = 20,
    session_gap_minutes: int = 5,
    prune_stale: bool = True,
) -> GoogleCalendarPushResult:
    """
    Push plan sessions to Google Calendar using OAuth credentials.

    Idempotency: deterministic event IDs — re-running updates existing events
    and deletes stale ones. Safe to call whenever the plan changes.

    Multiple sessions on the same day are stacked in order:
    review → tutorial_prep → learn → practice, starting at study_start_hour
    (default 20 = 8 PM) with session_gap_minutes between them.

    Re-calling with updated parameters will automatically update all events
    and remove any that no longer exist in the new plan.
    """
    from collections import defaultdict as _dd

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
    tz = plan.timezone or "UTC"

    # Group sessions by date, sort within each day by priority
    sessions_by_date: dict = _dd(list)
    for s in plan.sessions:
        sessions_by_date[s.session_date].append(s)

    for day_date in sorted(sessions_by_date.keys()):
        day_sessions = sorted(
            sessions_by_date[day_date],
            key=lambda s: _SESSION_DAY_ORDER.get(s.session_type.value, 9),
        )

        # First session starts at study_start_hour; subsequent ones follow immediately
        current_hour = study_start_hour
        current_minute = 0

        for s in day_sessions:
            start_dt = datetime.combine(
                day_date, datetime.min.time()
            ).replace(hour=current_hour, minute=current_minute)

            eid = _event_id(plan, s)
            body = _build_event(s, start_dt, tz)
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

            # Advance clock: end of this session + gap
            total_mins = current_minute + s.estimated_minutes + session_gap_minutes
            current_hour += total_mins // 60
            current_minute = total_mins % 60

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

