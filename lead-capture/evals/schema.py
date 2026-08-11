"""
Output schema for the /api/triage endpoint.

This is the contract. Whatever the model says, it either matches this shape
exactly or it never leaves the server.
"""
from enum import Enum
from pydantic import BaseModel, Field, ValidationError


class Category(str, Enum):
    sales = "sales"
    support = "support"
    billing = "billing"
    partnership = "partnership"
    spam = "spam"
    other = "other"


class Urgency(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Team(str, Enum):
    sales = "sales"
    support = "support"
    billing = "billing"
    general = "general"


class TriageResult(BaseModel):
    category: Category
    urgency: Urgency
    suggested_team: Team
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


__all__ = ["TriageResult", "Category", "Urgency", "Team", "ValidationError"]
