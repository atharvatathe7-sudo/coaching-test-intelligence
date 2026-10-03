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
from functools import lru_cache
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
    # For sheets with alignment markers: how far (pixels, at design scale)
    # the marker centres are from the sheet edge, and the marker image
    # file in the template folder. 0 / None for a flat, unmarked sheet.
    sheet_margin: int = 0
    marker_file: str | None = None

    @property
    def layout_path(self) -> Path:
        return self.directory / "template.json"

    def column_for(self, question_number: int) -> str:
        return self.question_label.format(n=question_number)

    @property
    def question_columns(self) -> dict[str, int]:
        return {self.column_for(n): n for n in self.question_numbers}

    def question_region(self, question_number: int) -> dict | None:
        """
        Where a question's bubbles are, in the coordinates of the aligned
        sheet image (the template's page size), with one row of context
        above and below. Used to crop the image for review. None if the
        layout has no such question.
        """
        return _question_region(self.layout_path, self.column_for(question_number), len(self.options))


@lru_cache(maxsize=32)
def _layout(path: Path) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def _question_region(layout_path: Path, column: str, option_count: int) -> dict | None:
    layout = _layout(layout_path)
    page_w, page_h = layout["pageDimensions"]
    bubble_w, bubble_h = layout["bubbleDimensions"]

    for block in layout["fieldBlocks"].values():
        labels = expand_labels(block.get("fieldLabels", []))

        if column not in labels:
            continue

        index = labels.index(column)
        origin_x, origin_y = block["origin"]
        bubbles_gap, labels_gap = block["bubblesGap"], block["labelsGap"]
        horizontal = block.get("direction", "horizontal") == "horizontal"

        if horizontal:
            x = origin_x
            y = origin_y + index * labels_gap
            width = (option_count - 1) * bubbles_gap + bubble_w
            height = bubble_h
            pad_x, pad_y = bubble_w, labels_gap
        else:
            x = origin_x + index * labels_gap
            y = origin_y
            width = bubble_w
            height = (option_count - 1) * bubbles_gap + bubble_h
            pad_x, pad_y = labels_gap, bubble_h

        left, top = max(0, x - pad_x), max(0, y - pad_y)
        right, bottom = min(page_w, x + width + pad_x), min(page_h, y + height + pad_y)

        return {
            "x": left, "y": top, "width": right - left, "height": bottom - top,
            "page_width": page_w, "page_height": page_h,
        }

    return None


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
            sheet_margin=int(manifest.get("sheet", {}).get("margin", 0)),
            marker_file=manifest.get("sheet", {}).get("marker"),
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

    if template.marker_file and not (directory / template.marker_file).is_file():
        raise TemplateError(f"template {template.id}: marker image missing")

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
