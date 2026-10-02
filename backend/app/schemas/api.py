from typing import Literal
from datetime import date

from pydantic import BaseModel, Field


class InstituteCreate(BaseModel):
    name: str = Field(min_length=1)


class BatchCreate(BaseModel):
    institute_id: int
    name: str = Field(min_length=1)


class StudentCreate(BaseModel):
    batch_id: int
    roll_number: str = Field(min_length=1)
    name: str = Field(min_length=1)


class TestCreate(BaseModel):
    batch_id: int
    name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    test_date: date
    marks_correct: float = 4.0
    marks_wrong: float = -1.0
    marks_blank: float = 0.0


class QuestionCreate(BaseModel):
    test_id: int
    question_number: int
    subject: str
    chapter_id: int | None = None
    topic_id: int | None = None
    correct_answer: str = Field(min_length=1)
    difficulty: str = "medium"


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
