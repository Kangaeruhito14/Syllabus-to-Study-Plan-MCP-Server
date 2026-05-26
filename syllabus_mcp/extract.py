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


# ── PDF reading ────────────────────────────────────────────────────────────────

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> list[TextPage]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[TextPage] = []
    for i, p in enumerate(reader.pages, start=1):
        t = p.extract_text() or ""
        pages.append(TextPage(page_number=i, text=t))
    return pages


# ── Shared constants ───────────────────────────────────────────────────────────

_MONTH_NAMES = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|(?:"
    + _MONTH_NAMES
    + r")\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}\s+(?:"
    + _MONTH_NAMES
    + r")(?:\s+\d{4})?)\b",
    flags=re.IGNORECASE,
)

_ASSESSMENT_KEYWORDS = ["midterm", "final", "exam", "quiz", "project", "assignment", "test"]
_ASSESSMENT_BLOCKERS = {
    "blackboard", "attendance", "office hours", "contact instructor",
    "academic integrity", "late work", "must be submitted", "must be in prior",
    "instructor reserves", "participation",
}
_TOPIC_BLOCKERS = {
    "attendance", "policy", "policies", "grading", "blackboard",
    "office hours", "accommodations", "integrity", "disability",
    "withdraw", "copyright", "plagiarism", "prerequisites", "textbook",
    "required materials", "course description", "instructor",
}
_TOPIC_SECTION_HINTS = {
    "schedule", "weekly", "topics", "course outline", "tentative calendar",
    "course calendar", "module", "unit", "course schedule", "class schedule",
    "lecture schedule", "course content",
}
_TOPIC_SECTION_END_HINTS = {
    "grading", "attendance", "policies", "academic integrity",
    "disability", "office hours", "course policies", "student conduct",
}
_OBJECTIVES_SECTION_HINTS = {
    "course objectives", "learning objectives", "learning outcomes",
    "student learning outcomes", "topics covered", "course topics",
    "upon completion", "students will", "you will learn",
}

_EXAM_DATE_PATTERNS = [
    re.compile(
        rf"\b(?P<label>(?:midterm|final)\s*(?:exam|project|test)?|exam\s*\d+|quiz\s*\d+)"
        rf"[\s:,\-–]*(?:on\s+)?(?P<date>{_MONTH_NAMES}\s+\d{{1,2}}(?:,\s*\d{{4}})?|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<date>(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)"
        rf"[\s:,\-–]*(?P<label>(?:midterm|final)\s*(?:exam|project|test)?|exam|quiz)",
        flags=re.IGNORECASE,
    ),
]


# ── Date utilities ─────────────────────────────────────────────────────────────

def _safe_parse_date(s: str, *, default_year: int | None = None) -> date | None:
    try:
        s = s.strip()
        if default_year and not re.search(r"\b\d{4}\b", s) and re.search(r"[A-Za-z]", s):
            s = f"{s} {default_year}"
        dt = dateparser.parse(s, fuzzy=False)
        if dt and dt.year < 2000:
            return None
        return dt.date() if dt else None
    except Exception:
        return None


def _find_date_in_text(text: str, *, default_year: int | None = None) -> date | None:
    for m in _DATE_RE.finditer(text):
        d = _safe_parse_date(m.group(0), default_year=default_year)
        if d:
            return d
    return None


# ── Line normalisation ─────────────────────────────────────────────────────────

def _normalize_line(raw: str) -> str:
    s = raw.replace("|", " | ")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_title(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip()
    s = s.replace("|", "")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _line_is_noise(raw: str) -> bool:
    low = raw.lower().strip()
    if not low or len(low) < 3:
        return True
    if low in {".", "-", "--", "●", "•", "○", "◆"}:
        return True
    if any(k in low for k in _TOPIC_BLOCKERS):
        return True
    if re.match(r"^[A-Z\s]{2,}$", raw) and len(raw.split()) <= 3:
        return True
    if len(raw) > 250:
        return True
    return False


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


# ── Title detection ────────────────────────────────────────────────────────────

def _detect_course_title(pages: list[TextPage]) -> tuple[str | None, float]:
    """
    Returns (title, confidence).
    Priority:
    1. "Course Title:" or "Course Name:" label on any page
    2. Explicit course code line (e.g. CSCI 3400 - Database...)
    3. First non-empty, non-header line of page 1
    """
    full_text = "\n".join(p.text for p in pages)
    norm = "\n".join(_normalize_line(ln) for ln in full_text.splitlines())

    # 1) Explicit label
    label_re = re.compile(
        r"(?:^|\n)\s*(?:course\s+(?:title|name)\s*[:–\-])\s*(.+)",
        flags=re.IGNORECASE,
    )
    m = label_re.search(norm)
    if m:
        candidate = _normalize_title(m.group(1)).strip()
        if candidate and not _line_is_noise(candidate) and len(candidate) < 150:
            return candidate[:120], 0.92

    # 2) Course-code line anywhere in first 2 pages
    code_re = re.compile(r"\b[A-Z]{2,5}[-\s]?\d{3,4}\b")
    for page in pages[:2]:
        lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]
        for ln in lines[:20]:
            if code_re.search(ln) and not _line_is_noise(ln) and len(ln) < 120:
                cleaned = re.sub(r"^(course\s*[:–\-]\s*)", "", ln, flags=re.IGNORECASE).strip()
                return _normalize_title(cleaned)[:120], 0.85

    # 3) First meaningful line on page 1 that is not a generic header
    generic_headers = {"course syllabus", "syllabus", "class syllabus", "course outline"}
    if pages:
        lines = [_normalize_line(ln.strip()) for ln in pages[0].text.splitlines() if ln.strip()]
        for ln in lines[:10]:
            low = ln.lower().strip()
            if low in generic_headers:
                continue
            if not _line_is_noise(ln) and 5 < len(ln) < 120:
                return _normalize_title(ln)[:120], 0.45

    return None, 0.0


# ── Topic extraction ───────────────────────────────────────────────────────────

def _extract_topics_week_module(lines: list[str], page_num: int) -> list[Topic]:
    """Week 1: ... / Module 2: ... / Lecture 3: ..."""
    topics: list[Topic] = []
    pattern = re.compile(
        r"^(?:week|wk|module|lecture|unit|class|session)\s*(\d{1,3})?\s*[:.\-–—]?\s*(.+)$",
        flags=re.IGNORECASE,
    )
    for ln in lines:
        m = pattern.match(ln.strip())
        if not m:
            continue
        week_num = int(m.group(1)) if m.group(1) else None
        title = m.group(2).strip(" -:;")
        title = re.sub(_DATE_RE, "", title).strip(" -:;")
        if not title or _line_is_noise(title) or len(title.split()) > 14:
            continue
        topics.append(Topic(
            title=_normalize_title(title)[:160],
            week=week_num,
            module=m.group(0).split()[0].lower() if m.group(0) else None,
            cues=[],
            source={"page": page_num, "line": ln},
        ))
    return topics


def _extract_topics_date_column(lines: list[str], page_num: int, default_year: int | None) -> list[Topic]:
    """
    Table/schedule style: `Jan 13   Introduction to Databases   Ch. 1`
    The date is in column 1, topic in column 2.
    Handles both whitespace-separated and tab-separated layouts.
    """
    topics: list[Topic] = []
    date_lead_re = re.compile(
        rf"^(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?\s+(.+)"
        rf"|^\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?\s+(.+)",
        flags=re.IGNORECASE,
    )
    for ln in lines:
        raw = ln.strip()
        m = date_lead_re.match(raw)
        if not m:
            continue
        # group 1 or group 2 is the remainder after the date
        remainder = (m.group(1) or m.group(2) or "").strip()
        # strip trailing reading reference like "Ch. 3" or "pp. 40-60"
        remainder = re.sub(r"\s+(ch(?:apter)?\.?\s*\d+[\w\-,\s]*|pp?\.?\s*\d+.*)$", "", remainder, flags=re.IGNORECASE).strip()
        # strip percentage references like "30%"
        remainder = re.sub(r"\s+\d+%$", "", remainder).strip()
        if not remainder or _line_is_noise(remainder) or len(remainder.split()) > 14:
            continue
        # Skip if the remainder itself looks like an exam/admin line we'd catch elsewhere
        if any(b in remainder.lower() for b in _ASSESSMENT_BLOCKERS):
            continue
        topics.append(Topic(
            title=_normalize_title(remainder)[:160],
            cues=["date_column"],
            source={"page": page_num, "line": ln},
        ))
    return topics


def _extract_topics_objectives(lines: list[str], page_num: int) -> list[Topic]:
    """
    Course Objectives / Learning Outcomes bullet lists.
    Captures bullet-point items in a known objectives section.
    """
    topics: list[Topic] = []
    in_section = False
    bullet_re = re.compile(r"^[\s]*[●•○◆\-\*]\s+(.+)$")
    numbered_re = re.compile(r"^[\s]*\d{1,2}[.)]\s+(.+)$")

    for ln in lines:
        low = ln.lower().strip()

        # Detect section start
        if any(hint in low for hint in _OBJECTIVES_SECTION_HINTS):
            in_section = True
            continue

        # Detect section end
        if in_section and any(hint in low for hint in _TOPIC_SECTION_END_HINTS):
            in_section = False
            continue
        # Also end on a blank-ish line after collecting some topics, unless still seeing bullets
        if in_section and not ln.strip() and topics:
            # allow one blank line; stop on two
            pass

        if not in_section:
            continue

        for pat in (bullet_re, numbered_re):
            m = pat.match(ln)
            if m:
                title = m.group(1).strip()
                # Strip trailing separators like "● Nouns, Adjectives, and Articles● Pronouns"
                # (when bullets are on one line separated by ●)
                sub_items = re.split(r"[●•○◆]", title)
                for item in sub_items:
                    item = item.strip(" -–—:,;")
                    if item and len(item) >= 3 and not _line_is_noise(item) and len(item.split()) <= 12:
                        topics.append(Topic(
                            title=_normalize_title(item)[:160],
                            cues=["objectives"],
                            source={"page": page_num, "line": ln},
                        ))
                break

        # Also handle inline bullet separation on same line (no leading bullet)
        # e.g. "Nouns, Adjectives● Pronouns● Verbs" when in_section
        if in_section and "●" in ln:
            for part in ln.split("●"):
                part = part.strip(" -–—:,;")
                if part and len(part) >= 3 and not _line_is_noise(part) and len(part.split()) <= 10:
                    topics.append(Topic(
                        title=_normalize_title(part)[:160],
                        cues=["objectives_inline"],
                        source={"page": page_num, "line": ln},
                    ))

    return topics


def _extract_topics_numbered_in_section(lines: list[str], page_num: int) -> list[Topic]:
    """
    Numbered list items inside a detected topic/schedule section.
    e.g.  1. Introduction  2. Data Types  3. Functions
    """
    topics: list[Topic] = []
    in_topic_section = False
    enum_re = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")

    for ln in lines:
        low = ln.lower().strip()
        if any(h in low for h in _TOPIC_SECTION_HINTS):
            in_topic_section = True
        if any(h in low for h in _TOPIC_SECTION_END_HINTS):
            in_topic_section = False

        if not in_topic_section:
            continue
        m = enum_re.match(ln)
        if m:
            title = m.group(2).strip()
            if title and not _line_is_noise(title) and len(title.split()) <= 14:
                topics.append(Topic(
                    title=_normalize_title(title)[:160],
                    cues=["numbered_in_section"],
                    source={"page": page_num, "line": ln},
                ))
    return topics


# ── Assessment extraction ──────────────────────────────────────────────────────

def _likely_assessment_line(raw: str) -> bool:
    low = raw.lower()
    if not any(k in low for k in _ASSESSMENT_KEYWORDS):
        return False
    if any(b in low for b in _ASSESSMENT_BLOCKERS):
        return False
    has_date = _DATE_RE.search(raw) is not None
    # Reject very long lines without a date — likely policy text
    if len(raw.split()) > 18 and not has_date:
        return False
    if ":" not in raw and not has_date and len(raw.split()) > 10:
        return False
    return True


def _canonical_name(raw: str) -> str:
    s = _normalize_title(raw).lower()
    s = re.sub(_DATE_RE, "", s).strip(" -–—:,\t")
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_assessments(
    pages: list[TextPage], *, default_year: int | None = None
) -> list[Assessment]:
    assessments: list[Assessment] = []
    seen_canonical: set[str] = set()

    # Pass 1: explicit inline date patterns
    all_lines: list[str] = []
    for page in pages:
        for ln in page.text.splitlines():
            all_lines.append(_normalize_line(ln.strip()))

    for pat in _EXAM_DATE_PATTERNS:
        for ln in all_lines:
            m = pat.search(ln)
            if not m:
                continue
            if any(b in ln.lower() for b in _ASSESSMENT_BLOCKERS):
                continue
            label = _normalize_title(m.group("label"))
            dt = _safe_parse_date(m.group("date"), default_year=default_year)
            if not label or not dt:
                continue
            key = _canonical_name(label)
            if key in seen_canonical:
                # Update date if existing entry has none
                for a in assessments:
                    if _canonical_name(a.name) == key and a.scheduled_date is None:
                        a.scheduled_date = dt
                        a.confidence = Confidence(value=0.82, reason="Explicit pattern match")
                continue
            seen_canonical.add(key)
            assessments.append(Assessment(
                name=label[:120],
                type=_guess_assessment_type(label),
                scheduled_date=dt,
                confidence=Confidence(value=0.82, reason="Explicit exam/date pattern"),
                source={"page": None, "line": "pattern_match"},
            ))

    # Pass 2: date-column table rows with exam keywords
    # e.g. "Feb 17   MIDTERM EXAM" or "Apr 21   FINAL EXAM"
    exam_kw_re = re.compile(r"\b(midterm|final\s+exam|exam|quiz)\b", flags=re.IGNORECASE)
    date_first_re = re.compile(
        rf"^(?:(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)\s+(.+)$",
        flags=re.IGNORECASE,
    )
    for ln in all_lines:
        m = date_first_re.match(ln)
        if not m:
            continue
        remainder = m.group(1).strip()
        if not exam_kw_re.search(remainder):
            continue
        if any(b in remainder.lower() for b in _ASSESSMENT_BLOCKERS):
            continue
        dt = _find_date_in_text(ln, default_year=default_year)
        name = _normalize_title(re.sub(_DATE_RE, "", remainder).strip(" -–—:,\t"))
        if not name or _line_is_noise(name):
            continue
        key = _canonical_name(name)
        if key in seen_canonical:
            continue
        seen_canonical.add(key)
        assessments.append(Assessment(
            name=name[:120],
            type=_guess_assessment_type(name),
            scheduled_date=dt,
            confidence=Confidence(value=0.78, reason="Date-column table row"),
            source={"page": None, "line": "date_column"},
        ))

    # Pass 3: keyword lines with inline or neighbor dates (per-page scan)
    for page in pages:
        page_lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]
        for idx, ln in enumerate(page_lines):
            if not _likely_assessment_line(ln):
                continue
            # Try inline date first, then +/-1 lines
            dt = _find_date_in_text(ln, default_year=default_year)
            if dt is None:
                for probe in (idx + 1, idx - 1):
                    if 0 <= probe < len(page_lines):
                        dt = _find_date_in_text(page_lines[probe], default_year=default_year)
                        if dt:
                            break

            name = _normalize_title(re.sub(_DATE_RE, "", ln).strip(" -–—:,\t"))
            # Remove trailing % (grading weight)
            name = re.sub(r"\s+\d+%$", "", name).strip()
            if not name or _line_is_noise(name) or len(name) < 3:
                continue
            key = _canonical_name(name)
            if key in seen_canonical:
                # Just fill in missing date
                for a in assessments:
                    if _canonical_name(a.name) == key and a.scheduled_date is None and dt:
                        a.scheduled_date = dt
                continue
            seen_canonical.add(key)
            assessments.append(Assessment(
                name=name[:120],
                type=_guess_assessment_type(name),
                scheduled_date=dt,
                confidence=Confidence(
                    value=0.68 if dt else 0.32,
                    reason="Keyword match" + (" + date" if dt else " (no date)"),
                ),
                source={"page": page.page_number, "line": ln},
            ))

    # Remove clearly noisy entries
    cleaned: list[Assessment] = []
    for a in assessments:
        if any(b in a.name.lower() for b in _ASSESSMENT_BLOCKERS):
            continue
        if len(a.name.split()) > 15:
            continue
        cleaned.append(a)

    return cleaned


# ── Non-syllabus detection ─────────────────────────────────────────────────────

_SYLLABUS_SIGNAL_WORDS = {
    "syllabus", "course", "instructor", "professor", "lecture", "exam",
    "midterm", "final", "assignment", "grading", "schedule", "week",
    "module", "semester", "credit", "prerequisite", "textbook", "objectives",
    "learning outcomes", "quiz", "project", "attendance",
}


def is_likely_syllabus(text: str) -> tuple[bool, float]:
    """
    Returns (is_syllabus, confidence 0-1).
    A simple signal-word density check — cheap, no API needed.
    """
    low = text.lower()
    total_words = max(len(low.split()), 1)
    hits = sum(1 for w in _SYLLABUS_SIGNAL_WORDS if w in low)
    density = hits / len(_SYLLABUS_SIGNAL_WORDS)

    if density >= 0.35:
        return True, min(0.55 + density * 0.5, 0.95)
    if density >= 0.15:
        return True, 0.40  # borderline — probably a syllabus but uncertain
    return False, density


# ── Main entry point ───────────────────────────────────────────────────────────

def extract_course_model_from_pages(
    pages: list[TextPage], *, timezone: str | None = None
) -> CourseModel:
    full_text = "\n".join(p.text for p in pages).strip()
    norm_text = "\n".join(_normalize_line(ln) for ln in full_text.splitlines())

    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", full_text)]
    default_year = min(years) if years else None

    course = CourseModel(timezone=timezone)
    course.extracted_text_summary = norm_text[:1200] if norm_text else None

    # ── Title ─────────────────────────────────────────────────────────────────
    title, title_conf = _detect_course_title(pages)
    if title:
        course.course_title = title
        course.confidences["course_title"] = Confidence(
            value=title_conf, reason="Multi-strategy title detection"
        )

    # ── Topics ────────────────────────────────────────────────────────────────
    all_topics: list[Topic] = []
    for page in pages:
        norm_lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]

        # Strategy 1: Week/Module/Lecture prefix
        all_topics.extend(_extract_topics_week_module(norm_lines, page.page_number))

        # Strategy 2: Date-column table rows (Jan 13   Introduction to Databases)
        all_topics.extend(_extract_topics_date_column(norm_lines, page.page_number, default_year))

        # Strategy 3: Course Objectives / Learning Outcomes bullet points
        all_topics.extend(_extract_topics_objectives(norm_lines, page.page_number))

        # Strategy 4: Numbered list inside a detected topic section
        all_topics.extend(_extract_topics_numbered_in_section(norm_lines, page.page_number))

    # Deduplicate by title (case-insensitive), prefer earlier / higher-priority strategies
    seen_titles: dict[str, Topic] = {}
    for t in all_topics:
        key = t.title.strip().lower()
        if key and key not in seen_titles:
            seen_titles[key] = t
    course.topics = list(seen_titles.values())

    # ── Assessments ───────────────────────────────────────────────────────────
    course.assessments = _extract_assessments(pages, default_year=default_year)

    # ── Constraints: week-based detection ─────────────────────────────────────
    if (
        re.search(r"\bweeks?\s*\d+", norm_text, flags=re.IGNORECASE)
        and not re.search(r"\b20\d{2}\b", norm_text)
    ):
        course.constraints_found.append(
            "Week-based schedule detected without explicit calendar dates; "
            "exam dates should be provided manually."
        )

    # ── End date from latest dated assessment ─────────────────────────────────
    dated = [a.scheduled_date for a in course.assessments if a.scheduled_date]
    if dated:
        course.end_date = max(dated)
        course.confidences["end_date"] = Confidence(
            value=0.6, reason="Latest detected assessment date"
        )

    return course
