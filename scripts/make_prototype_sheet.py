"""
Write a blank, printable prototype answer sheet (a PNG).

    python scripts/make_prototype_sheet.py [--template prototype-marked-60q] [--out sheet.png]

The picture is generated from the template's own layout, so printing it
gives a sheet whose bubbles are exactly where the OMR reader looks. Print
it at a size that fits an A4 page without cropping or distorting it (the
four corner markers must stay visible and square), fill bubbles with a
dark pen or pencil, and photograph or scan it flat and well lit.

This is a project-owned PROTOTYPE sheet, not any institute's real answer
sheet.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.omr import sheet_design  # noqa: E402
from backend.app.omr.template import TemplateError, get_template  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--template", default="prototype-marked-60q")
    parser.add_argument("--out", default="prototype_sheet.png")
    args = parser.parse_args()

    try:
        template = get_template(args.template)
    except TemplateError:
        raise SystemExit(f"Unknown template: {args.template}")

    image = sheet_design.render_sheet(
        template, "", {}, labels=True, shading=False, noise_sigma=0.0
    )
    Path(args.out).write_bytes(sheet_design.to_png(image))
    print(f"Wrote {args.out} ({image.shape[1]} x {image.shape[0]} px) for {template.id} v{template.version}")


if __name__ == "__main__":
    main()
