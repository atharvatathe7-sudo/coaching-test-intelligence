from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class BatchCreate(BaseModel):
    # The institute comes from the signed-in user, never from the client.
    name: str = Field(min_length=1, max_length=200)


ActionType = Literal["review", "reteach", "revise", "monitor", "no_action"]
ActionStatus = Literal["planned", "completed"]


class TeacherActionCreate(BaseModel):
    test_id: int
    question_number: int | None = None
    chapter_id: int | None = None
    topic_id: int | None = None
    finding_type: str | None = Field(default=None, max_length=50)
    finding_title: str | None = Field(default=None, max_length=255)
    finding_reason: str | None = None
    action_type: ActionType
    status: ActionStatus = "planned"
    note: str | None = None


class TeacherActionUpdate(BaseModel):
    action_type: ActionType | None = None
    status: ActionStatus | None = None
    note: str | None = None


class TestUpdate(BaseModel):
    """Editable test metadata. The batch cannot be changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    test_date: date | None = None
    marks_correct: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    marks_wrong: float | None = Field(default=None, allow_inf_nan=False)
    marks_blank: float | None = Field(default=None, allow_inf_nan=False)


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    roll_number: str | None = Field(default=None, min_length=1, max_length=100)
