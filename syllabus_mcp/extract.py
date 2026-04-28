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
_ASSESSMENT_BLOCKERS = {
    "blackboard",
    "attendance",
    "office hours",
    "contact instructor",
    "academic integrity",
    "late work",
    "must be in prior to the release",
}
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
_TOPIC_SECTION_HINTS = {
    "schedule",
    "weekly",
    "topics",
    "course outline",
    "tentative calendar",
    "course calendar",
    "module",
    "unit",
}
_TOPIC_SECTION_END_HINTS = {
    "grading",
    "attendance",
    "policies",
    "academic integrity",
    "disability",
    "office hours",
}
_MONTH_NAMES = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    "jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_EXAM_DATE_PATTERNS = [
    re.compile(
        rf"\b(?P<label>(?:midterm|final)\s*(?:exam|project|test)?|exam\s*\d+|quiz\s*\d+)\b"
        rf"[\s:,-]*(?:on\s+)?(?P<date>{_MONTH_NAMES}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<date>{_MONTH_NAMES}\s+\d{{1,2}}(?:,\s*\d{{4}})?)"
        rf"[\s:,-]*(?:-|–|—)?[\s]*(?P<label>(?:midterm|final)\s*(?:exam|project|test)?|exam|quiz)",
        flags=re.IGNORECASE,
    ),
]


def _safe_parse_date(s: str, *, default_year: int | None = None) -> date | None:
    try:
        if default_year and re.search(r"\b\d{4}\b", s) is None and re.search(r"[A-Za-z]", s):
            s = f"{s} {default_year}"
        dt = dateparser.parse(s, fuzzy=False)
        if dt and dt.year < 1990:
            return None
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
    if re.match(r"^[A-Z\s]{2,}$", raw) and len(raw.split()) <= 3:
        # all-caps banners like institution names
        return True
    if len(raw) > 220:
        return True
    return False


def _normalize_title(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip()
    s = s.replace("|", "")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_line(raw: str) -> str:
    s = raw.replace("|", " | ")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _canonical_assessment_name(raw: str) -> str:
    s = _normalize_title(raw).lower()
    s = re.sub(_DATE_RE, "", s).strip(" -–—:,\t")
    s = re.sub(r"\s+", " ", s)
    return s


def _likely_assessment_line(raw: str) -> bool:
    low = raw.lower()
    if not any(k in low for k in _ASSESSMENT_KEYWORDS):
        return False
    if any(b in low for b in _ASSESSMENT_BLOCKERS):
        return False
    has_date = _DATE_RE.search(raw) is not None
    if len(raw.split()) > 20 and not has_date:
        return False
    if ":" not in raw and not has_date and len(raw.split()) > 10:
        return False
    return True


def _best_inline_or_neighbor_date(lines: list[str], idx: int, *, default_year: int | None = None) -> date | None:
    # try same line, then one line before/after for common syllabus layouts
    for probe in (idx, idx + 1, idx - 1, idx + 2):
        if probe < 0 or probe >= len(lines):
            continue
        for m in _DATE_RE.finditer(lines[probe]):
            parsed = _safe_parse_date(m.group(0), default_year=default_year)
            if parsed:
                return parsed
    return None


def _extract_exam_from_patterns(lines: list[str], *, default_year: int | None = None) -> list[tuple[str, date]]:
    out: list[tuple[str, date]] = []
    for ln in lines:
        if _line_is_noise(ln):
            continue
        for pat in _EXAM_DATE_PATTERNS:
            m = pat.search(ln)
            if not m:
                continue
            label = _normalize_title(m.group("label"))
            dt = _safe_parse_date(m.group("date"), default_year=default_year)
            if label and dt:
                out.append((label, dt))
    return out


def _extract_exam_from_local_windows(lines: list[str], *, default_year: int | None = None) -> list[tuple[str, date]]:
    """
    Link date-like lines to nearby exam keyword lines (table/list style layouts).
    """
    out: list[tuple[str, date]] = []
    keyword_re = re.compile(r"\b(midterm|final|exam|quiz|test)\b", flags=re.IGNORECASE)

    for idx, raw in enumerate(lines):
        if _line_is_noise(raw):
            continue

        # If current line has exam keyword, try to borrow a date from nearby rows.
        if keyword_re.search(raw):
            label = _normalize_title(raw)
            dt = _best_inline_or_neighbor_date(lines, idx, default_year=default_year)
            if dt and label:
                out.append((label, dt))
            continue

        # If current line has date but no exam keyword, try nearby rows for a label.
        date_match = _DATE_RE.search(raw)
        if date_match:
            dt = _safe_parse_date(date_match.group(0), default_year=default_year)
            if not dt:
                continue
            for probe in (idx - 1, idx + 1, idx - 2, idx + 2):
                if probe < 0 or probe >= len(lines):
                    continue
                candidate = lines[probe]
                if _line_is_noise(candidate):
                    continue
                if keyword_re.search(candidate) and not any(b in candidate.lower() for b in _ASSESSMENT_BLOCKERS):
                    out.append((_normalize_title(candidate), dt))
                    break
    return out


def _extract_topics_from_schedule_lines(lines: list[str]) -> list[str]:
    topics: list[str] = []
    week_line_re = re.compile(
        rf"^\s*(?:week|wk|module|unit|lecture)?\s*\d{{1,2}}[\s:.-]+(?:{_MONTH_NAMES}\s+\d{{1,2}}(?:,\s*\d{{4}})?[\s:.-]+)?(?P<title>.+)$",
        flags=re.IGNORECASE,
    )
    for raw in lines:
        if _line_is_noise(raw):
            continue
        m = week_line_re.match(raw)
        if m:
            title = m.group("title").strip(" -:;")
            if title and not _line_is_noise(title) and len(title.split()) <= 14:
                topics.append(_normalize_title(title))
    return topics


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
    full_text = "\n".join(_normalize_line(p.text) for p in pages).strip()
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", full_text)]
    default_year = min(years) if years else None

    course = CourseModel(timezone=timezone)
    course.extracted_text_summary = full_text[:800] if full_text else None

    # Course title heuristic: first non-empty line of first page.
    if pages:
        first_lines = [_normalize_line(ln.strip()) for ln in pages[0].text.splitlines() if ln.strip()]
        if first_lines:
            title = first_lines[0]
            # Prefer an explicit course code line when present.
            for ln in first_lines[:12]:
                if re.search(r"\b[A-Z]{2,5}[-\s]?\d{3,4}\b", ln):
                    title = ln
                    break
            course.course_title = _normalize_title(title)[:120]
            course.confidences["course_title"] = Confidence(
                value=0.55 if title != first_lines[0] else 0.35,
                reason="Detected from page-1 heading"
            )

    # Assessment extraction: scan for common keywords, associate an inline date if present.
    assessment_lines: list[tuple[int, str]] = []
    for page in pages:
        lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]
        for ln in lines:
            if _line_is_noise(ln):
                continue
            if _likely_assessment_line(ln):
                stripped = ln.strip()
                if stripped:
                    assessment_lines.append((page.page_number, stripped))

    all_lines = [_normalize_line(ln.strip()) for p in pages for ln in p.text.splitlines() if ln.strip()]

    # Add high-confidence explicit exam-date matches from richer patterns.
    explicit_exam_hits = _extract_exam_from_patterns(
        all_lines,
        default_year=default_year,
    )
    window_exam_hits = _extract_exam_from_local_windows(
        all_lines,
        default_year=default_year,
    )

    assessments: list[Assessment] = []
    seen: set[tuple[int, str]] = set()
    for page_number, ln in assessment_lines:
        key = (page_number, ln.lower())
        if key in seen:
            continue
        seen.add(key)

        page_lines = [_normalize_line(x.strip()) for x in pages[page_number - 1].text.splitlines() if x.strip()]
        try:
            line_idx = page_lines.index(ln)
        except ValueError:
            line_idx = -1
        dt = (
            _best_inline_or_neighbor_date(page_lines, line_idx, default_year=default_year)
            if line_idx >= 0
            else None
        )
        name = _normalize_title(re.sub(_DATE_RE, "", ln).strip(" -–—:\t"))
        name = name or ln[:80]
        if _line_is_noise(name):
            continue

        assessments.append(
            Assessment(
                name=name[:120],
                type=_guess_assessment_type(name),
                scheduled_date=dt,
                confidence=Confidence(
                    value=0.65 if dt else 0.3,
                    reason="Keyword match" + (" + inline date" if dt else " (no date parsed)"),
                ),
                source={"page": page_number, "line": ln},
            )
        )

    for label, dt in explicit_exam_hits + window_exam_hits:
        incoming_key = _canonical_assessment_name(label)
        existing = next((a for a in assessments if _canonical_assessment_name(a.name) == incoming_key), None)
        if existing:
            # Upgrade missing dates from explicit matches, but avoid duplicate rows.
            if existing.scheduled_date is None:
                existing.scheduled_date = dt
                existing.confidence = Confidence(value=0.78, reason="Date filled from explicit exam/date pattern")
            continue
        assessments.append(
            Assessment(
                name=label[:120],
                type=_guess_assessment_type(label),
                scheduled_date=dt,
                confidence=Confidence(value=0.78, reason="Explicit exam/date pattern match"),
                source={"page": None, "line": "pattern_match"},
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
        in_topic_section = False
        page_lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]
        # Try parsing schedule-like rows first.
        for title in _extract_topics_from_schedule_lines(page_lines):
            topics.append(
                Topic(
                    title=title[:160],
                    cues=["schedule_row"],
                    source={"page": page.page_number, "line": "schedule_row"},
                )
            )
        for ln in page_lines:
            raw = ln.strip()
            if _line_is_noise(raw):
                continue
            low = raw.lower()
            if any(h in low for h in _TOPIC_SECTION_HINTS):
                in_topic_section = True
            if any(h in low for h in _TOPIC_SECTION_END_HINTS):
                in_topic_section = False

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
            if m2 and in_topic_section and len(raw) < 120:
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

    # If the syllabus is week-based with no concrete dates, expose this as a constraint.
    if re.search(r"\bweeks?\s*\d+\b", full_text, flags=re.IGNORECASE) and not re.search(r"\b20\d{2}\b", full_text):
        course.constraints_found.append(
            "Week-based schedule detected without explicit calendar dates; exam dates should be provided manually."
        )

    dated = [a.scheduled_date for a in course.assessments if a.scheduled_date]
    if dated:
        course.end_date = max(dated)
        course.confidences["end_date"] = Confidence(
            value=0.4, reason="Latest detected assessment date"
        )

    return course

