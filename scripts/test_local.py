from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from syllabus_mcp.server import (
    ExportPlanInput,
    GenerateStudyPlanInput,
    ParseSyllabusInput,
    WeightTopicsInput,
    export_plan,
    generate_study_plan,
    parse_syllabus,
    weight_topics,
)
from syllabus_mcp.models import StudyPreferences


def main() -> None:
    parsed = parse_syllabus(
        ParseSyllabusInput(
            content_type="text",
            timezone="UTC",
            content="""
CS101
Midterm Exam: March 30, 2026
Final Exam: May 20, 2026
Week 1: Intro to Python
Week 2: Data structures
Week 3: Testing
Week 4: Algorithms
""".strip(),
        )
    )
    weighted = weight_topics(WeightTopicsInput(course=parsed.course))
    plan_out = generate_study_plan(
        GenerateStudyPlanInput(
            course=weighted.course,
            preferences=StudyPreferences(course_start_date=date(2026, 3, 1), timezone="UTC", days_off=["sun"]),
        )
    )
    ics_out = export_plan(ExportPlanInput(plan=plan_out.plan, format="ics"))

    print("Course:", parsed.course.course_title)
    print("Assessments:", [(a.name, str(a.scheduled_date)) for a in parsed.course.assessments])
    print("Topics:", [t.title for t in parsed.course.topics])
    print("Plan sessions:", len(plan_out.plan.sessions))
    print("ICS preview:")
    print("\n".join(ics_out.result["ics"].splitlines()[:18]))


if __name__ == "__main__":
    main()

