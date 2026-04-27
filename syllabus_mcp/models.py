from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Confidence(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    reason: str


class AssessmentType(str, Enum):
    exam = "exam"
    quiz = "quiz"
    project = "project"
    assignment = "assignment"
    presentation = "presentation"
    other = "other"


class Assessment(BaseModel):
    name: str
    type: AssessmentType = AssessmentType.other
    scheduled_date: date | None = None
    weight_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence: Confidence | None = None
    source: dict[str, Any] | None = None


class Topic(BaseModel):
    title: str
    module: str | None = None
    week: int | None = Field(default=None, ge=1)
    pages: str | None = None
    cues: list[str] = Field(default_factory=list)
    weight_score: float | None = None
    weight_rationale: list[str] = Field(default_factory=list)
    source: dict[str, Any] | None = None


class CourseModel(BaseModel):
    course_title: str | None = None
    instructor: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = None
    assessments: list[Assessment] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    constraints_found: list[str] = Field(default_factory=list)
    extracted_text_summary: str | None = None
    confidences: dict[str, Confidence] = Field(default_factory=dict)


class IntensityPreset(str, Enum):
    light = "light"
    standard = "standard"
    intense = "intense"


class StudyPreferences(BaseModel):
    course_start_date: date | None = None
    timezone: str = "UTC"
    hours_per_day: float = Field(default=1.5, ge=0.25, le=12.0)
    days_off: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(
        default_factory=list
    )
    session_minutes: int = Field(default=60, ge=15, le=180)
    intensity: IntensityPreset = IntensityPreset.standard
    max_sessions_per_day: int = Field(default=3, ge=1, le=10)
    allow_catch_up: bool = True


class SessionType(str, Enum):
    learn = "learn"
    practice = "practice"
    review = "review"
    mock_exam = "mock_exam"
    buffer = "buffer"


class StudySession(BaseModel):
    session_date: date
    topic_title: str
    session_type: SessionType
    estimated_minutes: int = Field(ge=5, le=600)
    sr_step: int | None = None
    rationale: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class StudyPlan(BaseModel):
    course_title: str | None = None
    timezone: str = "UTC"
    start_date: date
    end_date: date
    sessions: list[StudySession]
    meta: dict[str, Any] = Field(default_factory=dict)

