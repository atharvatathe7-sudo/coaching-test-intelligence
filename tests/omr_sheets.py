"""
Synthetic OMR answer sheets for tests, generated on the fly.

Nothing here is a real scan and no upstream sample images are used. Bubble
positions are computed from the template's own layout file (the one
OMRChecker reads), so the images always match the template.
"""

import json

import cv2
import numpy as np

from backend.app.omr.template import expand_labels, get_template

_TYPES = {
    "QTYPE_INT": ("0123456789", "vertical"),
    "QTYPE_MCQ4": ("ABCD", "horizontal"),
}


def _bubble_positions(template):
    """{label: {value: (x, y)}} for every field in the layout."""
    layout = json.loads(template.layout_path.read_text())
    positions = {}

    for block in layout["fieldBlocks"].values():
        values, direction = _TYPES[block["fieldType"]]
        ox, oy = block["origin"]
        for i, label in enumerate(expand_labels(block["fieldLabels"])):
            positions[label] = {}
            for j, value in enumerate(values):
                if direction == "horizontal":
                    xy = (ox + j * block["bubblesGap"], oy + i * block["labelsGap"])
                else:
                    xy = (ox + i * block["labelsGap"], oy + j * block["bubblesGap"])
                positions[label][value] = xy

    return layout, positions


def render_sheet(roll: str, answers: dict[int, str], template_id=None, seed=0) -> bytes:
    """
    A PNG of a filled-in sheet.

    `roll` has one digit per roll column. `answers` maps question number to
    "" (blank), "A".."D", or several letters ("AB") for a multi-mark.
    Questions not in `answers` are left blank.
    """

    template = get_template(template_id)
    layout, positions = _bubble_positions(template)
    width, height = layout["pageDimensions"]
    box = layout["bubbleDimensions"][0]
    rng = np.random.default_rng(seed)

    image = np.full((height, width), 245, np.uint8)

    def centre(xy):
        return int(xy[0] + box / 2), int(xy[1] + box / 2)

    for values in positions.values():
        for xy in values.values():
            cv2.circle(image, centre(xy), 12, 150, 2)

    def mark(label, value):
        cv2.circle(image, centre(positions[label][value]), 11, 40, -1)

    roll_labels = expand_labels(json.loads(
        template.layout_path.read_text())["customLabels"][template.roll_field])
    assert len(roll) == len(roll_labels)
    for label, digit in zip(roll_labels, roll):
        mark(label, digit)

    for number, letters in answers.items():
        for letter in letters:
            mark(template.column_for(number), letter)

    # Mild sensor noise and uneven lighting.
    shade = np.tile(np.linspace(0.9, 1.0, width, dtype=np.float32), (height, 1))
    noisy = image.astype(np.float32) * shade + rng.normal(0, 5, image.shape)
    ok, encoded = cv2.imencode(".png", np.clip(noisy, 0, 255).astype(np.uint8))
    assert ok
    return encoded.tobytes()
