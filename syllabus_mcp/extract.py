from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

from dateutil import parser as dateparser
from pypdf import PdfReader

from syllabus_mcp.models import Assessment, AssessmentType, Confidence, CourseModel, Topic


@dataclass(frozen=True)
class TextPage:
    page_number: int
    text: str


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> list[TextPage]:
    # pypdf expects a file-like object; wrap raw bytes.
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[TextPage] = []
    for i, p in enumerate(reader.pages, start=1):
        t = p.extract_text() or ""
        pages.append(TextPage(page_number=i, text=t))
    return pages


_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\w+\s+\d{1,2}(?:,\s*\d{4})?)\b",
    flags=re.IGNORECASE,
)

_ASSESSMENT_KEYWORDS = ["midterm", "final", "exam", "quiz", "project", "assignment", "test"]
_TOPIC_BLOCKERS = {
    "attendance",
    "policy",
    "policies",
    "grading",
    "blackboard",
    "office hours",
    "accommodations",
    "integrity",
    "disability",
    "withdraw",
}


def _safe_parse_date(s: str) -> date | None:
    try:
        dt = dateparser.parse(s, fuzzy=True)
        return dt.date() if dt else None
    except Exception:
        return None


def _line_is_noise(raw: str) -> bool:
    low = raw.lower().strip()
    if not low or len(low) < 3:
        return True
    if low in {".", "-", "--"}:
        return True
    if any(k in low for k in _TOPIC_BLOCKERS):
        return True
    if len(raw) > 220:
        return True
    return False


def _likely_assessment_line(raw: str) -> bool:
    low = raw.lower()
    if not any(k in low for k in _ASSESSMENT_KEYWORDS):
        return False
    if len(raw.split()) > 20 and _DATE_RE.search(raw) is None:
        return False
    if ":" not in raw and _DATE_RE.search(raw) is None and len(raw.split()) > 12:
        return False
    return True


def _best_inline_or_neighbor_date(lines: list[str], idx: int) -> date | None:
    # try same line, then one line before/after for common syllabus layouts
    for probe in (idx, idx + 1, idx - 1):
        if probe < 0 or probe >= len(lines):
            continue
        m = _DATE_RE.search(lines[probe])
        if m:
            parsed = _safe_parse_date(m.group(0))
            if parsed:
                return parsed
    return None


def _guess_assessment_type(name: str) -> AssessmentType:
    n = name.lower()
    if "midterm" in n or "final" in n or "exam" in n:
        return AssessmentType.exam
    if "quiz" in n:
        return AssessmentType.quiz
    if "project" in n:
        return AssessmentType.project
    if "assignment" in n or "hw" in n or "homework" in n:
        return AssessmentType.assignment
    if "presentation" in n:
        return AssessmentType.presentation
    return AssessmentType.other


def extract_course_model_from_pages(
    pages: list[TextPage], *, timezone: str | None = None
) -> CourseModel:
    """
    Lightweight syllabus extraction.

    MVP heuristic approach:
    - detect assessments by keywords + inline dates
    - detect topics from Week/Module/Lecture style lines or short enumerations
    """
    full_text = "\n".join(p.text for p in pages).strip()

    course = CourseModel(timezone=timezone)
    course.extracted_text_summary = full_text[:800] if full_text else None

    # Course title heuristic: first non-empty line of first page.
    if pages:
        first_lines = [ln.strip() for ln in pages[0].text.splitlines() if ln.strip()]
        if first_lines:
            course.course_title = first_lines[0][:120]
            course.confidences["course_title"] = Confidence(
                value=0.35, reason="First line of page 1"
            )

    # Assessment extraction: scan for common keywords, associate an inline date if present.
    assessment_lines: list[tuple[int, str]] = []
    for page in pages:
        lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
        for ln in lines:
            low = ln.lower()
            if _line_is_noise(ln):
                continue
            if _likely_assessment_line(ln):
                stripped = ln.strip()
                if stripped:
                    assessment_lines.append((page.page_number, stripped))

    assessments: list[Assessment] = []
    seen: set[tuple[int, str]] = set()
    for page_number, ln in assessment_lines:
        key = (page_number, ln.lower())
        if key in seen:
            continue
        seen.add(key)

        page_lines = [x.strip() for x in pages[page_number - 1].text.splitlines() if x.strip()]
        try:
            line_idx = page_lines.index(ln)
        except ValueError:
            line_idx = -1
        dt = _best_inline_or_neighbor_date(page_lines, line_idx) if line_idx >= 0 else None
        name = re.sub(_DATE_RE, "", ln).strip(" -–—:\t")
        name = name or ln[:80]
        if _line_is_noise(name):
            continue

        assessments.append(
            Assessment(
                name=name[:120],
                type=_guess_assessment_type(name),
                scheduled_date=dt,
                confidence=Confidence(
                    value=0.55 if dt else 0.25,
                    reason="Keyword match" + (" + inline date" if dt else " (no date parsed)"),
                ),
                source={"page": page_number, "line": ln},
            )
        )

    course.assessments = assessments

    # Topic extraction
    topics: list[Topic] = []
    topic_re = re.compile(
        r"^(week|module|lecture|unit)\s*(\d{1,2})?\b[:\-–—\s]*(.+)$", re.IGNORECASE
    )
    enum_re = re.compile(r"^\s*(\d{1,2})[\.)]\s+(.+)$")

    for page in pages:
        for ln in page.text.splitlines():
            raw = ln.strip()
            if _line_is_noise(raw):
                continue
            m1 = topic_re.match(raw)
            if m1:
                week_num = int(m1.group(2)) if m1.group(2) else None
                title = m1.group(3).strip()
                if title and not _line_is_noise(title):
                    topics.append(
                        Topic(
                            title=title[:160],
                            week=week_num,
                            module=m1.group(1).lower(),
                            cues=[],
                            source={"page": page.page_number, "line": raw},
                        )
                    )
                continue

            m2 = enum_re.match(raw)
            if m2 and len(raw) < 180:
                title = m2.group(2).strip()
                if title and not _line_is_noise(title):
                    topics.append(
                        Topic(
                            title=title[:160],
                            cues=[],
                            source={"page": page.page_number, "line": raw},
                        )
                    )

    uniq: dict[str, Topic] = {}
    for t in topics:
        k = t.title.strip().lower()
        if k and k not in uniq:
            uniq[k] = t
    course.topics = list(uniq.values())

    dated = [a.scheduled_date for a in course.assessments if a.scheduled_date]
    if dated:
        course.end_date = max(dated)
        course.confidences["end_date"] = Confidence(
            value=0.4, reason="Latest detected assessment date"
        )

    return course

