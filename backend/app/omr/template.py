"""
OMR sheet templates.

A template has two parts in one folder under omr/templates/:

  template.json   the layout file OMRChecker reads (where the bubbles are)
  manifest.json   our description of it: which fields are questions (a
                  range, or an explicit list of numbers), which is the roll
                  number, the answer options, a version

Any other files in the folder (for example an alignment-marker image the
layout refers to) are copied next to template.json for OMRChecker.

The manifest is what the rest of the application uses; no question
positions or field names are written into business logic. When a template
is loaded the manifest is checked against template.json, so a layout edit
that drops or renames a field fails loudly instead of silently reading
nothing.

Templates are controlled files shipped with the application. There is no
template editor.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE_ID = "prototype-60q"

_RANGE = re.compile(r"^(?P<prefix>.*?)(?P<start>\d+)\.\.(?P<end>\d+)$")


class TemplateError(ValueError):
    """A template is missing or inconsistent."""


def expand_labels(labels) -> list[str]:
    """OMRChecker label ranges ("q1..4") -> ["q1", "q2", "q3", "q4"]."""
    expanded = []

    for label in labels:
        match = _RANGE.match(label)

        if match:
            start, end = int(match["start"]), int(match["end"])
            expanded += [f"{match['prefix']}{n}" for n in range(start, end + 1)]
        else:
            expanded.append(label)

    return expanded


@dataclass(frozen=True)
class OMRTemplate:
    id: str
    version: int
    description: str
    directory: Path
    options: tuple[str, ...]
    roll_field: str
    roll_digits: int
    question_numbers: tuple[int, ...]
    question_label: str            # e.g. "q{n}"

    @property
    def layout_path(self) -> Path:
        return self.directory / "template.json"

    def column_for(self, question_number: int) -> str:
        return self.question_label.format(n=question_number)

    @property
    def question_columns(self) -> dict[str, int]:
        return {self.column_for(n): n for n in self.question_numbers}


def load_template(directory: Path) -> OMRTemplate:
    directory = Path(directory)

    try:
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        layout = json.loads((directory / "template.json").read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise TemplateError(f"template files unreadable in {directory.name}") from error

    try:
        questions = manifest["questions"]
        if "numbers" in questions:
            # an explicit list, for sheets whose multiple-choice questions
            # are not one unbroken range
            numbers = tuple(int(n) for n in questions["numbers"])
        else:
            numbers = tuple(range(int(questions["first"]), int(questions["last"]) + 1))
        template = OMRTemplate(
            id=str(manifest["id"]),
            version=int(manifest["version"]),
            description=str(manifest.get("description", "")),
            directory=directory,
            options=tuple(manifest["options"]),
            roll_field=str(manifest["roll"]["field"]),
            roll_digits=int(manifest["roll"]["digits"]),
            question_numbers=numbers,
            question_label=str(questions["label"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TemplateError(f"manifest incomplete in {directory.name}") from error

    # The manifest must agree with the layout OMRChecker will read.
    block_labels = {
        label
        for block in layout.get("fieldBlocks", {}).values()
        for label in expand_labels(block.get("fieldLabels", []))
    }
    custom = layout.get("customLabels", {})

    missing = [c for c in template.question_columns if c not in block_labels]
    if missing:
        raise TemplateError(
            f"template {template.id}: layout has no field for {missing[0]}"
        )

    if not numbers or len(set(numbers)) != len(numbers):
        raise TemplateError(f"template {template.id}: bad question range")

    parts = expand_labels(custom.get(template.roll_field, []))
    if len(parts) != template.roll_digits or any(p not in block_labels for p in parts):
        raise TemplateError(
            f"template {template.id}: roll field does not match the layout"
        )

    if not template.options or any(len(o) != 1 for o in template.options):
        raise TemplateError(f"template {template.id}: bad answer options")

    return template


def list_templates() -> list[OMRTemplate]:
    return [
        load_template(path)
        for path in sorted(TEMPLATES_DIR.iterdir())
        if (path / "manifest.json").is_file()
    ]


def get_template(template_id: str | None) -> OMRTemplate:
    wanted = (template_id or "").strip() or DEFAULT_TEMPLATE_ID

    for template in list_templates():
        if template.id == wanted:
            return template

    raise TemplateError("unknown template")
