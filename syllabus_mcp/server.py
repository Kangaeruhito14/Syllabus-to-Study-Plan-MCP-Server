from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from syllabus_mcp.models import Assessment, AssessmentType, Confidence, CourseModel, StudyPlan, StudyPreferences, Topic
from syllabus_mcp.ocr import pdf_bytes_to_text_pages
from syllabus_mcp.extract import TextPage, extract_course_model_from_pages, extract_text_from_pdf_bytes
from syllabus_mcp.planner import generate_plan, weight_topics as weight_course_topics
from syllabus_mcp.exporters import plan_to_ics, push_plan_to_notion
from syllabus_mcp.gcal import push_plan_to_google_calendar


class ParseSyllabusInput(BaseModel):
    content_type: Literal["pdf_base64", "text"] = Field(
        description="Provide either base64-encoded PDF bytes or plain text."
    )
    content: str = Field(description="Base64 PDF bytes or syllabus text.")
    timezone: str | None = Field(default=None, description="Optional timezone hint.")


class ParseSyllabusOutput(BaseModel):
    course: CourseModel
    warnings: list[str] = Field(default_factory=list)


class DetectExamDatesOutput(BaseModel):
    course: CourseModel
    warnings: list[str] = Field(default_factory=list)


class WeightTopicsInput(BaseModel):
    course: CourseModel
    boost_keywords: list[str] = Field(
        default_factory=list,
        description="Optional custom keywords to treat as importance cues.",
    )


class WeightTopicsOutput(BaseModel):
    course: CourseModel
    warnings: list[str] = Field(default_factory=list)


class GenerateStudyPlanInput(BaseModel):
    course: CourseModel
    preferences: StudyPreferences = Field(default_factory=StudyPreferences)


class GenerateStudyPlanOutput(BaseModel):
    plan: StudyPlan
    warnings: list[str] = Field(default_factory=list)


class ExportPlanInput(BaseModel):
    plan: StudyPlan
    format: Literal["json", "ics", "google_calendar", "notion"]
    target: dict[str, Any] = Field(
        default_factory=dict,
        description="Format-specific options. For integrations, include identifiers and auth hints.",
    )


class ExportPlanOutput(BaseModel):
    format: str
    result: Any
    warnings: list[str] = Field(default_factory=list)


class CourseCorrectionInput(BaseModel):
    course: CourseModel
    set_course_title: str | None = None
    set_timezone: str | None = None
    set_end_date: date | None = None
    assessment_date_overrides: dict[str, date] = Field(
        default_factory=dict,
        description="Map assessment name -> corrected date.",
    )
    add_topics: list[str] = Field(default_factory=list)
    remove_topics: list[str] = Field(default_factory=list)


class CourseCorrectionOutput(BaseModel):
    course: CourseModel
    changes_applied: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BuildPlanReportInput(BaseModel):
    course: CourseModel
    plan: StudyPlan
    include_markdown: bool = True


class BuildPlanReportOutput(BaseModel):
    report: str


mcp = FastMCP(
    name="Syllabus-to-Study-Plan",
    instructions=(
        "Tools to parse a syllabus (PDF/text), detect exams, weight topics, "
        "generate a spaced-repetition study schedule, and export/push to ICS, "
        "Google Calendar, or Notion."
    ),
)


def _decode_pdf_base64(b64: str) -> bytes:
    return base64.b64decode(b64.encode("utf-8"))


@mcp.tool
def parse_syllabus(inp: ParseSyllabusInput) -> ParseSyllabusOutput:
    """
    Parse a syllabus provided as base64 PDF bytes (scanned/text) or as plain text.

    Returns a normalized CourseModel with topics and assessments, including confidence fields.
    """
    warnings: list[str] = []

    if inp.content_type == "pdf_base64":
        pdf_bytes = _decode_pdf_base64(inp.content)
        # Try native text extraction first; if it's empty/too sparse, fall back to OCR.
        pages = extract_text_from_pdf_bytes(pdf_bytes)
        total_chars = sum(len(p.text.strip()) for p in pages)
        if total_chars < 300:
            warnings.append("PDF text extraction sparse; using OCR fallback.")
            ocr_pages = pdf_bytes_to_text_pages(pdf_bytes)
            pages = [TextPage(page_number=p.page_number, text=p.text) for p in ocr_pages]
        course = extract_course_model_from_pages(pages, timezone=inp.timezone)
        if not course.topics:
            warnings.append("No topics detected; provide topic list manually or ensure syllabus has weekly outline.")
        if not course.assessments:
            warnings.append("No assessments detected; you may need to provide exam dates manually.")
    else:
        text = inp.content.strip()
        pages = [TextPage(page_number=1, text=text)]
        course = extract_course_model_from_pages(pages, timezone=inp.timezone)
        if not course.topics:
            warnings.append("No topics detected from text; consider pasting the weekly schedule section.")

    return ParseSyllabusOutput(course=course, warnings=warnings)


@mcp.tool
def detect_exam_dates(course: CourseModel) -> DetectExamDatesOutput:
    """Refine assessments and exam dates with confidence and assumptions."""
    warnings: list[str] = []
    exams = []
    for a in course.assessments:
        if a.type == AssessmentType.exam or any(k in a.name.lower() for k in ("midterm", "final", "exam", "test")):
            if a.scheduled_date is None:
                warnings.append(f"Missing date for likely exam: '{a.name}'.")
            exams.append(a)

    if exams and any(e.scheduled_date for e in exams):
        course.end_date = max([e.scheduled_date for e in exams if e.scheduled_date])
        course.confidences["end_date"] = Confidence(value=0.55, reason="Derived from detected exam assessments")
    elif course.end_date is None:
        warnings.append("No exam dates detected. Provide overrides via apply_course_corrections.")

    return DetectExamDatesOutput(course=course, warnings=warnings)


@mcp.tool
def weight_topics(inp: WeightTopicsInput) -> WeightTopicsOutput:
    """Assign weight scores to topics with rationale."""
    course = weight_course_topics(inp.course, boost_keywords=inp.boost_keywords)
    return WeightTopicsOutput(course=course, warnings=[])


@mcp.tool
def generate_study_plan(inp: GenerateStudyPlanInput) -> GenerateStudyPlanOutput:
    """Generate a day-by-day schedule with spaced repetition based on preferences."""
    plan = generate_plan(inp.course, inp.preferences)
    plan.meta["generated_at"] = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    if not inp.course.topics:
        warnings.append("No topics found; plan will contain practice/buffer only.")
    if not any(a.scheduled_date for a in inp.course.assessments) and not inp.course.end_date:
        warnings.append("No exam/end date detected; plan uses a 30-day default window.")
    return GenerateStudyPlanOutput(plan=plan, warnings=warnings)


@mcp.tool
def export_plan(inp: ExportPlanInput) -> ExportPlanOutput:
    """Export a plan to JSON/ICS or push to Google Calendar/Notion."""
    if inp.format == "json":
        return ExportPlanOutput(format="json", result=inp.plan.model_dump(), warnings=[])

    if inp.format == "ics":
        ics_text = plan_to_ics(inp.plan)
        return ExportPlanOutput(format="ics", result={"ics": ics_text}, warnings=[])

    if inp.format == "notion":
        token = inp.target.get("notion_token")
        database_id = inp.target.get("database_id")
        if not token or not database_id:
            return ExportPlanOutput(
                format="notion",
                result={"status": "missing_credentials"},
                warnings=["Provide target.notion_token and target.database_id."],
            )
        res = push_plan_to_notion(
            inp.plan,
            notion_token=token,
            database_id=database_id,
            prune_stale=bool(inp.target.get("prune_stale", True)),
        )
        return ExportPlanOutput(format="notion", result=res.__dict__, warnings=[])

    if inp.format == "google_calendar":
        access_token = inp.target.get("access_token")
        if not access_token:
            return ExportPlanOutput(
                format="google_calendar",
                result={"status": "missing_credentials"},
                warnings=["Provide target.access_token (and optionally refresh_token, client_id, client_secret)."],
            )
        res = push_plan_to_google_calendar(
            inp.plan,
            access_token=access_token,
            refresh_token=inp.target.get("refresh_token"),
            client_id=inp.target.get("client_id"),
            client_secret=inp.target.get("client_secret"),
            calendar_id=inp.target.get("calendar_id", "primary"),
            prune_stale=bool(inp.target.get("prune_stale", True)),
        )
        return ExportPlanOutput(format="google_calendar", result=res.__dict__, warnings=[])

    return ExportPlanOutput(format=inp.format, result={"status": "unknown_format"}, warnings=[])


@mcp.tool
def apply_course_corrections(inp: CourseCorrectionInput) -> CourseCorrectionOutput:
    """
    Apply user-specified corrections (title, dates, topics) to a parsed course model.
    """
    course = inp.course.model_copy(deep=True)
    changes: list[str] = []
    warnings: list[str] = []

    if inp.set_course_title:
        course.course_title = inp.set_course_title.strip()
        changes.append(f"course_title='{course.course_title}'")
    if inp.set_timezone:
        course.timezone = inp.set_timezone.strip()
        changes.append(f"timezone='{course.timezone}'")
    if inp.set_end_date:
        course.end_date = inp.set_end_date
        changes.append(f"end_date='{inp.set_end_date.isoformat()}'")

    if inp.assessment_date_overrides:
        lowered = {k.strip().lower(): v for k, v in inp.assessment_date_overrides.items()}
        matched = 0
        for a in course.assessments:
            key = a.name.strip().lower()
            if key in lowered:
                a.scheduled_date = lowered[key]
                if a.confidence:
                    a.confidence = Confidence(value=0.95, reason="User-corrected date")
                matched += 1
        if matched == 0:
            warnings.append("No assessment names matched assessment_date_overrides.")
        else:
            changes.append(f"assessment_dates_updated={matched}")

    remove_set = {t.strip().lower() for t in inp.remove_topics if t.strip()}
    if remove_set:
        before = len(course.topics)
        course.topics = [t for t in course.topics if t.title.strip().lower() not in remove_set]
        removed = before - len(course.topics)
        changes.append(f"topics_removed={removed}")

    existing = {t.title.strip().lower() for t in course.topics}
    added = 0
    for raw in inp.add_topics:
        title = raw.strip()
        if not title:
            continue
        if title.lower() in existing:
            continue
        course.topics.append(Topic(title=title))
        existing.add(title.lower())
        added += 1
    if added:
        changes.append(f"topics_added={added}")

    dated = [a.scheduled_date for a in course.assessments if a.scheduled_date]
    if dated:
        course.end_date = max(dated)

    return CourseCorrectionOutput(course=course, changes_applied=changes, warnings=warnings)


@mcp.tool
def build_plan_report(inp: BuildPlanReportInput) -> BuildPlanReportOutput:
    """
    Build a polished natural-language report for users.
    """
    course = inp.course
    plan = inp.plan
    exams = [a for a in course.assessments if a.type == AssessmentType.exam]
    dated_exams = [a for a in exams if a.scheduled_date]
    topics = course.topics[:8]
    first_sessions = plan.sessions[:6]
    total_hours = round(sum(s.estimated_minutes for s in plan.sessions) / 60, 1)

    lines = []
    if inp.include_markdown:
        lines.append(f"# Study Plan for {course.course_title or 'Your Course'}")
        lines.append("")
        lines.append("## Snapshot")
    lines.extend(
        [
            f"- Timeline: {plan.start_date.isoformat()} to {plan.end_date.isoformat()} ({len(plan.sessions)} sessions)",
            f"- Estimated workload: {total_hours} hours total",
            f"- Topics detected: {len(course.topics)}",
            f"- Assessments detected: {len(course.assessments)}",
        ]
    )
    if inp.include_markdown:
        lines.append("")
        lines.append("## Key Exams")
    if dated_exams:
        for a in sorted(dated_exams, key=lambda x: x.scheduled_date):
            lines.append(f"- {a.name}: {a.scheduled_date.isoformat()}")
    else:
        lines.append("- No exam dates confidently detected yet. Add corrections for best schedule quality.")

    if inp.include_markdown:
        lines.append("")
        lines.append("## Priority Topics")
    for t in sorted(topics, key=lambda x: x.weight_score or 1.0, reverse=True):
        lines.append(f"- {t.title} (weight: {t.weight_score or 1.0})")

    if inp.include_markdown:
        lines.append("")
        lines.append("## First Sessions")
    for s in first_sessions:
        lines.append(
            f"- {s.session_date.isoformat()}: [{s.session_type.value}] {s.topic_title} ({s.estimated_minutes} min)"
        )

    if inp.include_markdown:
        lines.append("")
        lines.append("## How to Adjust")
    lines.extend(
        [
            "- If exam dates change, use `apply_course_corrections.assessment_date_overrides` and regenerate the plan.",
            "- If topics are missing/noisy, use `add_topics` and `remove_topics` then rerun `weight_topics` and `generate_study_plan`.",
        ]
    )
    return BuildPlanReportOutput(report="\n".join(lines))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

