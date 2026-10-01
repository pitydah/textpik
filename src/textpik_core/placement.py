"""Explicit popup placement authority selection and revision bookkeeping.

TextPik refuses to claim a popup position it did not read from the compositor.
This module answers two questions and nothing else:

* which backend is allowed to place the popup for this session, and
* which placement request is still current.

Everything compositor-specific (D-Bus, effect availability) is injected so the
selection logic stays pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import PlacementBackend
from .platform import desktop_family

# Backends that keep TextPik usable but can never report a verified position.
UNVERIFIED_BACKENDS = {
    "gnome": "no-gnome-presentation-backend",
    "sway": "layer-shell-backend-not-implemented",
    "hyprland": "layer-shell-backend-not-implemented",
}


@dataclass(frozen=True, slots=True)
class PlacementBackendChoice:
    """Why a given placement backend was selected for this session."""

    backend: PlacementBackend
    authoritative: bool
    reason: str
    detail: str = ""

    @property
    def verified_possible(self) -> bool:
        return self.authoritative


def select_placement_backend(
    *,
    platform_name: str,
    desktop: str,
    effect_available: bool | None = None,
) -> PlacementBackendChoice:
    """Pick the placement authority for the current session.

    ``effect_available`` is the tri-state "is the TextPik KWin Effect loaded":
    ``True``/``False`` when known, ``None`` when it was not probed.
    """
    platform = str(platform_name or "").casefold()
    family = desktop_family(desktop)

    if not platform:
        return PlacementBackendChoice(
            PlacementBackend.UNAVAILABLE,
            False,
            "unknown-platform",
            "the Qt platform plugin name is empty",
        )

    if platform.startswith("offscreen") or platform.startswith("minimal"):
        return PlacementBackendChoice(
            PlacementBackend.UNAVAILABLE,
            False,
            "headless-platform",
            f"platform={platform}",
        )

    if not platform.startswith("wayland"):
        # X11 exposes a real window manager, so an observed position exists.
        return PlacementBackendChoice(
            PlacementBackend.X11,
            True,
            "x11-session",
            f"platform={platform}",
        )

    if family == "plasma":
        if effect_available:
            return PlacementBackendChoice(
                PlacementBackend.KWIN_EFFECT,
                True,
                "kwin-effect-loaded",
                "compositor applies and confirms the position",
            )
        return PlacementBackendChoice(
            PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            False,
            "kwin-effect-missing",
            "QWidget.move() is a no-op on Wayland; install the kwin-effect",
        )

    if family in UNVERIFIED_BACKENDS:
        return PlacementBackendChoice(
            PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            False,
            UNVERIFIED_BACKENDS[family],
            f"desktop={family}",
        )

    return PlacementBackendChoice(
        PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
        False,
        "no-placement-backend-for-this-compositor",
        f"desktop={family or 'unknown'}",
    )


class PresentationLease:
    """Tracks which placement request is still current.

    Confirmations arrive asynchronously from the compositor, so a confirmation
    for a superseded revision must never mutate the current popup state.
    """

    __slots__ = ("_active", "_applied", "_next")

    def __init__(self) -> None:
        self._active = 0
        self._applied = 0
        self._next = 0

    @property
    def active_revision(self) -> int:
        return self._active

    @property
    def applied_revision(self) -> int:
        return self._applied

    def begin(self) -> int:
        """Start a new placement request and make it the only current one."""
        self._next += 1
        self._active = self._next
        return self._active

    def accept(self, revision: int) -> bool:
        """Apply a confirmation, dropping anything that is no longer current."""
        if revision != self._active or self._active == 0:
            return False
        self._applied = revision
        return True

    def release(self) -> None:
        """Drop the current request so late confirmations are ignored."""
        self._active = 0
        self._applied = 0
