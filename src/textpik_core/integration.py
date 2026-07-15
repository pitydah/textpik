"""Desktop capability and action integration policies."""

from __future__ import annotations

from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    available: bool
    label: str
    degraded: bool = False


def action_availability(
    command: str,
    *,
    wayland: bool,
    kde: bool,
    dbus_services: set[str] | None = None,
) -> ActionAvailability:
    services = dbus_services or set()
    if command == "print" and not which("lp"):
        return ActionAvailability(False, "Requiere CUPS (comando lp)")
    if command == "ollama" and not which("ollama"):
        return ActionAvailability(False, "Ollama no está instalado")
    if command in {"ocr-image", "ocr-region"} and not which("tesseract"):
        return ActionAvailability(False, "Tesseract no está instalado")
    if command == "ocr-region" and not (
        which("spectacle")
        or which("gnome-screenshot")
        or (which("grim") and which("slurp"))
    ):
        return ActionAvailability(False, "No hay capturador de región compatible")
    if command in {"klipper-save", "klipper-menu"}:
        ready = kde and "org.kde.klipper" in services
        return ActionAvailability(ready, "Klipper no está disponible" if not ready else "Integración Klipper")
    if command == "kdeconnect":
        ready = bool(which("kdeconnect-cli")) or "org.kde.kdeconnect" in services
        return ActionAvailability(
            ready,
            "KDE Connect no está disponible" if not ready else "Integración KDE Connect",
        )
    if command == "terminal" and not any(
        which(name)
        for name in (
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
    ):
        return ActionAvailability(False, "No se encontró un emulador de terminal")
    if command == "paste":
        tools = ("wtype", "ydotool") if wayland else ("xdotool",)
        if not any(which(tool) for tool in tools):
            return ActionAvailability(True, "Copiará sin pegar automáticamente", True)
    return ActionAvailability(True, "Disponible")
