"""
Our own representation of what the OMR step recognised.

Nothing outside the omr package sees OMRChecker's CSV. The recogniser's
output is converted into these types by normalization.py, checked by
validation.py, and only then turned into ordinary answer records.

The recognition states are kept apart on purpose. In particular a
question that was left blank (BLANK) is not the same thing as one with
two or more bubbles marked (MULTI_MARK), even though the current
evaluation scores both as no answer.
"""

from dataclasses import dataclass, field
from enum import Enum


class RecognitionStatus(str, Enum):
    RECOGNIZED = "recognized"          # exactly one option marked
    BLANK = "blank"                    # no bubble marked
    MULTI_MARK = "multi_mark"          # two or more options marked
    INVALID = "invalid"                # a value that is not an option
    REVIEW_REQUIRED = "review_required"  # no usable value was produced


# States that must not be turned into a final answer without a person
# deciding what the student meant.
NEEDS_REVIEW = frozenset(
    {
        RecognitionStatus.MULTI_MARK,
        RecognitionStatus.INVALID,
        RecognitionStatus.REVIEW_REQUIRED,
    }
)


@dataclass(frozen=True)
class OMRAnswer:
    question_number: int
    # Exactly what the recogniser returned (None when it returned nothing
    # for this field at all). Kept so a reviewer can see it.
    raw_value: str | None
    # "A".."D" for RECOGNIZED, otherwise None. Never a guess.
    normalized_answer: str | None
    status: RecognitionStatus

    @property
    def needs_review(self) -> bool:
        return self.status in NEEDS_REVIEW


@dataclass
class OMRSheet:
    """One recognised answer sheet (one image)."""

    index: int                    # position in the upload, starting at 1
    display_name: str             # safe label for messages, never a path
    # The roll number as read, and the valid form of it (None if unusable).
    roll_raw: str | None = None
    roll_number: str | None = None
    # "roll_missing" or "roll_malformed" when roll_number is None.
    roll_problem: str | None = None
    answers: list[OMRAnswer] = field(default_factory=list)
    # Template fields that are not part of the selected test: reported,
    # never imported.
    ignored_fields: list[str] = field(default_factory=list)
    ignored_marked: int = 0
    # Set when the recogniser could not read the image at all.
    unreadable: bool = False


@dataclass(frozen=True)
class Issue:
    """A validation error or warning, in our own stable form."""

    code: str
    message: str
    sheet: str | None = None
    roll_number: str | None = None
    question_number: int | None = None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "sheet": self.sheet,
            "roll_number": self.roll_number,
            "question_number": self.question_number,
        }
