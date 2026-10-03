"""
Checks on uploaded OMR images.

Only the file header is read here: the web application never decodes
image pixels. That is left to the OMR child process, so a damaged or
hostile image cannot reach a native image decoder inside the server.

The uploaded filename is used for two things only: its extension is
checked, and a cleaned-up copy is shown in messages. It is never used as
a filesystem path (see checker.py, which names files itself).
"""

import re
import struct
from dataclasses import dataclass

from .. import config

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ImageRejected(ValueError):
    """The upload is not an acceptable image; the message is safe to show."""


@dataclass(frozen=True)
class ImageInfo:
    kind: str       # "png" or "jpeg"
    width: int
    height: int

    @property
    def extension(self) -> str:
        return ".png" if self.kind == "png" else ".jpg"


def safe_display_name(filename: str | None, index: int) -> str:
    """A label for messages: no directories, no control characters."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()

    if not name:
        return f"sheet {index}"

    return name[:80]


def declared_extension(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def _png_size(data: bytes) -> tuple[int, int]:
    # signature, then the first chunk must be IHDR (length 13)
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ImageRejected("The PNG file is damaged.")

    return struct.unpack(">II", data[16:24])


def _jpeg_size(data: bytes) -> tuple[int, int]:
    position = 2
    length = len(data)

    while position + 4 <= length:
        if data[position] != 0xFF:
            position += 1
            continue

        marker = data[position + 1]

        if marker == 0xFF:            # fill byte
            position += 1
            continue

        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            position += 2             # markers without a length
            continue

        if marker == 0xD9:            # end of image before any frame header
            break

        segment = struct.unpack(">H", data[position + 2:position + 4])[0]

        # Start-of-frame markers carry the picture size.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if position + 9 > length:
                break
            height, width = struct.unpack(">HH", data[position + 5:position + 9])
            return width, height

        position += 2 + segment

    raise ImageRejected("The JPEG file is damaged.")


def inspect_image(data: bytes, filename: str | None) -> ImageInfo:
    """Validate one upload; raises ImageRejected with a safe message."""

    if not data:
        raise ImageRejected("The file is empty.")

    if len(data) > config.MAX_OMR_IMAGE_BYTES:
        limit = config.MAX_OMR_IMAGE_BYTES // (1024 * 1024)
        raise ImageRejected(f"The image is larger than {limit} MB.")

    extension = declared_extension(filename)

    if extension not in config.OMR_ALLOWED_EXTENSIONS:
        raise ImageRejected("Only PNG and JPEG images are supported.")

    if data.startswith(PNG_SIGNATURE):
        kind = "png"
        width, height = _png_size(data)
    elif data.startswith(b"\xff\xd8\xff"):
        kind = "jpeg"
        width, height = _jpeg_size(data)
    else:
        raise ImageRejected("The file is not a PNG or JPEG image.")

    if (kind == "png") != (extension == ".png"):
        raise ImageRejected("The file content does not match its extension.")

    if min(width, height) < config.OMR_MIN_IMAGE_SIDE:
        raise ImageRejected("The image is too small to read.")

    if width * height > config.OMR_MAX_IMAGE_PIXELS:
        raise ImageRejected("The image has too many pixels.")

    return ImageInfo(kind=kind, width=width, height=height)
