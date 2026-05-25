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
    class NewAssessmentInput(BaseModel):
        name: str
        type: AssessmentType = AssessmentType.exam
        scheduled_date: date | None = None
        weight_percent: float | None = None

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
    remove_assessments: list[str] = Field(
        default_factory=list,
        description="Assessment names to remove (case-insensitive exact-name match).",
    )
    add_assessments: list[NewAssessmentInput] = Field(
        default_factory=list,
        description="Add or update assessments by name (manual exam/date correction flow).",
    )


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
        if any("Week-based schedule detected" in c for c in course.constraints_found):
            warnings.append("Syllabus appears week-based without concrete dates; use apply_course_corrections.assessment_date_overrides.")
    else:
        text = inp.content.strip()
        pages = [TextPage(page_number=1, text=text)]
        course = extract_course_model_from_pages(pages, timezone=inp.timezone)
        if not course.topics:
            warnings.append("No topics detected from text; consider pasting the weekly schedule section.")
        if any("Week-based schedule detected" in c for c in course.constraints_found):
            warnings.append("Syllabus appears week-based without concrete dates; use apply_course_corrections.assessment_date_overrides.")

    return ParseSyllabusOutput(course=course, warnings=warnings)


@mcp.tool
def detect_exam_dates(course: CourseModel) -> DetectExamDatesOutput:
    """Refine assessments and exam dates with confidence and assumptions."""
    warnings: list[str] = []
    blockers = ("assignment must", "blackboard", "attendance", "office hours")
    exams = []
    for a in course.assessments:
        name_low = a.name.lower()
        if any(b in name_low for b in blockers):
            continue
        if a.type == AssessmentType.exam or any(k in name_low for k in ("midterm", "final", "exam", "test")):
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

    if inp.add_assessments:
        existing_by_name = {a.name.strip().lower(): a for a in course.assessments}
        added = 0
        updated = 0
        for item in inp.add_assessments:
            key = item.name.strip().lower()
            if not key:
                continue
            if key in existing_by_name:
                a = existing_by_name[key]
                a.type = item.type
                if item.scheduled_date is not None:
                    a.scheduled_date = item.scheduled_date
                if item.weight_percent is not None:
                    a.weight_percent = item.weight_percent
                a.confidence = Confidence(value=0.95, reason="User-added assessment details")
                updated += 1
                continue

            course.assessments.append(
                Assessment(
                    name=item.name.strip(),
                    type=item.type,
                    scheduled_date=item.scheduled_date,
                    weight_percent=item.weight_percent,
                    confidence=Confidence(value=0.98, reason="User-added assessment"),
                    source={"page": None, "line": "manual_add_assessment"},
                )
            )
            existing_by_name[key] = course.assessments[-1]
            added += 1

        if added:
            changes.append(f"assessments_added={added}")
        if updated:
            changes.append(f"assessments_updated={updated}")

    remove_assessment_set = {a.strip().lower() for a in inp.remove_assessments if a.strip()}
    if remove_assessment_set:
        before = len(course.assessments)
        course.assessments = [
            a for a in course.assessments if a.name.strip().lower() not in remove_assessment_set
        ]
        removed = before - len(course.assessments)
        if removed:
            changes.append(f"assessments_removed={removed}")
        else:
            warnings.append("No assessment names matched remove_assessments.")

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

    Includes: exam countdown, weekly session summary, priority topics,
    first sessions preview, and actionable adjustment tips.
    """
    course = inp.course
    plan = inp.plan
    today = date.today()
    md = inp.include_markdown

    exams = [a for a in course.assessments if a.type == AssessmentType.exam]
    dated_exams = sorted([a for a in exams if a.scheduled_date], key=lambda x: x.scheduled_date)
    total_hours = round(sum(s.estimated_minutes for s in plan.sessions) / 60, 1)
    total_days = (plan.end_date - plan.start_date).days + 1
    learn_count = sum(1 for s in plan.sessions if s.session_type.value == "learn")
    review_count = sum(1 for s in plan.sessions if s.session_type.value == "review")

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    title = course.course_title or "Your Course"
    if md:
        lines += [f"# Study Plan — {title}", ""]

    # ── Snapshot ──────────────────────────────────────────────────────────────
    if md:
        lines += ["## At a Glance", ""]
    lines += [
        f"- Course: {title}",
        f"- Study window: {plan.start_date.isoformat()} → {plan.end_date.isoformat()} ({total_days} days)",
        f"- Total sessions: {len(plan.sessions)}  ({learn_count} learn · {review_count} review)",
        f"- Estimated total study time: {total_hours} hours",
        f"- Topics in plan: {len(course.topics)}",
        f"- Assessments tracked: {len(course.assessments)}",
    ]

    # ── Exam Countdown ────────────────────────────────────────────────────────
    if md:
        lines += ["", "## Exam Countdown", ""]
    else:
        lines.append("")
    if dated_exams:
        for a in dated_exams:
            days_left = (a.scheduled_date - today).days
            if days_left < 0:
                tag = "(past)"
            elif days_left == 0:
                tag = "TODAY"
            elif days_left == 1:
                tag = "tomorrow"
            else:
                tag = f"{days_left} days away"
            lines.append(f"- {a.name}: {a.scheduled_date.isoformat()}  [{tag}]")
    else:
        lines.append(
            "- No exam dates detected yet. "
            "Use `apply_course_corrections` or `full_pipeline.manual_exam_dates` to add them."
        )

    # ── Weekly Summary ────────────────────────────────────────────────────────
    if md:
        lines += ["", "## Weekly Study Summary", ""]
    else:
        lines.append("")

    from collections import defaultdict
    week_map: dict[str, int] = defaultdict(int)
    for s in plan.sessions:
        week_num = s.session_date.isocalendar()[1]
        year = s.session_date.year
        key = f"{year}-W{week_num:02d}"
        week_map[key] += s.estimated_minutes

    shown = 0
    for week_key in sorted(week_map.keys())[:6]:
        mins = week_map[week_key]
        hrs = round(mins / 60, 1)
        lines.append(f"- {week_key}: {hrs} hrs ({mins} min)")
        shown += 1
    if len(week_map) > shown:
        lines.append(f"- … and {len(week_map) - shown} more weeks")

    # ── Priority Topics ───────────────────────────────────────────────────────
    if md:
        lines += ["", "## Priority Topics (highest weight first)", ""]
    else:
        lines.append("")

    top_topics = sorted(course.topics, key=lambda t: t.weight_score or 1.0, reverse=True)[:8]
    if top_topics:
        for t in top_topics:
            score = t.weight_score or 1.0
            bar = "█" * min(int(score), 5) + "░" * max(0, 5 - int(score))
            lines.append(f"- {t.title}  [{bar}] {score:.1f}")
    else:
        lines.append("- No topics detected. Use `apply_course_corrections.add_topics` to add them.")

    # ── First Sessions ────────────────────────────────────────────────────────
    if md:
        lines += ["", "## Your First 7 Sessions", ""]
    else:
        lines.append("")

    for s in plan.sessions[:7]:
        lines.append(
            f"- {s.session_date.isoformat()} [{s.session_type.value:8s}] "
            f"{s.topic_title} ({s.estimated_minutes} min)"
        )

    # ── How to Adjust ─────────────────────────────────────────────────────────
    if md:
        lines += ["", "## How to Adjust This Plan", ""]
    else:
        lines.append("")

    lines += [
        "- Wrong exam dates? → call `apply_course_corrections` with `assessment_date_overrides`, then `generate_study_plan`.",
        "- Missing topics?   → call `apply_course_corrections` with `add_topics`, then `weight_topics` + `generate_study_plan`.",
        "- Change study hours or days off? → call `generate_study_plan` again with updated `preferences`.",
        "- Re-sync calendar? → call `export_plan` with `format='ics'` (or `google_calendar`/`notion`) after regenerating.",
    ]

    return BuildPlanReportOutput(report="\n".join(lines))


class SetupNotionDatabaseInput(BaseModel):
    notion_token: str = Field(description="Your Notion integration token (starts with 'secret_...').")
    parent_page_id: str = Field(
        description=(
            "The Notion page ID where the database will be created. "
            "Open the page in Notion, copy the URL — the ID is the last 32-char hex after the last '/'."
        )
    )
    database_title: str = Field(default="Study Plan", description="Title for the new Notion database.")


class SetupNotionDatabaseOutput(BaseModel):
    database_id: str
    database_url: str
    message: str
    warnings: list[str] = Field(default_factory=list)


@mcp.tool
def setup_notion_database(inp: SetupNotionDatabaseInput) -> SetupNotionDatabaseOutput:
    """
    Create the required Notion database for study plan export.

    Creates a database with all required properties:
    Name, Date, Type, Minutes, Key, Rationale, PlanKey.

    Run this once, then use the returned database_id in export_plan or full_pipeline.
    """
    from notion_client import Client as NotionClient

    client = NotionClient(auth=inp.notion_token)
    warnings: list[str] = []

    properties: dict[str, Any] = {
        "Name": {"title": {}},
        "Date": {"date": {}},
        "Type": {
            "select": {
                "options": [
                    {"name": "learn", "color": "blue"},
                    {"name": "review", "color": "green"},
                    {"name": "practice", "color": "yellow"},
                    {"name": "mock_exam", "color": "red"},
                    {"name": "buffer", "color": "gray"},
                ]
            }
        },
        "Minutes": {"number": {"format": "number"}},
        "Key": {"rich_text": {}},
        "PlanKey": {"rich_text": {}},
        "Rationale": {"rich_text": {}},
    }

    try:
        db = client.databases.create(
            parent={"type": "page_id", "page_id": inp.parent_page_id},
            title=[{"type": "text", "text": {"content": inp.database_title}}],
            properties=properties,
        )
        db_id = db["id"]
        db_url = db.get("url", f"https://notion.so/{db_id.replace('-', '')}")
        return SetupNotionDatabaseOutput(
            database_id=db_id,
            database_url=db_url,
            message=(
                f"Database '{inp.database_title}' created successfully. "
                f"Use database_id='{db_id}' in export_plan or full_pipeline."
            ),
            warnings=warnings,
        )
    except Exception as exc:
        return SetupNotionDatabaseOutput(
            database_id="",
            database_url="",
            message="Failed to create database. See warnings.",
            warnings=[str(exc)],
        )


class FullPipelineInput(BaseModel):
    content_type: Literal["pdf_base64", "text"] = Field(
        description="Provide either base64-encoded PDF bytes or plain text."
    )
    content: str = Field(description="Base64 PDF bytes or syllabus text.")
    timezone: str = Field(default="UTC", description="Your timezone, e.g. 'Asia/Kolkata'.")
    hours_per_day: float = Field(default=1.5, description="Study hours available per day.")
    days_off: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(
        default_factory=list,
        description="Days you cannot study, e.g. ['fri', 'sat'].",
    )
    course_start_date: date | None = Field(
        default=None,
        description="When to start studying. Defaults to today.",
    )
    manual_exam_dates: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Override or add exam dates. Key = exam name, value = date string 'YYYY-MM-DD'. "
            "Use this when the syllabus has no explicit dates (e.g. week-based schedules)."
        ),
    )
    boost_keywords: list[str] = Field(
        default_factory=list,
        description="Extra keywords to boost topic importance (e.g. ['networking', 'security']).",
    )
    export_format: Literal["ics", "json"] = Field(
        default="ics",
        description="Output format: 'ics' (importable calendar) or 'json' (raw data).",
    )


class FullPipelineOutput(BaseModel):
    course_title: str | None
    topics_found: int
    assessments_found: int
    sessions_total: int
    plan_start: str
    plan_end: str
    report: str
    export_format: str
    export_data: Any
    warnings: list[str] = Field(default_factory=list)


@mcp.tool
def full_pipeline(inp: FullPipelineInput) -> FullPipelineOutput:
    """
    One-call end-to-end pipeline: upload a syllabus and get a complete study plan.

    Runs: parse → detect exam dates → apply manual corrections → weight topics →
    generate day-by-day schedule → build readable report → export ICS or JSON.

    Use manual_exam_dates to provide real dates when the syllabus is week-based
    (no explicit calendar dates). Example: {"Final Exam": "2026-09-10"}.
    """
    warnings: list[str] = []

    # 1) Parse
    parse_out = parse_syllabus(ParseSyllabusInput(
        content_type=inp.content_type,
        content=inp.content,
        timezone=inp.timezone,
    ))
    warnings.extend(parse_out.warnings)

    # 2) Detect exam dates
    detect_out = detect_exam_dates(parse_out.course)
    warnings.extend(detect_out.warnings)

    # 3) Apply manual exam date overrides / additions (if provided)
    course = detect_out.course
    if inp.manual_exam_dates:
        parsed_overrides: dict[str, date] = {}
        new_assessments: list[CourseCorrectionInput.NewAssessmentInput] = []
        existing_names = {a.name.strip().lower() for a in course.assessments}
        for name, raw_date in inp.manual_exam_dates.items():
            try:
                from dateutil import parser as dp
                d = dp.parse(raw_date).date()
            except Exception:
                warnings.append(f"Could not parse date '{raw_date}' for '{name}'; skipped.")
                continue
            if name.strip().lower() in existing_names:
                parsed_overrides[name] = d
            else:
                new_assessments.append(
                    CourseCorrectionInput.NewAssessmentInput(name=name, type=AssessmentType.exam, scheduled_date=d)
                )
        corr_out = apply_course_corrections(CourseCorrectionInput(
            course=course,
            assessment_date_overrides=parsed_overrides,
            add_assessments=new_assessments,
        ))
        warnings.extend(corr_out.warnings)
        course = corr_out.course

    # 4) Weight topics
    weight_out = weight_topics(WeightTopicsInput(course=course, boost_keywords=inp.boost_keywords))
    course = weight_out.course

    # 5) Generate plan
    prefs = StudyPreferences(
        course_start_date=inp.course_start_date,
        timezone=inp.timezone,
        hours_per_day=inp.hours_per_day,
        days_off=inp.days_off,
    )
    plan_out = generate_study_plan(GenerateStudyPlanInput(course=course, preferences=prefs))
    warnings.extend(plan_out.warnings)
    plan = plan_out.plan
    plan.meta["generated_at"] = datetime.now(timezone.utc).isoformat()

    # 6) Build report
    report_out = build_plan_report(BuildPlanReportInput(course=course, plan=plan, include_markdown=True))

    # 7) Export
    export_out = export_plan(ExportPlanInput(plan=plan, format=inp.export_format, target={}))
    warnings.extend(export_out.warnings)

    return FullPipelineOutput(
        course_title=course.course_title,
        topics_found=len(course.topics),
        assessments_found=len(course.assessments),
        sessions_total=len(plan.sessions),
        plan_start=plan.start_date.isoformat(),
        plan_end=plan.end_date.isoformat(),
        report=report_out.report,
        export_format=export_out.format,
        export_data=export_out.result,
        warnings=warnings,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

