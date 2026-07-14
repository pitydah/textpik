"""Typed contracts shared by selection, popup and action backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any


class AnchorSource(str, Enum):
    ATSPI_SELECTION = "atspi-selection"
    KWIN = "kwin"
    HYPRLAND = "hyprland"
    SWAY = "sway"
    X11_POINTER = "x11-pointer"
    QT_POINTER = "qt-pointer"
    SCREEN_FALLBACK = "screen-fallback"


@dataclass(frozen=True, slots=True)
class PopupAnchor:
    x: int
    y: int
    source: AnchorSource
    confidence: float = 1.0
    created_at: float = field(default_factory=monotonic)
    ttl: float = 1.5

    @property
    def fresh(self) -> bool:
        return monotonic() - self.created_at <= self.ttl


@dataclass(slots=True)
class SelectionContext:
    text: str
    anchor: PopupAnchor | None = None
    application: str = ""
    role: str = ""
    sensitive: bool = False
    editable: bool = False
    selection_start: int | None = None
    selection_end: int | None = None
    backend: str = "clipboard"
    selection_rect: tuple[int, int, int, int] | None = None
    native_handle: Any = field(default=None, repr=False, compare=False)


class ActionOperation(str, Enum):
    COPY = "copy"
    TRANSFORM = "transform"
    OPEN_URL = "open-url"
    COMMAND = "command"
    SYSTEM = "system"


class ActionResultType(str, Enum):
    NONE = "none"
    COPY = "copy"
    REPLACE_SELECTION = "replace-selection"
    OPEN = "open"
    DIALOG = "dialog"


@dataclass(frozen=True, slots=True)
class ActionManifest:
    id: str
    name: str
    icon: str
    command: str
    operation: ActionOperation = ActionOperation.COMMAND
    result: ActionResultType = ActionResultType.NONE
    enabled: bool = True
    contexts: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    category: str = "General"


@dataclass(frozen=True, slots=True)
class ActionResult:
    kind: ActionResultType
    text: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
