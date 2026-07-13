"""Popup anchor selection and compositor cursor adapters."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable

from .models import AnchorSource, PopupAnchor


def place_popup(anchor, popup_size, screen_rect, avoid_rect=None, gap=6):
    """Place a popup near an anchor, preferring positions outside selected text."""
    width, height = popup_size
    sx, sy, sw, sh = screen_rect
    right, bottom = sx + sw, sy + sh
    ax, ay = anchor

    if avoid_rect:
        rx, ry, rw, rh = avoid_rect
        candidates = [
            (ax + gap, ay + gap),
            (ax - width, ry - height - gap),
            (ax - width, ry + rh + gap),
            (rx + rw + gap, ay - height // 2),
            (rx - width - gap, ay - height // 2),
        ]
    else:
        candidates = [
            (ax + gap, ay + gap),
            (ax + gap, ay - height - gap),
            (ax - width - gap, ay + gap),
            (ax - width - gap, ay - height - gap),
        ]

    def fits(x, y):
        return sx <= x and sy <= y and x + width <= right and y + height <= bottom

    def overlaps(x, y):
        if not avoid_rect:
            return False
        rx, ry, rw, rh = avoid_rect
        return not (
            x + width <= rx - gap
            or x >= rx + rw + gap
            or y + height <= ry - gap
            or y >= ry + rh + gap
        )

    for x, y in candidates:
        if fits(x, y) and not overlaps(x, y):
            return round(x), round(y)

    x, y = candidates[0]
    return (
        round(min(max(x, sx), max(sx, right - width))),
        round(min(max(y, sy), max(sy, bottom - height))),
    )


class AnchorResolver:
    """Selects the freshest, most trustworthy anchor without desktop coupling."""

    def resolve(self, candidates: Iterable[PopupAnchor | None]) -> PopupAnchor | None:
        usable = [candidate for candidate in candidates if candidate and candidate.fresh]
        if not usable:
            return None
        return max(usable, key=lambda item: (item.confidence, item.created_at))


def _run_json(argv: list[str], timeout: float = 0.35):
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=True
        )
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def hyprland_cursor_anchor() -> PopupAnchor | None:
    if not shutil.which("hyprctl"):
        return None
    payload = _run_json(["hyprctl", "cursorpos", "-j"])
    if not isinstance(payload, dict):
        return None
    try:
        return PopupAnchor(
            round(float(payload["x"])),
            round(float(payload["y"])),
            AnchorSource.HYPRLAND,
            0.94,
        )
    except (KeyError, TypeError, ValueError):
        return None


def sway_cursor_anchor() -> PopupAnchor | None:
    if not shutil.which("swaymsg"):
        return None
    payload = _run_json(["swaymsg", "-t", "get_seats", "-r"])
    if not isinstance(payload, list):
        return None
    for seat in payload:
        cursor = seat.get("cursor") if isinstance(seat, dict) else None
        if not isinstance(cursor, dict):
            continue
        try:
            return PopupAnchor(
                round(float(cursor["x"])),
                round(float(cursor["y"])),
                AnchorSource.SWAY,
                0.92,
            )
        except (KeyError, TypeError, ValueError):
            continue
    return None
