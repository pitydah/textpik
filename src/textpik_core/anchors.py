"""Popup anchor selection and compositor cursor adapters."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass

from .models import AnchorSource, PopupAnchor


SOURCE_WEIGHT = {
    AnchorSource.ATSPI_SELECTION: 0.08,
    AnchorSource.KWIN: 0.07,
    AnchorSource.HYPRLAND: 0.06,
    AnchorSource.SWAY: 0.06,
    AnchorSource.X11_POINTER: 0.05,
    AnchorSource.QT_POINTER: 0.0,
    AnchorSource.SCREEN_FALLBACK: -0.1,
}


@dataclass(frozen=True, slots=True)
class AnchorDecision:
    anchor: PopupAnchor | None
    considered: int
    reason: str


def place_popup(
    anchor,
    popup_size,
    screen_rect,
    avoid_rect=None,
    gap=6,
    pointer_direction=None,
    preference="auto",
):
    """Place a popup using a small deterministic candidate score.

    The candidate set is deliberately bounded: placement stays constant-time on
    the selection hot path while avoiding both selected text and screen edges.
    """
    width, height = popup_size
    sx, sy, sw, sh = screen_rect
    right, bottom = sx + sw, sy + sh
    ax, ay = anchor

    if avoid_rect:
        rx, ry, rw, rh = avoid_rect
        candidates = [
            # Cursor-local quadrants keep the toolbar close to the final drag
            # edge. The overlap score rejects whichever side covers selection.
            (ax + gap, ay + gap),
            (ax + gap, ay - height - gap),
            (ax - width - gap, ay + gap),
            (ax - width - gap, ay - height - gap),
            (ax - width // 2, ry - height - gap),
            (ax - width // 2, ry + rh + gap),
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

    if (
        pointer_direction
        and len(candidates) >= 4
        and (not avoid_rect or preference == "auto")
    ):
        dx, dy = pointer_direction
        if abs(dx) > abs(dy):
            preferred = 3 if dx > 0 else 2
        else:
            preferred = 0 if dy > 0 else 1
        candidates.insert(0, candidates.pop(preferred))
    explicit_preferred = None
    if avoid_rect and preference in {"above", "below", "side"}:
        preferred = {"above": 4, "below": 5, "side": 6}[preference]
        candidates.insert(0, candidates.pop(preferred))
        explicit_preferred = candidates[0]

    def clamp(value, low, high):
        return min(max(value, low), max(low, high))

    def overlap_area(x, y):
        if not avoid_rect:
            return 0
        rx, ry, rw, rh = avoid_rect
        overlap_width = max(0, min(x + width, rx + rw) - max(x, rx))
        overlap_height = max(0, min(y + height, ry + rh) - max(y, ry))
        return overlap_width * overlap_height

    scored = []
    for order, (raw_x, raw_y) in enumerate(candidates):
        x = clamp(raw_x, sx, right - width)
        y = clamp(raw_y, sy, bottom - height)
        displacement = abs(x - raw_x) + abs(y - raw_y)
        # Measure the pointer-to-edge distance, not pointer-to-center. A wide
        # toolbar can be easy to reach even when its visual center is far away.
        cursor_dx = max(x - ax, 0, ax - (x + width))
        cursor_dy = max(y - ay, 0, ay - (y + height))
        distance = cursor_dx + cursor_dy
        covers_anchor = x <= ax <= x + width and y <= ay <= y + height
        score = (
            overlap_area(x, y) * 10_000
            + int(covers_anchor) * 1_000_000
            + displacement * 80
            + int(
                explicit_preferred is not None
                and (raw_x, raw_y) != explicit_preferred
            ) * 500
            + distance
            + order
        )
        scored.append((score, round(x), round(y)))
    _, x, y = min(scored)
    return x, y


def stabilize_popup_position(
    candidate,
    previous,
    popup_size,
    avoid_rect=None,
    threshold=14,
):
    """Keep tiny anchor fluctuations from making a visible popup jitter."""
    if previous is None:
        return candidate
    x, y = candidate
    px, py = previous
    if abs(x - px) > threshold or abs(y - py) > threshold:
        return candidate
    if avoid_rect:
        width, height = popup_size
        rx, ry, rw, rh = avoid_rect
        overlaps = not (
            px + width <= rx
            or px >= rx + rw
            or py + height <= ry
            or py >= ry + rh
        )
        if overlaps:
            return candidate
    return previous


class AnchorResolver:
    """Selects the freshest, most trustworthy anchor without desktop coupling."""

    def resolve(self, candidates: Iterable[PopupAnchor | None]) -> PopupAnchor | None:
        return self.resolve_with_reason(candidates).anchor

    def resolve_with_reason(self, candidates: Iterable[PopupAnchor | None]) -> AnchorDecision:
        usable = [candidate for candidate in candidates if candidate and candidate.fresh]
        if not usable:
            return AnchorDecision(None, 0, "no-fresh-anchor")
        winner = max(
            usable,
            key=lambda item: (
                min(1.0, item.confidence + SOURCE_WEIGHT.get(item.source, 0.0)),
                item.created_at,
            ),
        )
        return AnchorDecision(winner, len(usable), winner.source.value)


def scale_anchor(anchor: PopupAnchor, scale: float) -> PopupAnchor:
    """Normalize logical compositor coordinates to Qt device coordinates."""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    scale = min(4.0, max(0.5, scale))
    return PopupAnchor(
        round(anchor.x * scale), round(anchor.y * scale), anchor.source,
        anchor.confidence, anchor.created_at, anchor.ttl,
    )


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
