"""
Turning validated OMR answers into the rows the existing answer import
reads (roll_number, question_number, answer).
"""

import csv
import io

from .models import OMRSheet, RecognitionStatus
from .validation import find_duplicate_answers


def answer_rows(sheets: list[OMRSheet]) -> list[tuple[str, int, str]]:
    """
    Final answer rows (roll, question, answer) for sheets that have no
    unresolved answers. Raises if a sheet still has one, or if a
    (roll, question) pair would appear twice, so ambiguity can never be
    imported by accident.
    """

    rows = []

    for sheet in sheets:
        for answer in sheet.answers:
            if answer.status is RecognitionStatus.RECOGNIZED:
                value = answer.normalized_answer
            elif answer.status is RecognitionStatus.BLANK:
                value = ""
            else:
                raise ValueError("an unresolved answer cannot be imported")
            rows.append((sheet.roll_number, answer.question_number, value))

    if find_duplicate_answers(rows):
        raise ValueError("duplicate roll number and question")

    return rows


def answers_csv(rows: list[tuple[str, int, str]]) -> bytes:
    """The rows in the format the existing answer import reads."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["roll_number", "question_number", "answer"])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")
