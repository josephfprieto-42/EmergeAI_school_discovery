from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["public", "charter", "private", "early_childhood"]


class Preferences(BaseModel):
    """Structured parent preferences extracted from conversation."""

    location_text: Optional[str] = Field(None, description="Address, neighborhood, ZIP, or landmark the family lives near")
    child_grade: Optional[int] = Field(None, ge=-2, le=12, description="-2 infant/toddler, -1 PK, 0 K, 1-12")
    child_grades: list[int] = Field(default_factory=list, description="All children's grades if multiple")
    categories: list[Category] = Field(default_factory=list, description="Empty means any")
    radius_miles: Optional[float] = Field(None, gt=0, le=40)
    priorities: list[Literal["academics", "distance", "small_school", "large_school", "diversity", "stem", "arts", "language", "magnet", "religious", "montessori", "special_needs", "gifted", "affordability", "early_childhood"]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, description="Program or name keywords to match, e.g. 'Montessori', 'bilingual', 'IB'")
    min_fl_grade: Optional[Literal["A", "B", "C"]] = None
    notes: Optional[str] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RecommendRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    preferences: Optional[Preferences] = None
    origin: Optional[tuple[float, float]] = None
    limit: int = Field(6, ge=1, le=12)


class SchoolExplanation(BaseModel):
    school_id: int
    why: str
    tradeoffs: str


class RecommendResponse(BaseModel):
    preferences: Preferences
    origin: Optional[tuple[float, float]]
    origin_label: Optional[str]
    summary: str
    follow_up: Optional[str] = None
    results: list[dict[str, Any]]
    explanations: list[SchoolExplanation]
    candidates_considered: int
    llm_used: bool


class CompareRequest(BaseModel):
    ids: list[int] = Field(..., min_length=2, max_length=4)
    origin: Optional[tuple[float, float]] = None
    preferences: Optional[Preferences] = None


class CompareResponse(BaseModel):
    schools: list[dict[str, Any]]
    summary: str
    tradeoffs: list[str]
    llm_used: bool
