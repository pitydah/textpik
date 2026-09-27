"""Desktop capability and action integration policies."""

from __future__ import annotations

import json
import locale
import re
import subprocess
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    available: bool
    label: str
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Slow integration facts collected away from the popup hot path."""

    ollama_model: str = ""
    ollama_models: tuple[str, ...] = ()
    ocr_languages: tuple[str, ...] = ()
    grammar_languages: tuple[str, ...] = ()
    spelling_language: str = ""
    grammar_ready: bool = False
    wasi_ready: bool = False


def available_commands(names) -> tuple[str, ...]:
    """Return installed integration commands without starting any service."""
    return tuple(name for name in names if which(str(name)))


def kdeconnect_devices(timeout: float = 3.0) -> tuple[tuple[str, str], ...]:
    if not which("kdeconnect-cli"):
        return ()
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "--list-available"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    devices = []
    for line in result.stdout.splitlines():
        match = re.search(r"^-\s+(.+?):\s+([A-Za-z0-9_.:-]+)\s+on\s+", line)
        if match:
            devices.append((match.group(2), match.group(1).strip()))
    return tuple(devices)


def cups_printers(timeout: float = 2.0) -> tuple[str, ...]:
    if not which("lpstat"):
        return ()
    try:
        result = subprocess.run(
            ["lpstat", "-a"], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(
        line.split()[0] for line in result.stdout.splitlines() if line.split()
    )


def _preferred_ollama_model(names: list[str], preferred: str = "") -> str:
    if preferred and preferred in names:
        return preferred
    priorities = ("llama3.2", "llama3.1", "llama3", "qwen3", "qwen2.5")
    for prefix in priorities:
        if match := next((name for name in names if name.casefold().startswith(prefix)), ""):
            return match
    return names[0] if names else ""


def probe_runtime_capabilities(
    *,
    preferred_ollama_model: str = "",
    ollama_endpoint: str = "http://127.0.0.1:11434/api/generate",
    grammar_endpoint: str = "http://127.0.0.1:8010/v2/languages",
    preferred_spelling_language: str = "auto",
) -> RuntimeCapabilities:
    """Probe optional providers once; every operation is local and bounded."""
    ollama_model = ""
    ollama_models: tuple[str, ...] = ()
    try:
        parsed = urlsplit(ollama_endpoint)
        tags_endpoint = urlunsplit(
            (parsed.scheme, parsed.netloc, "/api/tags", "", "")
        )
        with urllib.request.urlopen(tags_endpoint, timeout=0.7) as response:
            body = json.loads(response.read(1_000_001))
        names = [
            str(item.get("name", "")).strip()
            for item in body.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]
        ollama_models = tuple(names)
        ollama_model = _preferred_ollama_model(names, preferred_ollama_model)
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    ocr_languages: tuple[str, ...] = ()
    if which("tesseract"):
        try:
            result = subprocess.run(
                ["tesseract", "--list-langs"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            installed = {
                value.strip()
                for value in result.stdout.splitlines()[1:]
                if value.strip()
            }
            preferred = tuple(value for value in ("eng", "spa") if value in installed)
            ocr_languages = preferred or tuple(sorted(installed - {"osd"})[:1])
        except (OSError, subprocess.SubprocessError):
            pass

    spelling_language = ""
    try:
        import enchant

        locale_name = (locale.getlocale()[0] or "").replace("-", "_")
        candidates = tuple(
            dict.fromkeys(
                value
                for value in (
                    preferred_spelling_language
                    if preferred_spelling_language != "auto" else "",
                    locale_name, "es_CL", "es_ES", "es", "en_US", "en_GB",
                )
                if value
            )
        )
        spelling_language = next(
            (language for language in candidates if enchant.dict_exists(language)), ""
        )
    except (ImportError, OSError, RuntimeError):
        pass

    grammar_ready = False
    grammar_languages: tuple[str, ...] = ()
    try:
        grammar_probe_endpoint = (
            grammar_endpoint.removesuffix("/check") + "/languages"
            if grammar_endpoint.endswith("/check")
            else grammar_endpoint
        )
        with urllib.request.urlopen(grammar_probe_endpoint, timeout=0.5) as response:
            raw_languages = response.read(1_000_001)
        body = json.loads(raw_languages)
        grammar_languages = tuple(
            str(item.get("longCode") or item.get("code") or "").strip()
            for item in body[:200]
            if isinstance(item, dict) and (item.get("longCode") or item.get("code"))
        )
        grammar_ready = True
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    return RuntimeCapabilities(
        ollama_model=ollama_model,
        ollama_models=ollama_models,
        ocr_languages=ocr_languages,
        grammar_languages=grammar_languages,
        spelling_language=spelling_language,
        grammar_ready=grammar_ready,
        wasi_ready=bool(which("wasmtime")),
    )


def action_availability(
    command: str,
    *,
    wayland: bool,
    kde: bool,
    dbus_services: set[str] | None = None,
    history_enabled: bool = True,
    capabilities: RuntimeCapabilities | None = None,
    preferred_media_player: str = "auto",
    preferred_terminal: str = "auto",
    preferred_speech_engine: str = "auto",
    preferred_ocr_languages: str = "auto",
    preferred_screenshot_backend: str = "auto",
    preferred_printer: str = "auto",
    preferred_browser: str = "auto",
    clipboard_backend: str = "auto",
) -> ActionAvailability:
    services = dbus_services or set()
    if command == "textpik-history" and not history_enabled:
        return ActionAvailability(False, "Activa el historial privado en Configuración")
    if command == "print":
        if not which("lp"):
            return ActionAvailability(False, "Requiere CUPS (comando lp)")
        if preferred_printer != "auto":
            return ActionAvailability(True, f"Impresora: {preferred_printer}")
    if command == "ollama":
        if capabilities is not None and not capabilities.ollama_model:
            return ActionAvailability(False, "Inicia Ollama e instala al menos un modelo")
        if capabilities is not None:
            return ActionAvailability(True, f"Modelo local: {capabilities.ollama_model}")
    ocr_degraded = False
    if command in {"ocr-image", "ocr-region"}:
        if not which("tesseract"):
            return ActionAvailability(False, "Tesseract no está instalado")
        if capabilities is not None and not capabilities.ocr_languages:
            return ActionAvailability(False, "Tesseract no tiene idiomas OCR instalados")
        if capabilities is not None and preferred_ocr_languages != "auto":
            requested = set(preferred_ocr_languages.split("+"))
            missing = requested - set(capabilities.ocr_languages)
            if missing:
                return ActionAvailability(
                    False, f"Faltan idiomas OCR: {', '.join(sorted(missing))}"
                )
        if capabilities is not None and "spa" not in capabilities.ocr_languages:
            ocr_degraded = True
    if command == "spellcheck" and capabilities is not None:
        if not capabilities.spelling_language:
            return ActionAvailability(False, "Requiere PyEnchant y un diccionario")
        return ActionAvailability(True, f"Diccionario: {capabilities.spelling_language}")
    if command == "grammar" and capabilities is not None:
        return ActionAvailability(
            capabilities.grammar_ready,
            "LanguageTool local disponible"
            if capabilities.grammar_ready
            else "Inicia LanguageTool en 127.0.0.1:8010",
        )
    if command.startswith("wasi:") and capabilities is not None:
        return ActionAvailability(
            capabilities.wasi_ready,
            "Runtime WASI disponible" if capabilities.wasi_ready else "Requiere wasmtime",
        )
    screenshot_ready = {
        "spectacle": bool(which("spectacle")),
        "gnome-screenshot": bool(which("gnome-screenshot")),
        "grim-slurp": bool(which("grim") and which("slurp")),
        "portal": "org.freedesktop.portal.Desktop" in services,
    }
    if command == "ocr-region" and not (
        any(screenshot_ready.values())
        if preferred_screenshot_backend == "auto"
        else screenshot_ready.get(preferred_screenshot_backend, False)
    ):
        return ActionAvailability(False, "No hay capturador de región compatible")
    if command in {"ocr-image", "ocr-region"} and ocr_degraded:
        return ActionAvailability(True, "OCR disponible sin español", True)
    if command in {"klipper-save", "klipper-menu"}:
        klipper_ready = kde and "org.kde.klipper" in services
        if clipboard_backend == "textpik" or (
            clipboard_backend == "auto" and not klipper_ready and history_enabled
        ):
            return ActionAvailability(
                history_enabled,
                "Historial privado de TextPik"
                if history_enabled else "Activa el historial privado",
            )
        return ActionAvailability(
            klipper_ready,
            "Klipper no está disponible" if not klipper_ready else "Integración Klipper",
        )
    if command == "kdeconnect":
        ready = bool(which("kdeconnect-cli")) or bool(
            {"org.kde.kdeconnect", "org.gnome.Shell.Extensions.GSConnect"} & services
        )
        return ActionAvailability(
            ready,
            "KDE Connect no está disponible" if not ready else "Integración KDE Connect",
        )
    if command == "open-media-player" and preferred_media_player != "auto":
        ready = bool(which(preferred_media_player))
        return ActionAvailability(
            ready,
            f"Reproductor: {preferred_media_player}"
            if ready else f"No está instalado: {preferred_media_player}",
        )
    if command.startswith("xdg-open") and preferred_browser != "auto" and not which(preferred_browser):
        return ActionAvailability(False, f"Navegador no instalado: {preferred_browser}")
    terminal_names = (
        "konsole", "gnome-terminal", "kgx", "xfce4-terminal", "mate-terminal",
        "kitty", "alacritty", "xterm", "x-terminal-emulator",
    )
    if command == "terminal" and preferred_terminal != "auto":
        ready = bool(which(preferred_terminal))
        return ActionAvailability(
            ready,
            f"Terminal: {preferred_terminal}"
            if ready else f"No está instalada: {preferred_terminal}",
        )
    if command == "terminal" and not any(
        which(name)
        for name in terminal_names
    ):
        return ActionAvailability(False, "No se encontró un emulador de terminal")
    if command == "speak" and preferred_speech_engine != "auto":
        ready = bool(which(preferred_speech_engine))
        return ActionAvailability(
            ready,
            f"Voz: {preferred_speech_engine}"
            if ready else f"No está instalado: {preferred_speech_engine}",
        )
    if command == "speak" and not (which("spd-say") or which("espeak-ng") or which("espeak")):
        return ActionAvailability(False, "No hay motor de voz compatible")
    if command == "paste":
        tools = ("wtype", "ydotool") if wayland else ("xdotool",)
        if not any(which(tool) for tool in tools):
            return ActionAvailability(True, "Copiará sin pegar automáticamente", True)
    return ActionAvailability(True, "Disponible")
