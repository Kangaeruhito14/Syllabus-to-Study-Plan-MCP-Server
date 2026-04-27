from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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

