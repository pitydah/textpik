"""Truthful desktop-boundary capabilities for TextPik.

This module intentionally separates evidence from implementation.  In
particular, a cursor bridge, an activation signal, and a positioning backend are
three different authorities on Wayland.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .platform import desktop_family


class CapabilityTruth(str, Enum):
    VERIFIED = "verified"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WaylandCapabilityProfile:
    session: str
    desktop: str
    pointer_position: CapabilityTruth
    global_pointer_buttons: CapabilityTruth
    outside_click: CapabilityTruth
    positioning: CapabilityTruth
    positioning_backend: str
    required_backend: str
    popup_parity: str

    def as_dict(self) -> dict:
        payload = asdict(self)
        for key in (
            "pointer_position",
            "global_pointer_buttons",
            "outside_click",
            "positioning",
        ):
            payload[key] = getattr(self, key).value
        return payload


def _desktop_family(desktop: str) -> str:
    """Kept for backwards compatibility: see :mod:`textpik_core.platform`."""
    return desktop_family(desktop)


def build_wayland_profile(
    *,
    platform_name: str,
    desktop: str,
    kwin_cursor_bridge: bool = False,
    kwin_cursor_samples: bool = False,
    kwin_activation_bridge: bool = False,
    kwin_placement_effect: bool = False,
) -> WaylandCapabilityProfile:
    platform = str(platform_name or "").casefold()
    family = _desktop_family(desktop)

    if not platform.startswith("wayland"):
        return WaylandCapabilityProfile(
            session="x11",
            desktop=family,
            pointer_position=CapabilityTruth.VERIFIED,
            global_pointer_buttons=CapabilityTruth.VERIFIED,
            outside_click=CapabilityTruth.VERIFIED,
            positioning=CapabilityTruth.VERIFIED,
            positioning_backend="x11-window-manager",
            required_backend="none",
            popup_parity="desktop-validation-required",
        )

    if family == "plasma":
        return WaylandCapabilityProfile(
            session="wayland",
            desktop=family,
            # Registering the endpoint only proves TextPik is listening. A
            # verified position needs the KWin script to have actually sent a
            # recent sample, otherwise the claim is about an open socket.
            pointer_position=(
                CapabilityTruth.VERIFIED
                if (kwin_cursor_bridge and kwin_cursor_samples)
                else CapabilityTruth.DEGRADED
            ),
            global_pointer_buttons=CapabilityTruth.UNAVAILABLE,
            outside_click=(
                CapabilityTruth.DEGRADED
                if kwin_activation_bridge
                else CapabilityTruth.UNAVAILABLE
            ),
            positioning=(
                CapabilityTruth.VERIFIED
                if kwin_placement_effect
                else CapabilityTruth.DEGRADED
            ),
            positioning_backend=(
                "kwin-effect"
                if kwin_placement_effect
                else "qt-xdg-toplevel-unverified"
            ),
            required_backend=(
                "none"
                if kwin_placement_effect
                else "kwin-placement-effect"
            ),
            popup_parity=(
                "verified-placement-degraded-input"
                if kwin_placement_effect
                else "degraded-wayland"
            ),
        )

    if family == "gnome":
        required = "gnome-shell-presentation-integration"
    elif family in {"sway", "hyprland"}:
        required = "real-layer-shell-client-plus-input-backend"
    else:
        required = "compositor-specific-presentation-backend"

    return WaylandCapabilityProfile(
        session="wayland",
        desktop=family,
        pointer_position=CapabilityTruth.DEGRADED,
        global_pointer_buttons=CapabilityTruth.UNAVAILABLE,
        outside_click=CapabilityTruth.UNAVAILABLE,
        positioning=CapabilityTruth.DEGRADED,
        positioning_backend="qt-xdg-toplevel-best-effort",
        required_backend=required,
        popup_parity="degraded-wayland",
    )
