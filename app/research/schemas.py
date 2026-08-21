"""
Pydantic schemas for research output validation.
Every field from the LLM prompt is validated here.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Fact(BaseModel):
    fact: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class Claim(BaseModel):
    claim: str
    source: str = "unknown"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class Statistic(BaseModel):
    stat: str
    source: str = "unknown"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class DateEvent(BaseModel):
    event: str
    date: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class Person(BaseModel):
    name: str
    role: str = ""


class Location(BaseModel):
    name: str
    relevance: str = ""


class UncertainClaim(BaseModel):
    claim: str
    note: str = ""


class ResearchResult(BaseModel):
    topic: str
    summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    statistics: list[Statistic] = Field(default_factory=list)
    dates: list[DateEvent] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    uncertain_claims: list[UncertainClaim] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    suggested_sections: list[str] = Field(default_factory=list)

    @field_validator("facts", "claims", "statistics", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        """Accept both list and None gracefully."""
        if v is None:
            return []
        return v
