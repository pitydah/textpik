"""Desktop capability and action integration policies."""

from __future__ import annotations

import json
import locale
import re
import subprocess
import urllib.request
import ipaddress
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from shutil import which


# LanguageTool endpoint verdicts. These are surfaced verbatim in the settings
# diagnostics, so they are part of the user-visible contract.
GRAMMAR_ENDPOINT_LOCAL = "local"
GRAMMAR_ENDPOINT_REMOTE_OPT_IN = "remote-opt-in"
GRAMMAR_ENDPOINT_REMOTE_BLOCKED = "remote-blocked"
GRAMMAR_ENDPOINT_INSECURE_REMOTE = "insecure-remote"
GRAMMAR_ENDPOINT_INVALID = "invalid"
GRAMMAR_ENDPOINT_UNREACHABLE = "unreachable"


# Plain HTTP to a remote LanguageTool is allowed only for address ranges TextPik
# explicitly defines as local-link/private LAN. Do not delegate this security
# boundary to `ipaddress.is_private`: its meaning is "not globally reachable"
# and its classifications have changed between Python releases.
_PRIVATE_LAN_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    )
)


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
    grammar_endpoint_state: str = GRAMMAR_ENDPOINT_INVALID
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


def _local_http_endpoint(endpoint: str) -> bool:
    """Return True only for explicit HTTP(S) loopback endpoints.

    This is the Ollama product invariant: the runtime is local by definition, so
    the policy is a constant rather than a user preference. LanguageTool has a
    different contract and deliberately does not reuse this function.
    """
    try:
        parsed = urlsplit(str(endpoint or "").strip())
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )


def _host_is_loopback(hostname: str) -> bool:
    host = str(hostname or "").strip().lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_is_private(hostname: str) -> bool:
    """Return True for hosts that can be shown to stay on the local network.

    Deliberately conservative, because this predicate is what downgrades the
    HTTPS requirement: it admits an IP literal only when the address itself is
    private, and a name only when the name is reserved for private use (RFC 6761
    ``.localhost``, RFC 6762 mDNS ``.local``, ICANN-reserved ``.internal``, and
    ``.home.arpa`` from RFC 8375, the standardised home-network domain). Every
    other suffix is treated as public, so plain HTTP is refused.

    Two things this must not grow into:

    - No DNS resolution. A lookup here would add latency to a probe that runs on
      the settings path, and it would be unsound anyway: the answer could change
      between the check and the request, which is the classic DNS rebinding /
      TOCTOU hole. Suffix matching is decided on the user's literal input.
    - No de facto conventions. ``.lan`` is widely used in home setups but is not
      reserved by anyone, so it cannot be treated as a guarantee of private
      scope. Someone serving LanguageTool on ``grammar.lan`` should use
      ``https://grammar.lan/...`` or the private IP directly.
    """
    host = str(hostname or "").strip().lower()
    if _host_is_loopback(host):
        return True
    if (
        host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".home.arpa")
    ):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        address.version == network.version and address in network
        for network in _PRIVATE_LAN_NETWORKS
    )


def grammar_endpoint_verdict(
    endpoint: str, *, allow_remote: bool = False
) -> tuple[bool, str]:
    """Decide whether a LanguageTool probe may contact ``endpoint``.

    LanguageTool is not loopback-only the way Ollama is: a NAS, a VPS or a
    deliberately chosen public service is a legitimate deployment. So the
    policy is an explicit user opt-in, defaulting to fail-closed.

    Returns ``(allowed, reason)``. The reason is a stable diagnostic string,
    not a boolean, because "blocked" and "reached the server and it was down"
    need very different words in the settings dialog.
    """
    try:
        parsed = urlsplit(str(endpoint or "").strip())
    except ValueError:
        return False, GRAMMAR_ENDPOINT_INVALID
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, GRAMMAR_ENDPOINT_INVALID
    if _host_is_loopback(parsed.hostname):
        # Loopback stays allowed regardless of the opt-in: it is the default
        # deployment and the traffic never leaves the machine.
        return True, GRAMMAR_ENDPOINT_LOCAL
    if not allow_remote:
        return False, GRAMMAR_ENDPOINT_REMOTE_BLOCKED
    # Opted in. Plain HTTP stays acceptable only for a private LAN host; a
    # public host must be TLS so the text is not cleartext on the wire.
    if parsed.scheme != "https" and not _host_is_private(parsed.hostname):
        return False, GRAMMAR_ENDPOINT_INSECURE_REMOTE
    return True, GRAMMAR_ENDPOINT_REMOTE_OPT_IN


def probe_runtime_capabilities(
    *,
    preferred_ollama_model: str = "",
    ollama_endpoint: str = "http://127.0.0.1:11434/api/generate",
    grammar_endpoint: str = "http://127.0.0.1:8010/v2/languages",
    grammar_allow_remote: bool = False,
    preferred_spelling_language: str = "auto",
) -> RuntimeCapabilities:
    """Probe optional providers once; every operation is local and bounded."""
    ollama_model = ""
    ollama_models: tuple[str, ...] = ()
    try:
        if not _local_http_endpoint(ollama_endpoint):
            raise ValueError("Ollama capability probes are loopback-only")
        parsed = urlsplit(ollama_endpoint)
        tags_endpoint = urlunsplit(
            (parsed.scheme, parsed.netloc, "/api/tags", "", "")
        )
        with urllib.request.urlopen(tags_endpoint, timeout=0.7) as response:
            body = json.loads(response.read(1_000_001))
        # A local service can answer with an error object or a bare scalar.
        # Validate the shape before reading it: body.get() on a list raises
        # AttributeError, which this handler does not cover.
        if not isinstance(body, dict):
            raise ValueError("Ollama /api/tags returned a non-object payload")
        raw_models = body.get("models", [])
        if not isinstance(raw_models, list):
            raise ValueError("Ollama /api/tags returned a non-list 'models'")
        names = [
            str(item.get("name", "")).strip()
            for item in raw_models
            if isinstance(item, dict) and item.get("name")
        ]
        ollama_models = tuple(names)
        ollama_model = _preferred_ollama_model(names, preferred_ollama_model)
    except (OSError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
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
    # Computed before the try so the verdict survives whatever the probe throws:
    # "blocked by policy" and "reached the server, it was down" must stay
    # distinguishable in the settings diagnostics.
    grammar_allowed, grammar_endpoint_state = grammar_endpoint_verdict(
        grammar_endpoint, allow_remote=bool(grammar_allow_remote)
    )
    # A blocked endpoint opens no socket at all. The probe carries no user text,
    # but the URL itself can name a remote host, so skipping the request is what
    # makes "no request leaves the machine" literally true.
    if grammar_allowed:
        try:
            grammar_probe_endpoint = (
                grammar_endpoint.removesuffix("/check") + "/languages"
                if grammar_endpoint.endswith("/check")
                else grammar_endpoint
            )
            with urllib.request.urlopen(grammar_probe_endpoint, timeout=0.5) as response:
                raw_languages = response.read(1_000_001)
            body = json.loads(raw_languages)
            # A proxy error page decodes to an object; body[:200] on a dict would
            # otherwise raise TypeError. Reject the shape explicitly so the failure
            # is a clear "unavailable" rather than a silent misparse.
            if not isinstance(body, list):
                raise ValueError("LanguageTool probe returned a non-list payload")
            grammar_languages = tuple(
                str(item.get("longCode") or item.get("code") or "").strip()
                for item in body[:200]
                if isinstance(item, dict)
                and (item.get("longCode") or item.get("code"))
            )
            grammar_ready = True
        except (OSError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
            grammar_endpoint_state = GRAMMAR_ENDPOINT_UNREACHABLE

    return RuntimeCapabilities(
        ollama_model=ollama_model,
        ollama_models=ollama_models,
        ocr_languages=ocr_languages,
        grammar_languages=grammar_languages,
        spelling_language=spelling_language,
        grammar_ready=grammar_ready,
        grammar_endpoint_state=grammar_endpoint_state,
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
