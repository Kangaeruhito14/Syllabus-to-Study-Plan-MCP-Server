from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from syllabus_mcp.models import CourseModel, SessionType, StudyPlan, StudyPreferences, StudySession, Topic


@dataclass(frozen=True)
class WeightedTopic:
    topic: Topic
    score: float
    rationale: list[str]


DEFAULT_IMPORTANCE_CUES = [
    "midterm",
    "final",
    "exam",
    "important",
    "重点",
    "must know",
    "will be tested",
    "assessment",
]


def weight_topics(course: CourseModel, *, boost_keywords: list[str] | None = None) -> CourseModel:
    """
    Assign a weight score to each topic.

    Heuristics (MVP):
    - Base score = 1
    - +0.5 if topic appears with a week/module marker (structured outline)
    - +1 for each importance cue keyword found in topic line/source
    - +0.5 if close to an exam week (if we can infer from dates; very rough)
    """
    boost = [b.lower() for b in (boost_keywords or [])]
    cues = set(DEFAULT_IMPORTANCE_CUES + boost)

    for t in course.topics:
        score = 1.0
        rationale: list[str] = ["base=1.0"]

        if t.week is not None or t.module is not None:
            score += 0.5
            rationale.append("structured_outline:+0.5")

        hay = " ".join(
            [
                t.title or "",
                " ".join(t.cues or []),
                str((t.source or {}).get("line") or ""),
            ]
        ).lower()

        hit = [c for c in cues if c in hay]
        if hit:
            add = 1.0 * len(hit)
            score += add
            rationale.append(f"importance_cues({','.join(sorted(set(hit)))}):+{add:.1f}")

        t.weight_score = round(score, 2)
        t.weight_rationale = rationale

    return course


def _iter_study_dates(start: date, end: date, *, days_off: set[str]) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][cur.weekday()]
        if dow not in days_off:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _spaced_repetition_offsets(days_until_exam: int) -> list[int]:
    # Keep it simple; compress if exam is soon.
    if days_until_exam <= 10:
        return [1, 3, 6]
    if days_until_exam <= 25:
        return [1, 3, 7, 14]
    return [1, 3, 7, 14, 28]


def generate_plan(course: CourseModel, preferences: StudyPreferences) -> StudyPlan:
    """
    Build a day-by-day plan.

    MVP strategy:
    - Determine planning window: start_date -> (earliest exam date or course.end_date or start+30)
    - Allocate one LEARN session per day until topics exhausted (respect max sessions/day)
    - For each learn session, schedule review sessions based on SR offsets
    - Add buffer days every ~7 study days (light) or ~10 (standard) or ~14 (intense)
    """
    start = preferences.course_start_date or course.start_date or date.today()
    exam_dates = sorted([a.scheduled_date for a in course.assessments if a.scheduled_date] )
    end = (
        exam_dates[0]
        if exam_dates
        else (course.end_date or (start + timedelta(days=30)))
    )
    if end < start:
        # Guardrail for noisy extracted dates; never return an inverted plan window.
        end = start + timedelta(days=30)

    days_off = set(preferences.days_off)
    study_days = _iter_study_dates(start, end, days_off=days_off)

    # Sort topics by weight score descending (fallback 1.0).
    topics = sorted(course.topics, key=lambda t: (t.weight_score or 1.0), reverse=True)

    sessions: list[StudySession] = []

    # Buffer cadence by intensity
    buffer_every = {"light": 6, "standard": 8, "intense": 10}[preferences.intensity.value]

    topic_idx = 0
    for i, d in enumerate(study_days):
        # buffer day
        if i > 0 and i % buffer_every == 0:
            sessions.append(
                StudySession(
                    session_date=d,
                    topic_title="Buffer / Catch-up",
                    session_type=SessionType.buffer,
                    estimated_minutes=int(preferences.session_minutes / 2),
                    sr_step=None,
                    rationale=["scheduled buffer to reduce cram risk"],
                )
            )
            continue

        if topic_idx >= len(topics):
            # once done with topics, shift to practice/review days
            sessions.append(
                StudySession(
                    session_date=d,
                    topic_title="Mixed practice",
                    session_type=SessionType.practice,
                    estimated_minutes=preferences.session_minutes,
                    rationale=["no remaining new topics; practice mode"],
                )
            )
            continue

        t = topics[topic_idx]
        topic_idx += 1

        sessions.append(
            StudySession(
                session_date=d,
                topic_title=t.title,
                session_type=SessionType.learn,
                estimated_minutes=preferences.session_minutes,
                sr_step=0,
                rationale=[
                    "learn session",
                    f"topic_weight={t.weight_score or 1.0}",
                ],
            )
        )

        # Schedule reviews
        days_until_exam = max((end - d).days, 1)
        offsets = _spaced_repetition_offsets(days_until_exam)
        for step, off in enumerate(offsets, start=1):
            rd = d + timedelta(days=off)
            if rd > end:
                continue
            # Skip days off
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][rd.weekday()]
            if dow in days_off:
                continue
            sessions.append(
                StudySession(
                    session_date=rd,
                    topic_title=t.title,
                    session_type=SessionType.review,
                    estimated_minutes=max(15, int(preferences.session_minutes * 0.35)),
                    sr_step=step,
                    rationale=[f"spaced_repetition:+{off}d"],
                )
            )

    sessions_sorted = sorted(sessions, key=lambda s: (s.session_date, s.session_type.value, s.topic_title))

    return StudyPlan(
        course_title=course.course_title,
        timezone=preferences.timezone,
        start_date=start,
        end_date=end,
        sessions=sessions_sorted,
        meta={
            "days_off": sorted(days_off),
            "intensity": preferences.intensity.value,
            "buffer_every": buffer_every,
            "topics_count": len(course.topics),
            "assessments_count": len(course.assessments),
        },
    )


def generate_coverage_plan(
    course: CourseModel,
    preferences: StudyPreferences,
    *,
    study_end_date: date,
    tutorial_dates: list[dict[str, Any]] | None = None,
    next_day_review: bool = True,
    review_minutes: int = 25,
) -> StudyPlan:
    """
    Coverage mode: distribute all topics sequentially across the study window.

    Interleaved learning (next_day_review=True, default):
    - Day N:   [learn]  new topic  (session_minutes long)
    - Day N+1: [review] same topic (review_minutes, before that day's new topic)
    This means every day the student starts with a 25-min recap of yesterday,
    then moves to the new topic — matching how memory consolidation actually works.

    Tutorial-aware:
    - Tutorial days are blocked and marked as SessionType.tutorial.
    - The N study days immediately before each tutorial are marked as
      SessionType.tutorial_prep (review only that tutorial's topic).
    - Next-day reviews are not scheduled on tutorial/prep days; they fall
      on the next available free day.

    If there are more free days than topics the tail becomes revision.
    If there are more topics than free days multiple topics are packed per day.
    """
    start = preferences.course_start_date or course.start_date or date.today()
    days_off = set(preferences.days_off)
    session_mins = preferences.session_minutes

    if study_end_date <= start:
        study_end_date = start + timedelta(days=120)

    all_days = _iter_study_dates(start, study_end_date, days_off=days_off)
    all_day_set = set(all_days)

    # --- Parse and validate tutorial entries ---
    tutorial_info: list[tuple[date, str, int]] = []  # (date, topic_hint, prep_days)
    if tutorial_dates:
        for td in tutorial_dates:
            try:
                from dateutil import parser as _dp
                tdate = _dp.parse(str(td["date"])).date()
                topic_hint = str(td.get("topic_hint", "Tutorial")).strip() or "Tutorial"
                prep_days_count = max(0, int(td.get("prep_days", 3)))
                if start <= tdate <= study_end_date:
                    tutorial_info.append((tdate, topic_hint, prep_days_count))
            except Exception:
                pass  # silently skip malformed entries
    tutorial_info.sort(key=lambda x: x[0])

    # --- Mark tutorial days and prep days ---
    tutorial_day_set: set[date] = {t[0] for t in tutorial_info}
    prep_assignments: dict[date, str] = {}

    for tdate, topic_hint, prep_days_count in tutorial_info:
        count = 0
        check = tdate - timedelta(days=1)
        while count < prep_days_count and check >= start:
            dow = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][check.weekday()]
            if (dow not in days_off
                    and check in all_day_set
                    and check not in tutorial_day_set
                    and check not in prep_assignments):
                prep_assignments[check] = topic_hint
                count += 1
            check -= timedelta(days=1)

    # --- Free days = study days minus tutorial days minus prep days ---
    blocked = tutorial_day_set | set(prep_assignments.keys())
    free_days = [d for d in all_days if d not in blocked]

    # --- Topics in curriculum order (preserve extraction/insertion order) ---
    topics = list(course.topics)
    n_topics = len(topics)
    n_free = len(free_days)

    # --- Assign topics to free days with optional next-day review ---
    # Layout when next_day_review=True (e.g. 3 topics, 6 free days):
    #   free[0]: [learn] T1
    #   free[1]: [review] T1  +  [learn] T2
    #   free[2]: [review] T2  +  [learn] T3
    #   free[3]: [review] T3                   ← last review
    #   free[4]: [practice] Revision
    #   free[5]: [practice] Revision
    regular_sessions: list[StudySession] = []

    if n_free > 0 and n_topics == 0:
        for d in free_days:
            regular_sessions.append(StudySession(
                session_date=d,
                topic_title="Study / Revision",
                session_type=SessionType.practice,
                estimated_minutes=session_mins,
                rationale=["coverage: no topics found in syllabus"],
            ))

    elif n_free > 0 and n_topics <= n_free:
        for i, topic in enumerate(topics):
            # Learn session on free_days[i]
            regular_sessions.append(StudySession(
                session_date=free_days[i],
                topic_title=topic.title,
                session_type=SessionType.learn,
                estimated_minutes=session_mins,
                rationale=["coverage: learn new topic"],
            ))
            # Review session on free_days[i+1] (if available and enabled)
            if next_day_review and i + 1 < n_free:
                regular_sessions.append(StudySession(
                    session_date=free_days[i + 1],
                    topic_title=topic.title,
                    session_type=SessionType.review,
                    estimated_minutes=review_minutes,
                    rationale=["coverage: next-day review — reinforce yesterday's topic"],
                ))

        # Revision days: begin after last review slot
        revision_start = n_topics + 1 if (next_day_review and n_topics < n_free) else n_topics
        for d in free_days[revision_start:]:
            regular_sessions.append(StudySession(
                session_date=d,
                topic_title="Revision / Mixed Practice",
                session_type=SessionType.practice,
                estimated_minutes=session_mins,
                rationale=["coverage: all topics done — revision"],
            ))

    elif n_free > 0:
        # More topics than free days: distribute evenly (pack multiple per day, no next-day review)
        topic_idx = 0
        for day_idx, d in enumerate(free_days):
            remaining_topics = n_topics - topic_idx
            remaining_days = n_free - day_idx
            today_count = max(1, round(remaining_topics / remaining_days))
            day_topics = topics[topic_idx: topic_idx + today_count]
            topic_idx += today_count
            combined_title = " · ".join(t.title for t in day_topics)
            regular_sessions.append(StudySession(
                session_date=d,
                topic_title=combined_title,
                session_type=SessionType.learn,
                estimated_minutes=session_mins,
                rationale=[f"coverage: {len(day_topics)} topic(s) packed into 1 day"],
            ))

    # --- Prep day sessions ---
    prep_sessions: list[StudySession] = [
        StudySession(
            session_date=prep_date,
            topic_title=f"Tutorial Prep: {hint}",
            session_type=SessionType.tutorial_prep,
            estimated_minutes=session_mins,
            rationale=[f"pre-tutorial focused review — tutorial on {hint}"],
        )
        for prep_date, hint in prep_assignments.items()
    ]

    # --- Tutorial day sessions ---
    tutorial_sessions: list[StudySession] = [
        StudySession(
            session_date=tdate,
            topic_title=f"Tutorial: {hint}",
            session_type=SessionType.tutorial,
            estimated_minutes=session_mins,
            rationale=[f"tutorial/test day for topic: {hint}"],
        )
        for tdate, hint, _ in tutorial_info
        if tdate in all_day_set
    ]

    all_sessions = regular_sessions + prep_sessions + tutorial_sessions
    # Sort: by date, then by session type priority within the day
    _TYPE_ORDER = {
        "review": 0, "tutorial_prep": 1, "learn": 2,
        "practice": 3, "buffer": 4, "mock_exam": 5, "tutorial": 6,
    }
    all_sessions_sorted = sorted(
        all_sessions,
        key=lambda s: (s.session_date, _TYPE_ORDER.get(s.session_type.value, 9), s.topic_title),
    )

    return StudyPlan(
        course_title=course.course_title,
        timezone=preferences.timezone,
        start_date=start,
        end_date=study_end_date,
        sessions=all_sessions_sorted,
        meta={
            "mode": "coverage",
            "next_day_review": next_day_review,
            "days_off": sorted(days_off),
            "topics_count": n_topics,
            "free_days": n_free,
            "tutorial_days": len(tutorial_day_set),
            "prep_days_total": len(prep_assignments),
        },
    )

