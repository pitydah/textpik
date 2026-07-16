"""Small local text utilities used by built-in actions."""

from __future__ import annotations

import colorsys
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass


ANSI_ESCAPE = re.compile(r"\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
URL = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)
EMAIL = re.compile(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{6,}\d)(?!\w)")


@dataclass(frozen=True, slots=True)
class EntitySummary:
    urls: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()

    def render(self) -> str:
        groups = []
        for title, values in (("Enlaces", self.urls), ("Correos", self.emails), ("Teléfonos", self.phones)):
            if values:
                groups.append(f"{title}:\n" + "\n".join(values))
        return "\n\n".join(groups)


def extract_entities(text: str, maximum: int = 50) -> EntitySummary:
    maximum = max(1, min(200, int(maximum)))

    def unique(pattern):
        return tuple(dict.fromkeys(match.group(0).rstrip(".,;:") for match in pattern.finditer(text)))[:maximum]

    return EntitySummary(unique(URL), unique(EMAIL), unique(PHONE))


def format_json(text: str, *, compact: bool = False) -> str:
    if len(text) > 1_000_000:
        raise ValueError("JSON input is too large")
    value = json.loads(text)
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def color_details(text: str) -> str:
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError("unsupported color")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    return (
        f"HEX #{value.upper()}\n"
        f"RGB {red}, {green}, {blue}\n"
        f"HSL {round(hue * 360)}°, {round(saturation * 100)}%, {round(lightness * 100)}%"
    )


def slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")


def clean_terminal_text(text: str) -> str:
    return ANSI_ESCAPE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def compare_text(left: str, right: str) -> str:
    if len(left) > 100_000 or len(right) > 100_000:
        raise ValueError("comparison input is too large")
    lines = difflib.unified_diff(
        left.splitlines(), right.splitlines(),
        fromfile="selección", tofile="portapapeles", lineterm="",
    )
    return "\n".join(lines)[:500_000]
