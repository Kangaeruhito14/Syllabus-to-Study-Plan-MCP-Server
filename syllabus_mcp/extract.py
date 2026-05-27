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
    "room", "classroom", "location", "http://", "https://",
    "no class", "holiday", "spring break", "fall break", "thanksgiving",
    "information", "student development", "participation", "grade points",
    "learning activities", "learning objective", "approximate time",
}
_TOPIC_SECTION_HINTS = {
    "schedule", "weekly", "topics", "course outline", "tentative calendar",
    "course calendar", "module", "unit", "course schedule", "class schedule",
    "lecture schedule", "course content", "course description",
}
_TOPIC_SECTION_END_HINTS = {
    "grading", "attendance", "policies", "academic integrity",
    "disability", "office hours", "course policies", "student conduct",
    "references", "recommended books", "recommended reading", "bibliography",
    "required textbook", "textbooks", "required texts", "required reading",
    "course materials", "reading list",
}
_OBJECTIVES_SECTION_HINTS = {
    "course objectives", "learning objectives", "learning outcomes",
    "student learning outcomes", "topics covered", "course topics",
    "upon completion", "students will", "you will learn",
}

# Word-boundary compiled versions of the section hint sets (prevent substring false-positives
# e.g. "unit" matching inside "opportunity" or "community").
def _make_section_re(hints: set[str]) -> re.Pattern[str]:
    pat = "|".join(re.escape(h) for h in sorted(hints, key=len, reverse=True))
    return re.compile(r"\b(?:" + pat + r")\b", re.IGNORECASE)

_TOPIC_SECTION_RE = _make_section_re(_TOPIC_SECTION_HINTS)
_TOPIC_SECTION_END_RE = _make_section_re(_TOPIC_SECTION_END_HINTS)
_OBJECTIVES_SECTION_RE = _make_section_re(_OBJECTIVES_SECTION_HINTS)

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


_PAGE_HEADER_RE = re.compile(r"^page\s+\d+\s+of\s+\d+", re.IGNORECASE)
_OCR_BULLET_RE = re.compile(r"^[oOeE°]\s+")  # OCR misreads bullets as 'o', 'e', '°'
_OBJECTIVE_SENT_RE = re.compile(
    r"^(?:to\s+(?:understand|develop|learn|trace|explore|apply|analyze|analyse|study|examine|provide|help|enable|"
    r"identify|introduce|create|demonstrate|recognize|evaluate|describe|explain|compare|build|foster|"
    r"facilitate|promote|prepare|encourage|use|utilize|engage|assess|cultivate|familiarize|equip|enhance|"
    r"strengthen|acquire|discuss|review|investigate|explore|grow|become|make|give|ensure|verify|conduct)|"
    r"students?\s+will|the\s+students?\s+will|you\s+will|upon\s+completion|learners?\s+will|"
    r"this\s+course\s+will|participants?\s+will|"
    r"after\s+(?:successful\s+)?completion|"
    # Bloom's taxonomy imperative-verb learning outcome sentences (5+ word filter applied at call site)
    r"(?:represent|encode|evaluate|simplify|analyze|analyse|design|implement|describe|demonstrate|"
    r"apply|identify|synthesize|argue|write|recognize|compute|determine|familiarize|construct|"
    r"interpret|distinguish|differentiate|relate|solve|calculate|classify|formulate|justify|"
    r"grasp|obtain|acquire|state|define|list|name|recall|select|measure|perform|operate|"
    r"predict|generate|infer|compare|contrast|understand|introduce|find|add|subtract|get|"
    r"learn|become|achieve|expose|cope|deal|grow|make|use|conduct|ensure|verify|test)\s+\S)",
    re.IGNORECASE,
)
_VERSION_LINE_RE = re.compile(r"^v\.\d+\s+dated|^version\s+\d", re.IGNORECASE)


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
    # Skip page header artifacts like "Page 1 of 8"
    if _PAGE_HEADER_RE.match(low):
        return True
    # Skip pure version strings
    if _VERSION_LINE_RE.match(raw):
        return True
    # Skip standalone numbers or short letter codes
    if re.match(r"^\d+\.?\s*$", raw):
        return True
    # Skip lines starting with punctuation (HTML fragment artifacts or OCR artifacts)
    if raw and raw[0] in ",;:.)]-=":
        return True
    # Skip fragment titles: start with 1-3 char all-lowercase word (likely mid-word split)
    first_word = raw.split()[0] if raw.split() else ""
    if len(first_word) <= 3 and first_word.islower() and not first_word.endswith("."):
        return True
    return False


def _strip_ocr_artifacts(line: str) -> str:
    """Remove leading OCR-misread bullets ('o ', 'e ') and stray dashes."""
    line = _OCR_BULLET_RE.sub("", line.strip())
    line = re.sub(r"^[-–—]\s+", "", line)
    return line.strip()


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
        # Strip "Course Credits: N" suffix that can trail on the same label line
        candidate = re.sub(r"\s+course\s+credits?\s*[:=]\s*\d+.*$", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s*:\s*\d+\s*credits?.*$", "", candidate, flags=re.IGNORECASE).strip()
        if candidate and not _line_is_noise(candidate) and len(candidate) < 150:
            return candidate[:120], 0.92

    # 1.5) "Syllabus/Curriculum for <program>" — catches multi-course program documents
    prog_re = re.compile(r"(?:syllabus|curriculum|program)\s+(?:for|of)\s+(.+)", re.IGNORECASE)
    for page in pages[:5]:
        for ln in [_normalize_line(raw.strip()) for raw in page.text.splitlines() if raw.strip()]:
            pm = prog_re.match(ln)
            if pm:
                candidate = _normalize_title(pm.group(1)).strip()
                # Remove trailing parenthetical like "(Effective from 2018-19)"
                candidate = re.sub(r"\s*\(.*\)\s*$", "", candidate).strip()
                if candidate and not _line_is_noise(candidate) and 5 < len(candidate) < 120:
                    return candidate[:120], 0.88

    # 2) Course-code line anywhere in first 2 pages
    code_re = re.compile(r"\b[A-Z]{2,5}[-\s]?\d{3,4}\b")
    for page in pages[:2]:
        lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]
        for ln in lines[:20]:
            cleaned = _strip_ocr_artifacts(ln)
            if code_re.search(cleaned) and not _line_is_noise(cleaned) and len(cleaned) < 120:
                cleaned = re.sub(r"^(course\s*[:–\-]\s*)", "", cleaned, flags=re.IGNORECASE).strip()
                # Skip if it's just a code embedded in a long sentence
                if len(cleaned.split()) > 12:
                    continue
                return _normalize_title(cleaned)[:120], 0.85

    # 3) First meaningful line on page 1 that is not a generic header
    generic_headers = {
        "course syllabus", "syllabus", "class syllabus", "course outline",
        "syllabus and course information", "course information", "on-campus course syllabus",
        "online course syllabus", "course syllabus template", "common syllabus content",
    }
    _skip_title_re = re.compile(
        r"^page\s+\d+|^\d+\s*$|^v\.\d+|^version\s+\d|^printed|^last\s+updated|"
        r"course\s*credits?\s*[:=]|^subject\s*code",
        re.IGNORECASE,
    )
    if pages:
        lines = [_normalize_line(ln.strip()) for ln in pages[0].text.splitlines() if ln.strip()]
        for ln in lines[:15]:
            low = ln.lower().strip()
            cleaned = _strip_ocr_artifacts(ln)
            if not cleaned:
                continue
            if low in generic_headers:
                continue
            if _skip_title_re.search(cleaned):
                continue
            # Strip trailing "Course Credits: 2" style suffixes
            cleaned = re.sub(r"\s+course\s+credits?\s*[:=]\s*\d+.*$", "", cleaned, flags=re.IGNORECASE).strip()
            # Strip trailing ":  2 credits" style
            cleaned = re.sub(r"\s*:\s*\d+\s*credits?.*$", "", cleaned, flags=re.IGNORECASE).strip()
            if not cleaned:
                continue
            if not _line_is_noise(cleaned) and 5 < len(cleaned) < 120:
                return _normalize_title(cleaned)[:120], 0.45

    return None, 0.0


# ── Topic extraction ───────────────────────────────────────────────────────────

def _extract_topics_week_module(lines: list[str], page_num: int) -> list[Topic]:
    """Week 1: ... / Module 2: ... / Lecture 3: ..."""
    topics: list[Topic] = []
    pattern = re.compile(
        r"^(?:week|wk|module|lecture|unit|class|session)\b\s*(\d{1,3})?\s*[:.\-–—]?\s*(.+)$",
        flags=re.IGNORECASE,
    )
    for ln in lines:
        m = pattern.match(ln.strip())
        if not m:
            continue
        week_num = int(m.group(1)) if m.group(1) else None
        title = m.group(2).strip(" -:;")
        title = re.sub(_DATE_RE, "", title).strip(" -:;")
        # Strip Roman numeral section prefix (e.g. "I: Topic" or "Il: Topic" from OCR)
        title = re.sub(r"^(?:I{1,3}|I[Vl]|V?I{0,3}|Il{1,2}|Ill?):\s*", "", title).strip(" -:;")
        # Strip "[N lectures/hrs]" or "(N lectures/hrs)" bracketed suffixes
        title = re.sub(r"\s*[\[\(]\d+\s*(?:lectures?|hrs?\.?|hours?|classes?|sessions?)[\]\)].*$", "", title, flags=re.IGNORECASE).strip()
        # Strip "Two weeks", "Three weeks" etc schedule-column suffixes
        title = re.sub(r"\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+weeks?\s*$", "", title, flags=re.IGNORECASE).strip()
        # Strip trailing period left after cleaning
        title = title.rstrip(".")
        if not title or _line_is_noise(title) or len(title.split()) > 14:
            continue
        # Reject punctuation-heavy or too-short fragments
        if re.match(r"^[\W\d\s]+$", title) or len(title) < 4:
            continue
        # Reject sentence fragments (start lowercase + ends with ")." or similar)
        if title[0].islower() and re.search(r"[)\]\.]{1,2}$", title) and len(title.split()) <= 3:
            continue
        # Reject prose continuation after section keyword (e.g. "unit concentrates on...")
        if title[0].islower() and len(title.split()) > 3:
            continue
        # Reject exam/test/quiz days in schedule (caught by assessment extractor)
        if re.search(r"\b(exam|midterm|final|test\s*\d|quiz)\b", title, re.IGNORECASE):
            continue
        # Reject generic schedule column labels (activity types, not topics)
        if re.match(r"^(?:activity|discussion|assignments?|quiz|review|resources?|readings?)\s*\d*$", title, re.IGNORECASE):
            continue
        if re.search(r"\bcritical\s+thinking\s+questions?\b", title, re.IGNORECASE):
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
    Also handles: `3 5/31/16 Sources of Demographic Data. Ch. 4` (row# before date).
    """
    topics: list[Topic] = []
    # Pattern 1: date at start of line
    date_lead_re = re.compile(
        rf"^(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?\s+(.+)"
        rf"|^\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?\s+(.+)",
        flags=re.IGNORECASE,
    )
    # Pattern 2: row_number then date (e.g. "3 5/31/16 Sources of Demographic Data.")
    row_date_re = re.compile(
        rf"^\d{{1,2}}\s+(?:(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)\s+(.+)",
        flags=re.IGNORECASE,
    )
    # Pattern 3: weekday abbrev + date (e.g. "M 8/25 Orientation Meeting" or "W 9/10 ...")
    _WD = r"(?:M|T|W|Th|F|Sa|Su|Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    weekday_date_re = re.compile(
        rf"^{_WD}\s+(?:(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)\s+(.+)",
        flags=re.IGNORECASE,
    )
    for ln in lines:
        raw = ln.strip()
        remainder = None
        m = date_lead_re.match(raw)
        if m:
            remainder = (m.group(1) or m.group(2) or "").strip()
        elif row_date_re.match(raw):
            remainder = row_date_re.match(raw).group(1).strip()
        elif weekday_date_re.match(raw):
            # Split by 3+ spaces to isolate the topic column from chapter ref column
            parts = re.split(r"\s{3,}", raw, maxsplit=3)
            if len(parts) >= 3:
                remainder = parts[1].strip()  # topic is middle column
            else:
                remainder = weekday_date_re.match(raw).group(1).strip()
        if remainder is None:
            continue
        # Skip time-only remainders like "12-1 pm" (exam time slots, not topics)
        if re.match(r"^\d+[-–]\d+\s*(?:am|pm)?$", remainder, re.IGNORECASE):
            continue
        # Skip first-day "Syllabus" review sessions (not a study topic)
        if re.match(r"^syllabus\b", remainder, re.IGNORECASE):
            continue
        # Strip "Web Movies, ..." style in-line media annotations before other strips
        remainder = re.sub(r"\s+Web\s+Movies?(?:[,\s].*)?$", "", remainder, flags=re.IGNORECASE).strip()
        # Strip trailing reading/textbook references: "Ch. 3", "pp. 40-60", "ExSyn: 31-35", "WB: Lesson 2"
        remainder = re.sub(r"\s+(ch(?:apter)?\.?\s*\d+[\w\-,\s]*|pp?\.?\s*\d+.*)$", "", remainder, flags=re.IGNORECASE).strip()
        # Strip abbreviated textbook refs like "ExSyn: 31", "WB:", "NA 27", biblical refs like "Phil 1:1"
        remainder = re.sub(r"\s+[A-Z][a-zA-Z]{0,6}:\s*[\w\-]+.*$", "", remainder).strip()
        # Strip trailing chapter code patterns like "C1, R3", "BV,G1-4", "BV,G 1-4", "Web Movies, C6"
        remainder = re.sub(r"\s+(?:[A-Z]{1,4}\s*\d+)(?:[,\s]+(?:[A-Z]{1,4}\s*\d+|Web\s+\w+))*\s*$", "", remainder).strip()
        # Also strip orphaned capital-letter abbreviation clusters (e.g. "BV,G" after digit stripping)
        remainder = re.sub(r"\s+[A-Z]{1,4}(?:,[A-Z]{1,4})*\s*$", "", remainder).strip()
        # Strip composite textbook codes like "BV,G 1-4" (letter+comma+letter+space+digits, with optional space)
        remainder = re.sub(r"\s+[A-Z]{1,4}(?:,[A-Z]{1,4})+\s*\d+(?:[-,\s–]*\d+)*\s*$", "", remainder).strip()
        # Strip trailing "none", "Quiz N", standalone digits, and similar noise
        remainder = re.sub(r"\s+(?:none|quiz\s*\d+|\d{1,3}-\d{1,3})\s*.*$", "", remainder, flags=re.IGNORECASE).strip()
        # Strip percentage references like "30%"
        remainder = re.sub(r"\s+\d+%$", "", remainder).strip()
        # Strip orphaned 1-3 char abbreviated words at end (e.g. "intro to case Ex" → "intro to case")
        remainder = re.sub(r"\s+[A-Z][a-zA-Z]{0,2}\s*$", "", remainder).strip()
        # Strip trailing commas left after code stripping
        remainder = remainder.rstrip(",").strip()
        if not remainder or _line_is_noise(remainder) or len(remainder.split()) > 14:
            continue
        # Skip if the remainder itself looks like an exam/admin line we'd catch elsewhere
        if any(b in remainder.lower() for b in _ASSESSMENT_BLOCKERS):
            continue
        # Skip assessment lines (exam/test/quiz day in schedule) and checkpoint-type items
        if re.search(r"\b(exam|midterm|final|test\s*\d|quiz\s*\d|checkpoint)\b", remainder, re.IGNORECASE):
            continue
        # Skip activity/assignment column headers in schedule tables
        if re.search(r"\bcritical\s+thinking\s+questions?\b", remainder, re.IGNORECASE):
            continue
        # Skip grading weight lines
        if re.search(r"\d+\s*%", remainder):
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

        # Detect section start (word-boundary match)
        if _OBJECTIVES_SECTION_RE.search(low):
            in_section = True
            continue

        # Detect section end — including "course description" which opens the topic section
        if in_section and (_TOPIC_SECTION_END_RE.search(low) or "course description" in low):
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
                # Strip leading "N " prefix from double-numbered items (e.g. "1. 1 Crystal Structure")
                title = re.sub(r"^\d+\s+", "", title).strip()
                # Strip trailing separators like "● Nouns, Adjectives, and Articles● Pronouns"
                sub_items = re.split(r"[●•○◆]", title)
                for item in sub_items:
                    item = item.strip(" -–—:,;")
                    if not item or len(item) < 3:
                        continue
                    # Reject prose continuation (starts lowercase)
                    if item[0].islower():
                        continue
                    # Reject sentence-style learning outcomes (ends with period + >= 5 words)
                    if item.endswith('.') and len(item.split()) >= 5:
                        continue
                    if _line_is_noise(item) or len(item.split()) > 12:
                        continue
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
                if not part or part[0].islower():
                    continue
                if part.endswith('.') and len(part.split()) >= 5:
                    continue
                if part and len(part) >= 3 and not _line_is_noise(part) and len(part.split()) <= 10:
                    topics.append(Topic(
                        title=_normalize_title(part)[:160],
                        cues=["objectives_inline"],
                        source={"page": page_num, "line": ln},
                    ))

    return topics


def _extract_topics_multicolumn_table(raw_lines: list[str], page_num: int) -> list[Topic]:
    """
    Multi-column schedule table detected by 3+ space column separators.
    Handles ASTR-style:  'M 8/25        Orientation Meeting        BV,G1-4'
    Operates on RAW (un-normalized) lines to preserve spacing.
    """
    topics: list[Topic] = []
    _WD = r"(?:M|T|W|Th|F|Sa|Su|Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    date_prefix_re = re.compile(
        rf"^\s*(?:\d{{1,2}}\s+)?(?:{_WD}\s+)?(?:\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?|(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        flags=re.IGNORECASE,
    )
    for ln in raw_lines:
        stripped = ln.strip()
        if not date_prefix_re.match(stripped):
            continue
        if not re.search(r"\s{3,}", stripped):
            continue
        parts = re.split(r"\s{3,}", stripped)
        if len(parts) < 2:
            continue
        topic_part = parts[1].strip()
        # Strip trailing textbook codes that weren't separated by 3+ spaces (e.g. "Conduction C4")
        topic_part = re.sub(r"\s+(?:[A-Z]{1,4}\s*\d+)(?:[,\s]+(?:[A-Z]{1,4}\s*\d+|Web\s+\w+))*\s*$", "", topic_part).strip()
        topic_part = re.sub(r"\s+[A-Z]{1,4}(?:,[A-Z]{1,4})*\s*$", "", topic_part).strip()
        topic_part = topic_part.rstrip(",").strip()
        if not topic_part or _line_is_noise(topic_part):
            continue
        if re.search(r"\b(exam|midterm|final|test\s*\d|quiz)\b", topic_part, re.IGNORECASE):
            continue
        if re.search(r"\d+\s*%", topic_part):
            continue
        topics.append(Topic(
            title=_normalize_title(topic_part)[:160],
            cues=["multicolumn_table"],
            source={"page": page_num, "line": ln},
        ))
    return topics


def _extract_topics_numbered_in_section(
    tagged_lines: list[tuple[str, int]],
) -> list[Topic]:
    """
    Numbered list items inside a detected topic/schedule section.
    Accepts cross-page tagged_lines so section state persists across page boundaries.
    Handles both `1. Title` and `1 Title` (space-only) numbering formats.
    """
    topics: list[Topic] = []
    in_topic_section = False
    course_desc_active = False  # True when activated specifically by "course description"
    current_page: int | None = None
    enum_re = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
    enum_space_re = re.compile(r"^\s*(\d{1,2})\s+(.{2,100})$")

    for ln, page_num in tagged_lines:
        # At a page boundary, reset sections NOT rooted in "course description".
        # This prevents schedule-type sections from leaking through to the next page's
        # bibliography/appendix content (e.g. GRK-620, syl54739).
        if page_num != current_page:
            current_page = page_num
            if in_topic_section and not course_desc_active:
                in_topic_section = False

        low = ln.lower().strip()
        if _TOPIC_SECTION_RE.search(low):
            in_topic_section = True
            course_desc_active = "course description" in low
        if _TOPIC_SECTION_END_RE.search(low):
            in_topic_section = False
            course_desc_active = False

        if not in_topic_section:
            continue

        m = enum_re.match(ln)
        use_space_format = False
        if not m:
            m = enum_space_re.match(ln)
            use_space_format = m is not None
        if not m:
            continue

        title = m.group(2).strip()

        # Strip leading "N " prefix from double-numbered lines like "1. 1 Crystal Structure"
        title = re.sub(r"^\d+\s+", "", title).strip()

        # Strip trailing section-header colons ("Introduction:")
        title = title.rstrip(" :")

        # Strip trailing lab-hours credit digit (e.g. "Measurement of DC Voltage 3")
        title = re.sub(r"\s+\d+\s*$", "", title).strip()

        # Skip rows where the captured title is itself a date (date-column table row captured as numbered)
        if re.match(r"^\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", title):
            continue

        # For space-format lines, require title to start uppercase or digit (not prose continuation)
        if use_space_format and title and title[0].islower():
            continue

        # Require minimum meaningful length
        if len(title) < 4:
            continue

        # Skip grading-weight items like "3. Weekly homework (50%): ..."
        if re.search(r"\d+\.?\d*%", title):
            continue
        # Skip bibliography/book references (publisher keywords or Author,Firstname pattern)
        if re.search(
            r"\b(?:Oxford|Cambridge|University Press|Publishing|Monographs|Theological|Eerdmans|Zondervan|Pearson|Macmillan|Routledge|McGraw|edition|ed\.)\b",
            title, re.IGNORECASE
        ):
            continue
        if re.match(r"^[A-Z][a-z]+,\s*(?:[A-Z][a-z]+|[A-Z]\.?)[,\s]", title):
            continue
        # Skip comma-separated assessment-type lists (e.g. "Quiz, MCQ, Assignment, etc")
        _ASSESS_TERMS = ["quiz", "mcq", "exam", "assignment", "homework", "test"]
        if sum(1 for k in _ASSESS_TERMS if k in title.lower()) >= 2:
            continue
        if title and not _line_is_noise(title) and len(title.split()) <= 12:
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
        # Skip URLs
        if re.search(r"https?://", a.name):
            continue
        # Skip lines that are sentences (ends with period + have many words)
        if a.name.endswith(".") and len(a.name.split()) > 8:
            continue
        # Skip clearly noisy patterns
        if re.match(r"^[\W\d\s]+$", a.name):
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
    # Build cross-page tagged lines for strategy 4 (section state must persist across pages)
    all_tagged_lines: list[tuple[str, int]] = []
    for page in pages:
        for ln in page.text.splitlines():
            if ln.strip():
                all_tagged_lines.append((_normalize_line(ln.strip()), page.page_number))

    # Strategy 4 runs first: numbered items inside Course Description sections.
    # Running first gives these topics priority in dedup over objectives-section extractions.
    all_topics: list[Topic] = _extract_topics_numbered_in_section(all_tagged_lines)

    for page in pages:
        raw_lines = [ln for ln in page.text.splitlines() if ln.strip()]
        norm_lines = [_normalize_line(ln.strip()) for ln in page.text.splitlines() if ln.strip()]

        # Strategy 1: Week/Module/Lecture prefix
        all_topics.extend(_extract_topics_week_module(norm_lines, page.page_number))

        # Strategy 2: Date-column table rows (Jan 13   Introduction to Databases)
        all_topics.extend(_extract_topics_date_column(norm_lines, page.page_number, default_year))

        # Strategy 5: Multi-column table (raw lines to preserve 3+ space separators)
        all_topics.extend(_extract_topics_multicolumn_table(raw_lines, page.page_number))

        # Strategy 3: Course Objectives / Learning Outcomes bullet points (lowest priority)
        all_topics.extend(_extract_topics_objectives(norm_lines, page.page_number))

    # Deduplicate by title (case-insensitive), prefer earlier / higher-priority strategies
    seen_titles: dict[str, Topic] = {}
    for t in all_topics:
        key = t.title.strip().lower().rstrip(".,;:")
        # Skip objective-style sentences (learning outcomes that slipped through)
        if _OBJECTIVE_SENT_RE.match(t.title):
            continue
        if key and key not in seen_titles:
            seen_titles[key] = t
    topics_list = list(seen_titles.values())

    # Cap at 60 topics — more indicates a curriculum scheme (multi-subject), not one course
    MAX_TOPICS = 60
    if len(topics_list) > MAX_TOPICS:
        course.constraints_found.append(
            f"Document contains {len(topics_list)} detected topics — may be a multi-subject curriculum "
            f"document. Capped at {MAX_TOPICS}. Use apply_course_corrections to refine."
        )
        topics_list = topics_list[:MAX_TOPICS]
    course.topics = topics_list

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
