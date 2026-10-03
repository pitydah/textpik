"""On-demand XDG desktop portal adapters.

QtDBus is imported only when the user explicitly requests a portal operation,
so the resident selection path remains dependency- and allocation-free.
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse


PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
AREA_TARGET = 4


def portal_request_path(sender: str, token: str) -> str:
    """Return the race-free request path defined by xdg-desktop-portal."""
    sender = sender.lstrip(":").replace(".", "_")
    if not sender or not token or not token.replace("_", "").isalnum():
        raise ValueError("invalid portal request identity")
    return f"{PORTAL_PATH}/request/{sender}/{token}"


def portal_file_path(results: dict) -> Path:
    """Extract and validate the local file URI returned by Screenshot."""
    value = results.get("uri", "") if isinstance(results, dict) else ""
    if hasattr(value, "variant"):
        value = value.variant()
    parsed = urlparse(str(value))
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise RuntimeError("El portal devolvió una captura no local")
    source = Path(unquote(parsed.path)).expanduser()
    if not source.is_file():
        raise RuntimeError("El portal no entregó una captura válida")
    return source


def portal_supports_area(version, available_targets) -> bool:
    """Return whether a v3 portal explicitly advertises area capture."""
    normalized = []
    for value in (version, available_targets):
        if hasattr(value, "variant"):
            value = value.variant()
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            normalized.append(0)
    portal_version, targets = normalized
    return portal_version >= 3 and bool(targets & AREA_TARGET)


def capture_xdg_screenshot(target: Path, *, timeout_seconds: int = 90) -> Path:
    """Interactively capture an area through the XDG Screenshot portal."""
    from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot
    from PySide6.QtDBus import (
        QDBusConnection,
        QDBusInterface,
        QDBusMessage,
        QDBusObjectPath,
        QDBusVariant,
    )

    timeout_seconds = max(5, min(180, int(timeout_seconds)))
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        raise RuntimeError("No hay una sesión D-Bus disponible")

    interface = QDBusInterface(
        PORTAL_SERVICE, PORTAL_PATH, SCREENSHOT_INTERFACE, bus
    )
    if not interface.isValid():
        raise RuntimeError("XDG Screenshot Portal no está disponible")

    token = f"textpik_{secrets.token_hex(12)}"
    expected_path = portal_request_path(bus.baseService(), token)
    loop = QEventLoop()

    class ResponseReceiver(QObject):
        def __init__(self):
            super().__init__()
            self.received = False
            self.response = 2
            self.results = {}

        @Slot("uint", dict)
        def response_ready(self, response, results):
            self.received = True
            self.response = int(response)
            self.results = dict(results)
            loop.quit()

    receiver = ResponseReceiver()

    def connect_request(path):
        return bus.connect(
            PORTAL_SERVICE,
            path,
            REQUEST_INTERFACE,
            "Response",
            receiver,
            "response_ready(uint,QVariantMap)",
        )

    if not connect_request(expected_path):
        raise RuntimeError("No se pudo observar la respuesta del portal")

    options = {
        "handle_token": QDBusVariant(token),
        "interactive": QDBusVariant(True),
        "modal": QDBusVariant(True),
    }
    if portal_supports_area(
        interface.property("version"), interface.property("AvailableTargets")
    ):
        options["target"] = QDBusVariant(AREA_TARGET)

    reply = interface.call("Screenshot", "", options)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        bus.disconnect(
            PORTAL_SERVICE, expected_path, REQUEST_INTERFACE, "Response",
            receiver, "response_ready(uint,QVariantMap)",
        )
        raise RuntimeError(reply.errorMessage() or "El portal rechazó la captura")
    arguments = reply.arguments()
    if not arguments:
        bus.disconnect(
            PORTAL_SERVICE, expected_path, REQUEST_INTERFACE, "Response",
            receiver, "response_ready(uint,QVariantMap)",
        )
        raise RuntimeError("El portal no devolvió un identificador de solicitud")
    handle = arguments[0]
    actual_path = handle.path() if isinstance(handle, QDBusObjectPath) else str(handle)
    if actual_path != expected_path:
        bus.disconnect(
            PORTAL_SERVICE, expected_path, REQUEST_INTERFACE, "Response",
            receiver, "response_ready(uint,QVariantMap)",
        )
        if not connect_request(actual_path):
            raise RuntimeError("No se pudo observar la solicitud del portal")

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_seconds * 1000)
    loop.exec()
    timer.stop()
    bus.disconnect(
        PORTAL_SERVICE, actual_path, REQUEST_INTERFACE, "Response",
        receiver, "response_ready(uint,QVariantMap)",
    )
    if not receiver.received:
        QDBusInterface(
            PORTAL_SERVICE, actual_path, REQUEST_INTERFACE, bus
        ).call("Close")
        raise RuntimeError("La selección de región agotó el tiempo de espera")
    if receiver.response == 1:
        raise RuntimeError("Selección de región cancelada")
    if receiver.response != 0:
        raise RuntimeError("El portal no pudo capturar la región")

    source = portal_file_path(receiver.results)
    if source.resolve() != target:
        shutil.copyfile(source, target)
    return target
