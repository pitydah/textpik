"""Pure Linux session and desktop capability detection."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping

TERMINAL_CANDIDATES = (
    "konsole",
    "gnome-terminal",
    "kgx",
    "xfce4-terminal",
    "mate-terminal",
    "kitty",
    "alacritty",
    "xterm",
    "x-terminal-emulator",
)


def is_wayland_session(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("XDG_SESSION_TYPE", "").casefold() == "wayland"


def detect_desktop_environment(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    desktop = ":".join(
        filter(
            None,
            (
                values.get("XDG_CURRENT_DESKTOP", ""),
                values.get("XDG_SESSION_DESKTOP", ""),
                values.get("DESKTOP_SESSION", ""),
            ),
        )
    )
    return desktop.casefold()


def is_kde_desktop(desktop: str) -> bool:
    value = desktop.casefold()
    return "kde" in value or "plasma" in value


def command_exists(
    command: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> bool:
    return which(command) is not None


def find_available_terminal(
    *,
    available: Callable[[str], bool] = command_exists,
) -> str | None:
    return next(
        (command for command in TERMINAL_CANDIDATES if available(command)),
        None,
    )
