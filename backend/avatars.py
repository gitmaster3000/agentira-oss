"""Profile picture choices and validation (shared by REST admin PATCH and MCP).

Values: "" (default), "preset:<n>" (people's characters), "bot:<n>" (robot
styles), an https image link, or a small inline image (data URL).
"""

from __future__ import annotations

import base64
import binascii
import re

# Robot styles, index = the <n> in "bot:<n>". Keep the frontend robot list the
# same length (frontend/src/components/UserAvatar.jsx) when changing this.
BOT_STYLES = [
    "Classic",
    "Round",
    "Boxy",
    "Antenna",
    "Visor",
    "Friendly",
]

MAX_URL_CHARS = 1000
MAX_IMAGE_BYTES = 200 * 1024
IMAGE_TYPES = ("png", "jpeg", "webp", "gif")

_INDEX = re.compile(r"^(preset|bot):(\d{1,4})$")
_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/]*={0,2})$")

ALLOWED = (
    "Allowed pictures: empty (default), a robot style like 'bot:0' "
    f"(0 to {len(BOT_STYLES) - 1}), an https:// image link up to {MAX_URL_CHARS} "
    f"characters, or a small {'/'.join(IMAGE_TYPES)} image as a base64 data URL "
    f"up to {MAX_IMAGE_BYTES // 1024} KB."
)


def avatar_choices(current: str = "") -> dict:
    return {
        "robot_styles": [{"value": f"bot:{i}", "label": n} for i, n in enumerate(BOT_STYLES)],
        "accepted": {
            "image_link": f"https:// link, max {MAX_URL_CHARS} characters",
            "image_data_url": f"data:image/({'|'.join(IMAGE_TYPES)});base64,..., max {MAX_IMAGE_BYTES // 1024} KB",
        },
        "max_image_kb": MAX_IMAGE_BYTES // 1024,
        "current": current or "",
    }


def validate_avatar(value: str) -> str:
    """Return value if it is a valid picture, else raise ValueError (plain message)."""
    if value == "":
        return value
    m = _INDEX.match(value)
    if m:
        if m.group(1) == "bot" and int(m.group(2)) >= len(BOT_STYLES):
            raise ValueError(f"Unknown robot style '{value}'. {ALLOWED}")
        return value
    if value.startswith("https://"):
        if len(value) > MAX_URL_CHARS or re.search(r"\s", value) or len(value) <= len("https://"):
            raise ValueError(f"That image link is not valid or is too long. {ALLOWED}")
        return value
    if value.startswith("data:"):
        m = _DATA_URL.match(value)
        if not m:
            raise ValueError(f"That is not a supported image. {ALLOWED}")
        b64 = m.group(2)
        # Estimate before decoding so a huge value is refused cheaply.
        if len(b64) * 3 // 4 > MAX_IMAGE_BYTES + 3:
            raise ValueError(f"That image is too big. {ALLOWED}")
        try:
            size = len(base64.b64decode(b64, validate=True))
        except (binascii.Error, ValueError):
            raise ValueError(f"That image data is broken. {ALLOWED}")
        if size > MAX_IMAGE_BYTES:
            raise ValueError(f"That image is too big. {ALLOWED}")
        return value
    raise ValueError(f"That is not a valid picture. {ALLOWED}")
