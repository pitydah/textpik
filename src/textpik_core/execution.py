"""Pure command execution policy; actual process creation stays in adapters."""

from __future__ import annotations

import shlex
from pathlib import Path

TERMINAL_EXECUTABLES = frozenset(
    {"konsole", "gnome-terminal", "xterm", "alacritty", "kitty"}
)


def executable_name(command: str) -> str:
    """Return a command's executable basename without executing or resolving it."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return ""
    return Path(argv[0]).name if argv else ""


def is_terminal_execution(command: str) -> bool:
    """Classify commands that require TextPik's terminal confirmation gate."""
    return executable_name(command) in TERMINAL_EXECUTABLES
