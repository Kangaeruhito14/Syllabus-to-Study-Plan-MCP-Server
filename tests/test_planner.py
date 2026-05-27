from __future__ import annotations

from datetime import date

from syllabus_mcp.models import Assessment, AssessmentType, Confidence, CourseModel, StudyPreferences, Topic
from syllabus_mcp.planner import generate_plan, weight_topics


def _simple_course(*, with_dates: bool = True) -> CourseModel:
    course = CourseModel(course_title="Test Course", timezone="UTC")
    course.topics = [
        Topic(title="Variables"),
        Topic(title="Loops"),
        Topic(title="Functions"),
        Topic(title="Classes"),
    ]
    if with_dates:
        course.assessments = [
            Assessment(
                name="Midterm Exam",
                type=AssessmentType.exam,
                scheduled_date=date(2026, 4, 15),
                confidence=Confidence(value=0.9, reason="test"),
            ),
            Assessment(
                name="Final Exam",
                type=AssessmentType.exam,
                scheduled_date=date(2026, 5, 20),
                confidence=Confidence(value=0.9, reason="test"),
            ),
        ]
    return course


# ── weight_topics ──────────────────────────────────────────────────────────────

def test_weight_topics_assigns_scores():
    course = _simple_course()
    course = weight_topics(course)
    for t in course.topics:
        assert t.weight_score is not None
        assert t.weight_score >= 1.0


def test_weight_topics_base_score_is_one():
    course = CourseModel(course_title="X")
    course.topics = [Topic(title="Random Topic")]
    course = weight_topics(course)
    assert course.topics[0].weight_score == 1.0


def test_weight_topics_boost_keywords_raise_score():
    course = CourseModel(course_title="X")
    course.topics = [Topic(title="Security Fundamentals")]
    course = weight_topics(course, boost_keywords=["security"])
    assert course.topics[0].weight_score is not None
    assert course.topics[0].weight_score > 1.0


# ── generate_plan ──────────────────────────────────────────────────────────────

def test_plan_start_before_end():
    course = _simple_course()
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    assert plan.start_date <= plan.end_date


def test_plan_has_sessions():
    course = _simple_course()
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    assert len(plan.sessions) > 0


def test_plan_no_sessions_on_days_off():
    course = _simple_course()
    prefs = StudyPreferences(
        course_start_date=date(2026, 3, 1),
        timezone="UTC",
        days_off=["sat", "sun"],
    )
    plan = generate_plan(course, prefs)
    off_days = {"sat", "sun"}
    dow_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for s in plan.sessions:
        dow = dow_map[s.session_date.weekday()]
        assert dow not in off_days, f"Session found on day-off: {s.session_date} ({dow})"


def test_plan_without_exam_dates_uses_30day_window():
    course = _simple_course(with_dates=False)
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    delta = (plan.end_date - plan.start_date).days
    assert delta == 30


def test_plan_end_date_never_before_start():
    course = CourseModel(course_title="Bad Dates")
    course.topics = [Topic(title="Topic A")]
    # Noisy: end_date set earlier than start we'll request
    course.end_date = date(2020, 1, 1)
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    assert plan.end_date >= plan.start_date


def test_learn_sessions_match_topics():
    course = _simple_course()
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    learn_titles = {s.topic_title for s in plan.sessions if s.session_type.value == "learn"}
    topic_titles = {t.title for t in course.topics}
    assert learn_titles.issubset(topic_titles | {"Mixed practice", "Buffer / Catch-up"})


def test_spaced_repetition_review_sessions_exist():
    course = _simple_course()
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC")
    plan = generate_plan(course, prefs)
    review_sessions = [s for s in plan.sessions if s.session_type.value == "review"]
    assert len(review_sessions) > 0


def test_plan_metadata_populated():
    course = _simple_course()
    prefs = StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC", intensity="standard")
    plan = generate_plan(course, prefs)
    assert "intensity" in plan.meta
    assert "topics_count" in plan.meta
    assert plan.meta["topics_count"] == len(course.topics)
