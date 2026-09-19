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
