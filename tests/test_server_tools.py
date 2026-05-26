from __future__ import annotations

from datetime import date

from syllabus_mcp.server import (
    BuildPlanReportInput,
    CourseCorrectionInput,
    ExportPlanInput,
    FullPipelineInput,
    GenerateStudyPlanInput,
    GetRawTextInput,
    ParseSyllabusInput,
    WeightTopicsInput,
    apply_course_corrections,
    build_plan_report,
    detect_exam_dates,
    export_plan,
    full_pipeline,
    generate_study_plan,
    get_raw_text,
    parse_syllabus,
    weight_topics,
)
from syllabus_mcp.models import StudyPreferences


_SIMPLE_TEXT = (
    "CS101 Introduction to Programming\n"
    "Midterm Exam: March 30, 2026\n"
    "Final Exam: May 20, 2026\n"
    "Week 1: Intro to Python\n"
    "Week 2: Data Structures\n"
    "Week 3: Algorithms\n"
    "Week 4: Testing\n"
)


# ── parse_syllabus ─────────────────────────────────────────────────────────────

def test_parse_syllabus_text_returns_course():
    out = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    assert out.course is not None
    assert out.course.course_title is not None


def test_parse_syllabus_topics_extracted():
    out = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    assert len(out.course.topics) >= 2


def test_parse_syllabus_assessments_extracted():
    out = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    assert len(out.course.assessments) >= 1


# ── detect_exam_dates ──────────────────────────────────────────────────────────

def test_detect_exam_dates_sets_end_date():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    detected = detect_exam_dates(parsed.course)
    assert detected.course is not None


# ── apply_course_corrections ───────────────────────────────────────────────────

def test_correction_set_title():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    out = apply_course_corrections(CourseCorrectionInput(
        course=parsed.course,
        set_course_title="CUSTOM TITLE",
    ))
    assert out.course.course_title == "CUSTOM TITLE"
    assert any("course_title" in c for c in out.changes_applied)


def test_correction_add_and_remove_topics():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    out = apply_course_corrections(CourseCorrectionInput(
        course=parsed.course,
        add_topics=["Brand New Topic"],
        remove_topics=["Testing"],
    ))
    titles = [t.title for t in out.course.topics]
    assert "Brand New Topic" in titles
    assert "Testing" not in titles


def test_correction_add_assessments():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    before_count = len(parsed.course.assessments)
    out = apply_course_corrections(CourseCorrectionInput(
        course=parsed.course,
        add_assessments=[
            CourseCorrectionInput.NewAssessmentInput(
                name="Pop Quiz",
                type="quiz",
                scheduled_date=date(2026, 3, 10),
            )
        ],
    ))
    assert len(out.course.assessments) >= before_count
    names = [a.name for a in out.course.assessments]
    assert "Pop Quiz" in names


def test_correction_remove_assessments():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    # Add one first so we know the name
    added = apply_course_corrections(CourseCorrectionInput(
        course=parsed.course,
        add_assessments=[
            CourseCorrectionInput.NewAssessmentInput(name="Quiz To Remove", scheduled_date=date(2026, 3, 5))
        ],
    ))
    removed = apply_course_corrections(CourseCorrectionInput(
        course=added.course,
        remove_assessments=["Quiz To Remove"],
    ))
    names = [a.name for a in removed.course.assessments]
    assert "Quiz To Remove" not in names


def test_correction_end_date_auto_updated_from_assessments():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    out = apply_course_corrections(CourseCorrectionInput(
        course=parsed.course,
        add_assessments=[
            CourseCorrectionInput.NewAssessmentInput(
                name="Final",
                type="exam",
                scheduled_date=date(2026, 9, 1),
            )
        ],
    ))
    assert out.course.end_date is not None
    assert out.course.end_date >= date(2026, 9, 1)


# ── weight_topics ──────────────────────────────────────────────────────────────

def test_weight_topics_tool_returns_scores():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    out = weight_topics(WeightTopicsInput(course=parsed.course, boost_keywords=[]))
    for t in out.course.topics:
        assert t.weight_score is not None


# ── generate_study_plan ────────────────────────────────────────────────────────

def test_generate_plan_returns_sessions():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(
        course=weighted.course,
        preferences=StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC"),
    ))
    assert len(plan_out.plan.sessions) > 0


# ── build_plan_report ──────────────────────────────────────────────────────────

def test_build_plan_report_returns_text():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(
        course=weighted.course,
        preferences=StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC"),
    ))
    report = build_plan_report(BuildPlanReportInput(
        course=weighted.course,
        plan=plan_out.plan,
        include_markdown=True,
    ))
    assert len(report.report) > 50
    assert "Study Plan" in report.report or "Timeline" in report.report


# ── export_plan ────────────────────────────────────────────────────────────────

def test_export_plan_ics_returns_ics_string():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(
        course=weighted.course,
        preferences=StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC"),
    ))
    ics_out = export_plan(ExportPlanInput(plan=plan_out.plan, format="ics", target={}))
    assert ics_out.format == "ics"
    assert "BEGIN:VCALENDAR" in ics_out.result["ics"]
    assert "END:VCALENDAR" in ics_out.result["ics"]


def test_export_plan_json_returns_dict():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(
        course=weighted.course,
        preferences=StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC"),
    ))
    json_out = export_plan(ExportPlanInput(plan=plan_out.plan, format="json", target={}))
    assert json_out.format == "json"
    assert "sessions" in json_out.result


def test_export_plan_notion_missing_creds_returns_warning():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(course=weighted.course))
    out = export_plan(ExportPlanInput(plan=plan_out.plan, format="notion", target={}))
    assert out.result["status"] == "missing_credentials"
    assert len(out.warnings) > 0


# ── full_pipeline ──────────────────────────────────────────────────────────────

# ── get_raw_text ───────────────────────────────────────────────────────────────

def test_get_raw_text_returns_content():
    out = get_raw_text(GetRawTextInput(content_type="text", content=_SIMPLE_TEXT))
    assert len(out.raw_text) > 0
    assert out.char_count > 0
    assert out.is_likely_syllabus is True
    assert out.syllabus_confidence >= 0.4


def test_get_raw_text_detects_non_syllabus():
    recipe = "Chicken Tikka Masala. Ingredients: chicken, yogurt, spices. Cook and serve."
    out = get_raw_text(GetRawTextInput(content_type="text", content=recipe))
    assert out.is_likely_syllabus is False
    assert len(out.warnings) > 0


def test_parse_syllabus_warns_on_non_syllabus():
    recipe = "Chicken Tikka Masala. Ingredients: chicken, yogurt, spices. Cook and serve."
    out = parse_syllabus(ParseSyllabusInput(content_type="text", content=recipe, timezone="UTC"))
    assert any("not appear to be a syllabus" in w or "WARNING" in w for w in out.warnings)


def test_parse_syllabus_table_format():
    table_syllabus = (
        "CSCI 3400 - Database Management Systems\n"
        "COURSE SCHEDULE:\n"
        "Jan 13   Introduction to Databases   Ch. 1\n"
        "Jan 20   Relational Model   Ch. 2\n"
        "Feb 17   MIDTERM EXAM\n"
        "Apr 21   FINAL EXAM\n"
    )
    out = parse_syllabus(ParseSyllabusInput(content_type="text", content=table_syllabus, timezone="UTC"))
    assert "3400" in (out.course.course_title or "") or "Database" in (out.course.course_title or "")
    assert len(out.course.topics) >= 2
    dated_exams = [a for a in out.course.assessments if a.scheduled_date]
    assert len(dated_exams) >= 1


def test_full_pipeline_text_produces_plan():
    out = full_pipeline(FullPipelineInput(
        content_type="text",
        content=_SIMPLE_TEXT,
        timezone="UTC",
        hours_per_day=1.5,
        course_start_date=date(2026, 3, 1),
        export_format="ics",
    ))
    assert out.sessions_total > 0
    assert out.topics_found >= 2
    assert out.export_format == "ics"
    assert "BEGIN:VCALENDAR" in out.export_data["ics"]
    assert len(out.report) > 50


def test_full_pipeline_manual_exam_dates_applied():
    week_based = (
        "BIO 101\n"
        "Week 1: Cell Biology\n"
        "Week 2: Genetics\n"
        "Week 3: Evolution\n"
        "Midterm Exam\n"
        "Week 4: Ecology\n"
    )
    out = full_pipeline(FullPipelineInput(
        content_type="text",
        content=week_based,
        timezone="UTC",
        course_start_date=date(2026, 3, 1),
        manual_exam_dates={"Final Exam": "2026-06-15"},
        export_format="ics",
    ))
    assert out.sessions_total > 0
    # Plan end should be on or near the manual exam date
    assert out.plan_end <= "2026-06-15"


def test_full_pipeline_json_export():
    out = full_pipeline(FullPipelineInput(
        content_type="text",
        content=_SIMPLE_TEXT,
        timezone="UTC",
        course_start_date=date(2026, 3, 1),
        export_format="json",
    ))
    assert out.export_format == "json"
    assert "sessions" in out.export_data


def test_export_plan_gcal_missing_creds_returns_warning():
    parsed = parse_syllabus(ParseSyllabusInput(content_type="text", content=_SIMPLE_TEXT, timezone="UTC"))
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(GenerateStudyPlanInput(course=weighted.course))
    out = export_plan(ExportPlanInput(plan=plan_out.plan, format="google_calendar", target={}))
    assert out.result["status"] == "missing_credentials"
    assert len(out.warnings) > 0
