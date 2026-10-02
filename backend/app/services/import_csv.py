"""
CSV parsing and the shared report structure for data imports.

This module has no database access. Parsing returns plain rows with
their CSV line numbers so validation messages can point at the row.
"""

import csv
import io

from .. import config

# Allowed answer options (current application semantics).
ANSWER_OPTIONS = ("A", "B", "C", "D")

# Second line of defence; the request itself is limited while it is
# received (security/body_limit.py).
MAX_UPLOAD_BYTES = config.MAX_UPLOAD_BYTES


def clean_text(value: str | None) -> str:
    """Trim and collapse internal whitespace (keeps original case)."""
    return " ".join((value or "").split())


def normalize_name(value: str | None) -> str:
    """Matching key for names: collapsed whitespace, case-insensitive."""
    return clean_text(value).casefold()


class ImportReport:
    """Errors, warnings and a summary for one import attempt."""

    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.summary: dict = {}

    @staticmethod
    def _entry(file, row, field, value, message) -> dict:
        return {
            "file": file,
            "row": row,
            "field": field,
            "value": value,
            "message": message,
        }

    def error(self, file, message, row=None, field=None, value=None):
        self.errors.append(self._entry(file, row, field, value, message))

    def warning(self, file, message, row=None, field=None, value=None):
        self.warnings.append(self._entry(file, row, field, value, message))

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_dict(self, status: str) -> dict:
        return {
            "status": status,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": self.summary,
        }


def parse_csv(
    raw: bytes,
    filename: str,
    required_columns: tuple[str, ...],
    report: ImportReport,
) -> list[tuple[int, dict]]:
    """
    Parse CSV bytes into (line_number, {column: value}) rows.

    Column names are matched case-insensitively and values are trimmed.
    Problems are recorded on the report; if the file is unusable
    (unreadable, empty, missing a required column) no rows are returned.
    """

    if len(raw) > MAX_UPLOAD_BYTES:
        report.error(
            filename,
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
        return []

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.error(
            filename,
            "File is not valid UTF-8 text. Save it as CSV (UTF-8).",
        )
        return []

    reader = csv.reader(io.StringIO(text))

    try:
        header = next(reader, None)

        if header is None or not any(cell.strip() for cell in header):
            report.error(filename, "File is empty or has no header row.")
            return []

        columns = [cell.strip().lower() for cell in header]

        duplicated = sorted({c for c in columns if columns.count(c) > 1})

        for column in duplicated:
            report.error(
                filename,
                f"Column '{column}' appears more than once.",
                row=1,
                field=column,
            )

        missing = [c for c in required_columns if c not in columns]

        for column in missing:
            report.error(
                filename,
                f"Required column '{column}' is missing.",
                row=1,
                field=column,
            )

        if missing or duplicated:
            return []

        rows: list[tuple[int, dict]] = []

        for values in reader:
            line = reader.line_num

            if not any(cell.strip() for cell in values):
                continue

            if len(values) != len(columns):
                report.error(
                    filename,
                    f"Row has {len(values)} values but the header has "
                    f"{len(columns)} columns.",
                    row=line,
                )
                continue

            rows.append(
                (
                    line,
                    {
                        column: value.strip()
                        for column, value in zip(columns, values)
                    },
                )
            )

    except csv.Error as exc:
        report.error(filename, f"Malformed CSV: {exc}")
        return []

    return rows
