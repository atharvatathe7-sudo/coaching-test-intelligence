"""
Synthetic OMR answer sheets for tests, generated on the fly.

Nothing here is a real scan and no upstream or community sample images
are used. Sheets are drawn by backend/app/omr/sheet_design.py from the
template's own layout file, so the pictures always match the template.
"""

import cv2
import numpy as np

from backend.app.omr import sheet_design
from backend.app.omr.template import get_template


def render_sheet(roll: str, answers: dict[int, str], template_id=None, seed=0) -> bytes:
    """
    A PNG of a filled-in sheet, drawn flat (no camera effects).

    `roll` has one digit per roll column. `answers` maps question number
    to "" (blank), "A".."D", or several letters ("AB") for a multi-mark.
    Questions not in `answers` are left blank.
    """
    template = get_template(template_id)
    return sheet_design.to_png(sheet_design.render_sheet(template, roll, answers, seed=seed))


def photograph(
    roll: str,
    answers: dict[int, str],
    template_id="prototype-marked-60q",
    seed=0,
    rotation=2.5,
    tilt=0.02,
    scale=0.88,
    jpeg=True,
) -> bytes:
    """
    A marked sheet as a phone camera might see it: rotated, tilted,
    smaller than the frame and off-centre, on a darker background, with
    noise, blur and (optionally) JPEG compression. Deterministic per seed.
    """
    template = get_template(template_id)
    sheet = sheet_design.render_sheet(template, roll, answers, labels=True, seed=seed)
    rng = np.random.default_rng(seed + 1000)
    h, w = sheet.shape
    canvas_w, canvas_h = int(w * 1.25), int(h * 1.2)

    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    centre = np.float32([w / 2, h / 2])
    angle = np.deg2rad(rng.uniform(-rotation, rotation))
    rot = np.float32([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    moved = (corners - centre) @ rot.T * scale
    moved += rng.uniform(-tilt, tilt, moved.shape).astype(np.float32) * [w, h]
    moved += np.float32([canvas_w / 2, canvas_h / 2]) + rng.uniform(-0.03, 0.03, 2).astype(np.float32) * [w, h]

    matrix = cv2.getPerspectiveTransform(corners, moved.astype(np.float32))
    photo = cv2.warpPerspective(
        sheet, matrix, (canvas_w, canvas_h), borderMode=cv2.BORDER_CONSTANT, borderValue=95
    )
    photo = photo.astype(np.float32) + rng.normal(0, 4, photo.shape)
    photo = cv2.GaussianBlur(np.clip(photo, 0, 255).astype(np.uint8), (3, 3), 0)

    ok, encoded = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 88]) if jpeg \
        else cv2.imencode(".png", photo)
    assert ok
    return encoded.tobytes()
