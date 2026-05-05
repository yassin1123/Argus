from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    query: str
    title: str = ""
    report_mode: str = "general"


class IntakeAnswerItem(BaseModel):
    id: str
    answer: str = ""


class IntakeSubmitRequest(BaseModel):
    answers: list[IntakeAnswerItem] = Field(default_factory=list)


class SessionRow(BaseModel):
    id: UUID
    title: str
    query: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
