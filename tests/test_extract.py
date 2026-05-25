from __future__ import annotations

from syllabus_mcp.extract import TextPage, extract_course_model_from_pages


def _pages(text: str) -> list[TextPage]:
    return [TextPage(page_number=1, text=text)]


# ── title detection ────────────────────────────────────────────────────────────

def test_title_from_course_code():
    pages = _pages("CSC-1200 Orientation to IT\nInstructor: Prof. Smith\nWeek 1: Intro")
    course = extract_course_model_from_pages(pages)
    assert course.course_title is not None
    assert "CSC" in course.course_title or "1200" in course.course_title


def test_title_falls_back_to_first_line():
    pages = _pages("Introduction to Python\nWeek 1: Variables\nWeek 2: Loops")
    course = extract_course_model_from_pages(pages)
    assert course.course_title is not None
    assert len(course.course_title) > 0


# ── topic extraction ───────────────────────────────────────────────────────────

def test_week_style_topics_extracted():
    text = (
        "CS101\n"
        "Week 1: Introduction to Python\n"
        "Week 2: Data Structures\n"
        "Week 3: Algorithms\n"
        "Week 4: Testing\n"
    )
    course = extract_course_model_from_pages(_pages(text))
    titles = [t.title for t in course.topics]
    assert any("Introduction" in t or "Python" in t for t in titles)
    assert any("Data" in t or "Structures" in t for t in titles)


def test_module_style_topics_extracted():
    text = (
        "Module 1: Networking Basics\n"
        "Module 2: Routing Protocols\n"
        "Module 3: Security Fundamentals\n"
    )
    course = extract_course_model_from_pages(_pages(text))
    assert len(course.topics) >= 2


def test_policy_lines_not_extracted_as_topics():
    text = (
        "CS200\n"
        "Week 1: Variables\n"
        "Attendance policy: students must attend all classes.\n"
        "Grading: 40% midterm, 60% final.\n"
        "Office hours: Mon 2-4pm.\n"
        "Week 2: Functions\n"
    )
    course = extract_course_model_from_pages(_pages(text))
    titles = [t.title.lower() for t in course.topics]
    assert not any("attendance" in t or "grading" in t or "office" in t for t in titles)


# ── assessment extraction ──────────────────────────────────────────────────────

def test_exam_with_inline_date_parsed():
    text = "CS101\nMidterm Exam: March 30, 2026\nFinal Exam: May 20, 2026\nWeek 1: Intro\n"
    course = extract_course_model_from_pages(_pages(text))
    names = [a.name.lower() for a in course.assessments]
    assert any("midterm" in n for n in names)
    assert any("final" in n for n in names)


def test_exam_dates_populated():
    text = "CS101\nMidterm Exam: March 30, 2026\nFinal Exam: May 20, 2026\n"
    course = extract_course_model_from_pages(_pages(text))
    dated = [a for a in course.assessments if a.scheduled_date is not None]
    assert len(dated) >= 1


def test_policy_lines_not_extracted_as_assessments():
    text = (
        "CSE 101\n"
        "Week 1: Intro\n"
        "Assignments must be submitted via Blackboard by midnight.\n"
        "Attendance is required for all sessions.\n"
        "Final Exam: April 15, 2026\n"
    )
    course = extract_course_model_from_pages(_pages(text))
    names = [a.name.lower() for a in course.assessments]
    assert not any("blackboard" in n or "attendance" in n for n in names)


# ── week-based detection ───────────────────────────────────────────────────────

def test_week_based_constraint_detected():
    text = (
        "BIO 101\n"
        "Weeks 1-3: Cell Biology\n"
        "Weeks 4-6: Genetics\n"
        "Weeks 7-9: Evolution\n"
        "Midterm Exam\n"
        "Weeks 10-12: Ecology\n"
    )
    course = extract_course_model_from_pages(_pages(text))
    assert any("Week-based" in c for c in course.constraints_found)


# ── end_date derivation ────────────────────────────────────────────────────────

def test_end_date_derived_from_latest_exam():
    text = "CS101\nMidterm Exam: March 10, 2026\nFinal Exam: May 5, 2026\n"
    course = extract_course_model_from_pages(_pages(text))
    if course.end_date:
        assert course.end_date.year == 2026
        assert course.end_date.month >= 3


def test_no_year_1990_dates():
    text = "CS101\nFinal Exam: May 20\nWeek 1: Intro\n"
    course = extract_course_model_from_pages(_pages(text), timezone="UTC")
    for a in course.assessments:
        if a.scheduled_date:
            assert a.scheduled_date.year >= 2000
