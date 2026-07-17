"""Desktop capability and action integration policies."""

from __future__ import annotations

import json
import locale
import subprocess
import urllib.request
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
    ocr_languages: tuple[str, ...] = ()
    spelling_language: str = ""
    grammar_ready: bool = False
    wasi_ready: bool = False


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
    grammar_endpoint: str = "http://127.0.0.1:8010/v2/languages",
) -> RuntimeCapabilities:
    """Probe optional providers once; every operation is local and bounded."""
    ollama_model = ""
    if which("ollama"):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:11434/api/tags", timeout=0.7
            ) as response:
                body = json.loads(response.read(1_000_001))
            names = [
                str(item.get("name", "")).strip()
                for item in body.get("models", [])
                if isinstance(item, dict) and item.get("name")
            ]
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
                for value in (locale_name, "es_CL", "es_ES", "es", "en_US", "en_GB")
                if value
            )
        )
        spelling_language = next(
            (language for language in candidates if enchant.dict_exists(language)), ""
        )
    except (ImportError, OSError, RuntimeError):
        pass

    grammar_ready = False
    try:
        with urllib.request.urlopen(grammar_endpoint, timeout=0.5) as response:
            response.read(64)
        grammar_ready = True
    except (OSError, ValueError):
        pass

    return RuntimeCapabilities(
        ollama_model=ollama_model,
        ocr_languages=ocr_languages,
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
) -> ActionAvailability:
    services = dbus_services or set()
    if command == "textpik-history" and not history_enabled:
        return ActionAvailability(False, "Activa el historial privado en Configuración")
    if command == "print" and not which("lp"):
        return ActionAvailability(False, "Requiere CUPS (comando lp)")
    if command == "ollama":
        if not which("ollama"):
            return ActionAvailability(False, "Ollama no está instalado")
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
    if command == "ocr-region" and not (
        which("spectacle")
        or which("gnome-screenshot")
        or (which("grim") and which("slurp"))
        or "org.freedesktop.portal.Desktop" in services
    ):
        return ActionAvailability(False, "No hay capturador de región compatible")
    if command in {"ocr-image", "ocr-region"} and ocr_degraded:
        return ActionAvailability(True, "OCR disponible sin español", True)
    if command in {"klipper-save", "klipper-menu"}:
        ready = kde and "org.kde.klipper" in services
        return ActionAvailability(ready, "Klipper no está disponible" if not ready else "Integración Klipper")
    if command == "kdeconnect":
        ready = bool(which("kdeconnect-cli")) or bool(
            {"org.kde.kdeconnect", "org.gnome.Shell.Extensions.GSConnect"} & services
        )
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
    if command == "speak" and not (which("spd-say") or which("espeak-ng") or which("espeak")):
        return ActionAvailability(False, "No hay motor de voz compatible")
    if command == "paste":
        tools = ("wtype", "ydotool") if wayland else ("xdotool",)
        if not any(which(tool) for tool in tools):
            return ActionAvailability(True, "Copiará sin pegar automáticamente", True)
    return ActionAvailability(True, "Disponible")
