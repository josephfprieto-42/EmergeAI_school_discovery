from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Category = Literal["public", "charter", "private", "early_childhood"]
Priority = Literal[
    "academics",
    "distance",
    "small_school",
    "large_school",
    "diversity",
    "stem",
    "arts",
    "language",
    "magnet",
    "religious",
    "montessori",
    "special_needs",
    "gifted",
    "affordability",
    "early_childhood",
]
ListOp = Literal["add", "remove", "replace", "clear"]
ClearField = Literal[
    "location_text",
    "radius_miles",
    "min_fl_grade",
    "notes",
    "categories",
    "priorities",
    "keywords",
    "children",
    "household",
    "prefer_near",
]
PreferNear = Literal["home", "work", "route"]
ActivityInterest = Literal["arts", "stem", "language", "sports"]
# How far the conversation has come: nothing to rank on yet, one anchor known, or both.
Stage = Literal["discovering", "preliminary", "refined"]
# Things the advisor may ask about, one per turn, never twice per session.
Topic = Literal["children", "location", "categories", "priorities", "radius", "work", "min_fl_grade"]


class Child(BaseModel):
    grade: int = Field(..., ge=-2, le=12, description="-2 infant/toddler, -1 PK, 0 K, 1-12")
    label: Optional[str] = None


class ActivityPlace(BaseModel):
    """One recurring activity. The place, when given, joins the weekly route."""

    label: str = Field(..., max_length=80)
    location_text: Optional[str] = Field(None, max_length=200)
    child_label: Optional[str] = Field(None, max_length=80)


class Household(BaseModel):
    """Facts about the family that outlive one search: where the parents work,
    when they need pickup covered, and what the children already do each week."""

    work_location_text: Optional[str] = Field(None, max_length=200)
    work_schedule_text: Optional[str] = Field(None, max_length=200)
    needs_after_school_care: Optional[bool] = None
    activities: list[ActivityPlace] = Field(default_factory=list)
    activity_interests: list[ActivityInterest] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.work_location_text
            or self.work_schedule_text
            or self.needs_after_school_care is not None
            or self.activities
            or self.activity_interests
        )


HouseholdClearField = Literal[
    "work_location_text",
    "work_schedule_text",
    "needs_after_school_care",
    "activities",
    "activity_interests",
]


class Preferences(BaseModel):
    """Structured parent preferences extracted from conversation.

    `children` is the source of truth. `child_grade` (first child) and
    `child_grades` are derived so existing callers keep working.
    """

    location_text: Optional[str] = Field(None, description="Address, neighborhood, ZIP, or landmark the family lives near")
    child_grade: Optional[int] = Field(None, ge=-2, le=12, description="-2 infant/toddler, -1 PK, 0 K, 1-12")
    child_grades: list[int] = Field(default_factory=list, description="All children's grades if multiple")
    children: list[Child] = Field(default_factory=list, description="One entry per child")
    categories: list[Category] = Field(default_factory=list, description="Empty means any")
    radius_miles: Optional[float] = Field(None, gt=0, le=40)
    priorities: list[Priority] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, description="Program or name keywords to match, e.g. 'Montessori', 'bilingual', 'IB'")
    min_fl_grade: Optional[Literal["A", "B", "C"]] = None
    notes: Optional[str] = None
    prefer_near: Optional[PreferNear] = Field(None, description="Which point distance is measured from: home, work, or the commute route")

    @model_validator(mode="before")
    @classmethod
    def _hydrate_children(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        children = data.get("children") or []
        grades = list(data.get("child_grades") or [])
        grade = data.get("child_grade")
        if not children and (grades or grade is not None):
            if grade is not None and grade not in grades:
                grades.insert(0, grade)
            data = {**data, "children": [{"grade": g} for g in grades]}
        return data

    @model_validator(mode="after")
    def _derive_grades(self) -> Preferences:
        if self.children:
            self.child_grades = [c.grade for c in self.children]
            self.child_grade = self.children[0].grade
        else:
            self.child_grades = []
            self.child_grade = None
        return self


class ListUpdate(BaseModel):
    """Change one list field. Omitted updates leave the stored list alone."""

    op: ListOp
    values: list[str] = Field(default_factory=list)


class ChildUpdate(BaseModel):
    op: ListOp
    children: list[Child] = Field(default_factory=list)


class ActivityUpdate(BaseModel):
    op: ListOp
    activities: list[ActivityPlace] = Field(default_factory=list)


class HouseholdPatch(BaseModel):
    """Delta for the household. Absent fields were not mentioned."""

    work_location_text: Optional[str] = Field(None, max_length=200)
    work_schedule_text: Optional[str] = Field(None, max_length=200)
    needs_after_school_care: Optional[bool] = None
    activities: Optional[ActivityUpdate] = None
    activity_interests: Optional[ListUpdate] = None
    clear_fields: list[HouseholdClearField] = Field(default_factory=list)


class PreferencePatch(BaseModel):
    """Delta for one turn. Fields that are absent were not mentioned."""

    reset: bool = False
    location_text: Optional[str] = None
    radius_miles: Optional[float] = Field(None, gt=0, le=40)
    min_fl_grade: Optional[Literal["A", "B", "C"]] = None
    notes: Optional[str] = None
    prefer_near: Optional[PreferNear] = None
    clear_fields: list[ClearField] = Field(default_factory=list)
    categories: Optional[ListUpdate] = None
    priorities: Optional[ListUpdate] = None
    keywords: Optional[ListUpdate] = None
    children: Optional[ChildUpdate] = None
    household: Optional[HouseholdPatch] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RecommendRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    # Accepted so older clients do not 422. The server stores history and
    # preferences itself; these copies are not the source of truth.
    history: list[ChatMessage] = Field(default_factory=list)
    preferences: Optional[Preferences] = None
    origin: Optional[tuple[float, float]] = None
    origin_label: Optional[str] = Field(None, max_length=200)
    # Used for this ranking only when the conversation has not set a radius.
    radius_miles: Optional[float] = Field(None, gt=0, le=40)
    # Precise coordinates are written to the session only when this is true.
    remember_location: bool = False
    # Household profile that outlives this chat. A new session adopts it.
    household_id: Optional[str] = Field(None, max_length=64)
    limit: int = Field(6, ge=1, le=12)


class SchoolExplanation(BaseModel):
    school_id: int
    why: str
    tradeoffs: str


class ChildGroup(BaseModel):
    grade: int
    label: Optional[str] = None
    results: list[dict[str, Any]]
    candidates_considered: int


class ActivityPointOut(BaseModel):
    label: str
    lat: float
    lon: float


class QuestionOption(BaseModel):
    """A tap-to-answer chip. `message` is sent as if the parent typed it."""

    label: str
    message: str


class Question(BaseModel):
    topic: Topic
    text: str
    options: list[QuestionOption] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    session_id: str
    household_id: Optional[str] = None
    household: Optional[Household] = None
    preferences: Preferences
    origin: Optional[tuple[float, float]]
    origin_label: Optional[str]
    work: Optional[tuple[float, float]] = None
    work_label: Optional[str] = None
    activity_points: list[ActivityPointOut] = Field(default_factory=list)
    summary: str
    # Same text as question.text; kept so stored transcripts and older clients still work.
    follow_up: Optional[str] = None
    stage: Stage = "refined"
    changes: list[str] = Field(default_factory=list)
    question: Optional[Question] = None
    results: list[dict[str, Any]]
    groups: Optional[list[ChildGroup]] = None
    explanations: list[SchoolExplanation]
    candidates_considered: int
    llm_used: bool


class SessionState(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    preferences: Preferences
    origin: Optional[tuple[float, float]] = None
    origin_label: Optional[str] = None
    recommendation: Optional[RecommendResponse] = None
    household_id: Optional[str] = None
    household: Optional[Household] = None
    asked: list[Topic] = Field(default_factory=list)


class HouseholdState(BaseModel):
    household_id: str
    household: Household
    work: Optional[tuple[float, float]] = None
    work_label: Optional[str] = None

