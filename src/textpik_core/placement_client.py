"""QtDBus client for the compositor-side TextPik placement effect.

The client is deliberately thin and fails soft.  Placement is an optional
capability: when the effect is missing or the compositor does not answer, every
method reports failure instead of raising, and the popup keeps working in its
explicitly unverified mode.

The transport is injectable so the protocol rules can be tested without a
session bus, and Qt is imported lazily so headless and X11 runs never touch it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import Point

SERVICE_NAME = "org.textpik.KWinPlacement"
OBJECT_PATH = "/KWinPlacement"
INTERFACE_NAME = "org.textpik.KWinPlacement"

# The placement call sits on the selection hot path, so the timeout is short
# enough to notice a stalled compositor without delaying the popup.
CALL_TIMEOUT_MS = 150

READBACK_FIELDS = 7
"""`revision,has_window,x,y,w,h,output`, mirroring the effect's readback()."""


@dataclass(frozen=True, slots=True)
class PlacementConfirmation:
    """Geometry the compositor reported for a placement request."""

    revision: int
    position: Point
    size: tuple[int, int]
    output: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "position": self.position.as_tuple(),
            "size": self.size,
            "output": self.output,
        }


class PlacementTransport(Protocol):
    """The minimal surface the client needs from a D-Bus connection."""

    def call(self, method: str, *args: Any) -> tuple[bool, list[Any]]:
        """Return ``(ok, arguments)``; ``ok`` is false on any D-Bus error."""
        ...

    def call_async(self, method: str, *args: Any, on_done) -> None:
        """Run the call without blocking and hand the result to ``on_done``.

        ``on_done`` receives ``(ok, arguments)``.  The call must never block the
        caller: this is the variant the popup hot path uses, because a stalled
        compositor would otherwise freeze the interface for the timeout.
        """
        ...


class QtDBusPlacementTransport:
    """QtDBus-backed transport against the placement effect.

    ``service_name`` exists so a test can host its own well-formed service
    instead of depending on whether the real effect is loaded.
    """

    def __init__(
        self, timeout_ms: int = CALL_TIMEOUT_MS, service_name: str = SERVICE_NAME
    ) -> None:
        self._timeout_ms = timeout_ms
        self._service_name = service_name
        self._interface: Any = None
        # QDBusPendingCallWatcher is owned by Python: without a live reference
        # the watcher is collected before it can deliver its reply.
        self._watchers: set[Any] = set()
        self.error = ""

    def _iface(self):
        if self._interface is None:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface

            interface = QDBusInterface(
                self._service_name,
                OBJECT_PATH,
                INTERFACE_NAME,
                QDBusConnection.sessionBus(),
            )
            interface.setTimeout(self._timeout_ms)
            self._interface = interface
        return self._interface

    def call(self, method: str, *args: Any) -> tuple[bool, list[Any]]:
        from PySide6.QtDBus import QDBusMessage

        try:
            interface = self._iface()
        except Exception as exc:  # pragma: no cover - depends on Qt install
            self.error = f"qtdbus-unavailable: {exc}"
            return False, []

        if not interface.isValid():
            self.error = "placement-service-unavailable"
            return False, []

        try:
            # PySide6's variadic form takes at most four arguments and
            # requestPlacement sends five, so the list form is the only
            # reliable one. It also needs the call mode spelled out.
            from PySide6.QtDBus import QDBus

            reply = interface.callWithArgumentList(
                QDBus.CallMode.AutoDetect, method, list(args)
            )
        except Exception as exc:  # pragma: no cover - depends on the bus
            self.error = f"call-failed: {exc}"
            return False, []

        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            self.error = str(reply.errorMessage() or "dbus-error")
            return False, []
        return True, list(reply.arguments())

    def call_async(self, method: str, *args: Any, on_done) -> None:
        """Issue the call and return immediately.

        A reply that never arrives cannot strand the caller: QtDBus delivers a
        timeout error for the asynchronous call too, and the popup keeps its own
        reveal deadline as a second guarantee.
        """
        try:
            from PySide6.QtDBus import QDBusMessage, QDBusPendingCallWatcher

            interface = self._iface()
        except Exception as exc:  # pragma: no cover - depends on Qt install
            self.error = f"qtdbus-unavailable: {exc}"
            on_done(False, [])
            return

        if not interface.isValid():
            self.error = "placement-service-unavailable"
            on_done(False, [])
            return

        try:
            # PySide6 exposes only the list form here: asyncCall() takes a single
            # argument, so calling it with the method and its arguments raises
            # TypeError and every asynchronous placement would fail.
            pending = interface.asyncCallWithArgumentList(method, list(args))
        except Exception as exc:  # pragma: no cover - depends on the bus
            self.error = f"call-failed: {exc}"
            on_done(False, [])
            return

        watcher = QDBusPendingCallWatcher(pending)
        self._watchers.add(watcher)

        def _finished(finished):
            self._watchers.discard(watcher)
            reply = finished.reply()
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                self.error = str(reply.errorMessage() or "dbus-error")
                on_done(False, [])
            else:
                on_done(True, list(reply.arguments()))
            finished.deleteLater()

        watcher.finished.connect(_finished)


class KWinPlacementClient:
    """Reads and drives the placement authority exposed by the KWin effect.

    Two shapes are available on purpose.  The popup hot path uses the
    asynchronous calls, because a stalled compositor must not freeze the
    interface.  The blocking variants remain for the availability probe, which
    decides the cloak before the popup is shown and has to answer immediately,
    and for tooling that runs outside the event loop.
    """

    def __init__(self, transport: PlacementTransport | None = None) -> None:
        self._transport = (
            transport if transport is not None else QtDBusPlacementTransport()
        )

    @property
    def last_error(self) -> str:
        return str(getattr(self._transport, "error", ""))

    def available(self) -> bool:
        """Whether a compositor-side placement authority answers at all."""
        ok, _ = self._transport.call("readback")
        return ok

    def register_window(self, internal_id: str = "") -> bool:
        """Pin the effect to one window by KWin's ``internalId``.

        TextPik currently does not call this: KWin's ``internalId`` is a
        compositor-side ``QUuid`` that is not exposed over xdg-shell, so the
        popup cannot know it.  The effect resolves the popup by its window class
        instead, and this method stays available for callers that do know the
        id (for example a future KWin script or a test harness).
        """
        ok, _ = self._transport.call("registerTextPikWindow", str(internal_id or ""))
        return ok

    def unregister_window(self) -> bool:
        ok, _ = self._transport.call("unregisterTextPikWindow")
        return ok

    def request(self, revision: int, x: int, y: int, width: int, height: int) -> bool:
        ok, _ = self._transport.call(
            "requestPlacement",
            int(revision),
            int(x),
            int(y),
            int(width),
            int(height),
        )
        return ok

    def readback(self, revision: int) -> PlacementConfirmation | None:
        """Compositor geometry for ``revision``, or ``None`` if it is not evidence.

        A confirmation is only returned when the effect reports the same
        revision we asked about and actually holds a window.  A superseded
        request, a missing popup, or an unparsable payload must never be
        mistaken for a verified position.
        """
        ok, arguments = self._transport.call("readback")
        if not ok or not arguments:
            return None
        return self.parse(str(arguments[0]), expected_revision=int(revision))

    def request_async(
        self,
        revision: int,
        x: int,
        y: int,
        width: int,
        height: int,
        on_done,
    ) -> None:
        """Ask the compositor to place the popup, without blocking.

        ``on_done(ok)`` runs later on the event loop, so the caller keeps
        ownership of its deadlines: a slow compositor must not freeze the popup.
        """
        self._transport.call_async(
            "requestPlacement",
            int(revision),
            int(x),
            int(y),
            int(width),
            int(height),
            on_done=lambda ok, _arguments: on_done(ok),
        )

    def readback_async(self, revision: int, on_done) -> None:
        """Read the placement back without blocking; ``on_done`` gets the result."""
        expected = int(revision)

        def _parsed(ok, arguments):
            if not ok or not arguments:
                on_done(None)
                return
            on_done(self.parse(str(arguments[0]), expected_revision=expected))

        self._transport.call_async("readback", on_done=_parsed)

    @staticmethod
    def parse(payload: str, *, expected_revision: int) -> PlacementConfirmation | None:
        fields = payload.split(",", READBACK_FIELDS - 1)
        if len(fields) != READBACK_FIELDS:
            return None
        returned_revision, has_window, x, y, width, height, output = fields
        try:
            if int(returned_revision) != expected_revision:
                return None
            if int(has_window) != 1:
                return None
            return PlacementConfirmation(
                revision=expected_revision,
                position=Point(int(x), int(y)),
                size=(int(width), int(height)),
                output=output,
            )
        except ValueError:
            return None
