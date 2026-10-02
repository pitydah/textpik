"""Typed contracts shared by selection, popup and action backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any


@dataclass(frozen=True, slots=True)
class Point:
    """A logical-pixel position in global desktop coordinates."""

    x: int
    y: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class Rect:
    """A logical-pixel rectangle in global desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    def right(self) -> int:
        return self.x + self.width

    def bottom(self) -> int:
        return self.y + self.height


class PlacementBackend(str, Enum):
    """The authority that is allowed to report an observed popup position.

    Only compositor-side backends (``KWIN_EFFECT``, ``X11``) may set
    ``observed_position``.  ``QT_XDG_TOPLEVEL_UNVERIFIED`` exists so that
    ``QWidget.move()`` keeps working on X11 while making its no-op behaviour on
    Wayland explicit instead of silently reported as success.
    """

    KWIN_EFFECT = "kwin-effect"
    X11 = "x11"
    QT_XDG_TOPLEVEL_UNVERIFIED = "qt-xdg-toplevel-unverified"
    UNAVAILABLE = "unavailable"

    @property
    def authoritative(self) -> bool:
        """Whether this backend can observe the real compositor geometry.

        Compared by value rather than by member identity: the project can be
        imported both as ``textpik_core`` and as ``src.textpik_core`` (the CI
        editable install does both), and the two module objects then hold
        distinct enum classes for the same value.
        """
        return self.value in ("kwin-effect", "x11")


class PlacementOutcome(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    MISMATCH = "mismatch"
    STALE = "stale"
    BACKEND_UNAVAILABLE = "backend-unavailable"


@dataclass(frozen=True, slots=True)
class PopupPlacementResult:
    """The outcome of one placement request.

    ``desired`` is what the anchor resolver asked for, ``requested`` is what
    survived workarea constraints, and ``observed`` is what the compositor
    reported back.  ``verified`` is only ever true when an authoritative backend
    confirmed the request, the revision is still active, and the observed
    geometry is within tolerance.
    """

    backend: PlacementBackend
    desired: Point
    requested: Point
    constrained: Point | None = None
    observed: Point | None = None
    requested_size: tuple[int, int] | None = None
    observed_size: tuple[int, int] | None = None
    output: str = ""
    revision: int | None = None
    active_revision: int | None = None
    tolerance: int = 2
    error: str | None = None

    def __post_init__(self) -> None:
        # A non-authoritative backend can never publish an observed position:
        # Qt's own geometry under Wayland is a claim, not evidence.
        if not self.backend.authoritative and self.observed is not None:
            object.__setattr__(self, "observed", None)
            object.__setattr__(self, "observed_size", None)
            object.__setattr__(self, "error", self.error or "untrusted-backend")
        if self.error is not None:
            return
        object.__setattr__(self, "error", self._derive_error())

    def _revision_is_stale(self) -> bool:
        return (
            self.revision is not None
            and self.active_revision is not None
            and self.revision != self.active_revision
        )

    def _origin_mismatch(self) -> bool:
        if self.observed is None:
            return False
        return (
            abs(self.observed.x - self.requested.x) > self.tolerance
            or abs(self.observed.y - self.requested.y) > self.tolerance
        )

    def _size_mismatch(self) -> bool:
        if self.requested_size is None or self.observed_size is None:
            return False
        return (
            abs(self.observed_size[0] - self.requested_size[0]) > self.tolerance
            or abs(self.observed_size[1] - self.requested_size[1]) > self.tolerance
        )

    def _derive_error(self) -> str | None:
        if self.backend.value == PlacementBackend.UNAVAILABLE.value:
            return "placement-backend-unavailable"
        if not self.backend.authoritative:
            return None
        if self._revision_is_stale():
            return "stale-revision"
        if self.observed is None:
            return None
        if self._size_mismatch():
            return "size-mismatch"
        if self._origin_mismatch():
            return "position-mismatch"
        return None

    @property
    def verified(self) -> bool:
        if not self.backend.authoritative:
            return False
        if self.observed is None:
            return False
        if (
            self.revision is not None
            and self.active_revision is not None
            and self.revision != self.active_revision
        ):
            return False
        if (
            abs(self.observed.x - self.requested.x) > self.tolerance
            or abs(self.observed.y - self.requested.y) > self.tolerance
        ):
            return False
        if (
            self.requested_size is not None
            and self.observed_size is not None
            and (
                abs(self.observed_size[0] - self.requested_size[0]) > self.tolerance
                or abs(self.observed_size[1] - self.requested_size[1]) > self.tolerance
            )
        ):
            return False
        return True

    @property
    def outcome(self) -> PlacementOutcome:
        if self.verified:
            return PlacementOutcome.VERIFIED
        if self.backend.value == PlacementBackend.UNAVAILABLE.value:
            return PlacementOutcome.BACKEND_UNAVAILABLE
        if not self.backend.authoritative:
            return PlacementOutcome.UNVERIFIED
        if (
            self.revision is not None
            and self.active_revision is not None
            and self.revision != self.active_revision
        ):
            return PlacementOutcome.STALE
        if self.observed is None:
            return PlacementOutcome.UNVERIFIED
        if self.error == "size-mismatch":
            return PlacementOutcome.MISMATCH
        if (
            abs(self.observed.x - self.requested.x) > self.tolerance
            or abs(self.observed.y - self.requested.y) > self.tolerance
        ):
            return PlacementOutcome.MISMATCH
        return PlacementOutcome.UNVERIFIED

    def as_dict(self) -> dict:
        return {
            "backend": self.backend.value,
            "desired": self.desired.as_tuple(),
            "requested": self.requested.as_tuple(),
            "constrained": self.constrained.as_tuple() if self.constrained else None,
            "observed": self.observed.as_tuple() if self.observed else None,
            "requested_size": self.requested_size,
            "observed_size": self.observed_size,
            "output": self.output,
            "revision": self.revision,
            "active_revision": self.active_revision,
            "tolerance": self.tolerance,
            "verified": self.verified,
            "outcome": self.outcome.value,
            "error": self.error,
        }


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

    def action_snapshot(self) -> "SelectionContext":
        """Freeze the target that a visible popup action is allowed to mutate.

        `native_handle` intentionally remains the same AT-SPI object; the
        surrounding metadata and captured range are copied so a later selection
        cannot retarget an already-visible action by replacing the application's
        mutable `selection_context`.
        """
        return SelectionContext(
            text=str(self.text),
            anchor=self.anchor,
            application=str(self.application),
            role=str(self.role),
            sensitive=bool(self.sensitive),
            editable=bool(self.editable),
            selection_start=self.selection_start,
            selection_end=self.selection_end,
            backend=str(self.backend),
            selection_rect=(
                tuple(self.selection_rect) if self.selection_rect is not None else None
            ),
            native_handle=self.native_handle,
        )


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
