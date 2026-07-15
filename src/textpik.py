#!/usr/bin/env python3
"""
textpik - Barra emergente de acciones al seleccionar texto.

Soporta X11 mediante QClipboard.Selection y KDE Plasma Wayland mediante
Klipper por D-Bus. Evita shell=True para acciones configurables.
"""

import json
import html
import logging
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import ctypes
import time
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote_plus

try:
    from textpik_core.actions import (
        PermissionStore,
        fuzzy_score,
        migrate_action,
        stable_action_id,
        transform_text,
    )
    from textpik_core.anchors import (
        AnchorResolver,
        hyprland_cursor_anchor,
        place_popup,
        stabilize_popup_position,
        sway_cursor_anchor,
    )
    from textpik_core.atspi import AtspiSelectionBackend
    from textpik_core.extensions import inspect_local_extensions
    from textpik_core.models import AnchorSource, PopupAnchor, SelectionContext
    from textpik_core.integration import action_availability
    from textpik_core.execution import is_terminal_execution as core_is_terminal_execution
    from textpik_core.performance import PerformanceTracker
    from textpik_core.platform import (
        command_exists,
        detect_desktop_environment,
        find_available_terminal,
        is_kde_desktop,
        is_wayland_session,
    )
    from textpik_core.planning import ContextSnapshot, plan_actions
    from textpik_core.profiles import resolve_profile
    from textpik_core.selection import evaluate_selection_intent
    from textpik_core.spelling import SpellingService
    from textpik_core.grammar import LanguageToolService, apply_suggestions
    from textpik_core.insights import local_insight, text_statistics
    from textpik_core.ranking import LocalActionRanker
    from textpik_core.undo import UndoManager
    from textpik_core.providers import OllamaProvider, TesseractProvider
    from textpik_core.history import HistoryStore
    from textpik_core.automation import automation_matches, preview_automation
    from textpik_core.wasi import run_wasi
    from textpik_core.settings import (
        DEFAULT_SETTINGS,
        normalize_bool as normalize_core_bool,
        normalize_settings as normalize_core_settings,
    )
    from textpik_core.storage import read_json, write_json_atomic
    from textpik_core.popup_state import PopupPhase, PopupStateMachine
    from textpik_core.text import build_command_argv, classify_text, normalize_url
except ModuleNotFoundError:  # Imported as src.textpik from a source checkout.
    from .textpik_core.actions import (
        PermissionStore,
        fuzzy_score,
        migrate_action,
        stable_action_id,
        transform_text,
    )
    from .textpik_core.anchors import (
        AnchorResolver,
        hyprland_cursor_anchor,
        place_popup,
        stabilize_popup_position,
        sway_cursor_anchor,
    )
    from .textpik_core.atspi import AtspiSelectionBackend
    from .textpik_core.extensions import inspect_local_extensions
    from .textpik_core.models import AnchorSource, PopupAnchor, SelectionContext
    from .textpik_core.integration import action_availability
    from .textpik_core.execution import (
        is_terminal_execution as core_is_terminal_execution,
    )
    from .textpik_core.performance import PerformanceTracker
    from .textpik_core.platform import (
        command_exists,
        detect_desktop_environment,
        find_available_terminal,
        is_kde_desktop,
        is_wayland_session,
    )
    from .textpik_core.planning import ContextSnapshot, plan_actions
    from .textpik_core.profiles import resolve_profile
    from .textpik_core.selection import evaluate_selection_intent
    from .textpik_core.spelling import SpellingService
    from .textpik_core.grammar import LanguageToolService, apply_suggestions
    from .textpik_core.insights import local_insight, text_statistics
    from .textpik_core.ranking import LocalActionRanker
    from .textpik_core.undo import UndoManager
    from .textpik_core.providers import OllamaProvider, TesseractProvider
    from .textpik_core.history import HistoryStore
    from .textpik_core.automation import automation_matches, preview_automation
    from .textpik_core.wasi import run_wasi
    from .textpik_core.settings import (
        DEFAULT_SETTINGS,
        normalize_bool as normalize_core_bool,
        normalize_settings as normalize_core_settings,
    )
    from .textpik_core.storage import read_json, write_json_atomic
    from .textpik_core.popup_state import PopupPhase, PopupStateMachine
    from .textpik_core.text import build_command_argv, classify_text, normalize_url


def is_wayland():
    return is_wayland_session(os.environ)


def is_qt_wayland():
    app = QApplication.instance() if "QApplication" in globals() else None
    if app is None:
        return is_wayland() and os.environ.get("QT_QPA_PLATFORM", "") != "xcb"
    return app.platformName().lower().startswith("wayland")


def desktop_environment():
    return detect_desktop_environment(os.environ)


def is_kde():
    return is_kde_desktop(desktop_environment())


def available_terminal():
    return find_available_terminal(available=check_command)


def check_command(cmd):
    return command_exists(cmd)


def clipboard_has_text(clipboard=None):
    """Handle headless and initializing clipboard backends safely."""
    try:
        clipboard = clipboard or QApplication.clipboard()
        mime_data = clipboard.mimeData() if clipboard is not None else None
        return bool(mime_data is not None and mime_data.hasText())
    except RuntimeError:
        return False


def check_python_module(module):
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def install_python_or_system_package(python_module, pacman_package, pip_package):
    if check_python_module(python_module):
        return True

    install_hint = textwrap.dedent(
        f"""
        Falta {python_module}.

        Instala la dependencia y vuelve a ejecutar textpik:
          pip: python3 -m pip install --user {pip_package}
          Arch: sudo pacman -S --needed {pacman_package}
          Debian/Ubuntu: sudo apt install python3-{pip_package.lower()}
          Fedora: sudo dnf install python3-{pip_package.lower()}
          openSUSE: sudo zypper install python3-{pip_package.lower()}
        """
    ).strip()

    print(install_hint)
    if not sys.stdin.isatty():
        if check_command("kdialog"):
            subprocess.Popen(["kdialog", "--error", install_hint])
        elif check_command("zenity"):
            subprocess.Popen(["zenity", "--error", "--text", install_hint])
        elif check_command("notify-send"):
            subprocess.Popen(["notify-send", "textpik", install_hint])
    # Dependency installation is deliberately never performed while importing
    # the application. Package managers and privilege prompts belong to the
    # distro/package workflow, not to TextPik's startup path.
    return False


if not install_python_or_system_package("PySide6", "pyside6", "PySide6"):
    sys.exit(1)


from PySide6.QtCore import (  # noqa: E402
    ClassInfo,
    QLockFile,
    QObject,
    QPoint,
    QProcess,
    QRunnable,
    QRectF,
    QSize,
    QThreadPool,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (  # noqa: E402
    QAction,
    QClipboard,
    QColor,
    QCursor,
    QDesktopServices,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "textpik"
APP_VERSION = "0.5.0-rc.1"
GITHUB_PROFILE_URL = "https://github.com/pitydah"
GITHUB_SPONSORS_URL = "https://github.com/sponsors/pitydah"
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ROOTS = [
    Path(getattr(sys, "_MEIPASS", _SOURCE_ROOT)),
    _SOURCE_ROOT,
    Path(sys.prefix) / "share" / APP_NAME,
    Path("/app/share") / APP_NAME,
    Path("/usr/local/share") / APP_NAME,
    Path("/usr/share") / APP_NAME,
]
PROJECT_ROOT = next(
    (root for root in _RUNTIME_ROOTS if (root / "assets").is_dir()),
    _SOURCE_ROOT,
)
ASSETS_DIR = PROJECT_ROOT / "assets"
APP_ASSETS_DIR = ASSETS_DIR / "app"
ACTIONS_ASSETS_DIR = ASSETS_DIR / "actions"
TRAY_ASSETS_DIR = ASSETS_DIR / "tray"

APP_ICON_FILE = APP_ASSETS_DIR / "textpik.svg"
TRAY_ICON_FILE = TRAY_ASSETS_DIR / "textpik-tray.svg"

CONFIG_DIR = Path.home() / ".config" / APP_NAME
CACHE_DIR = Path.home() / ".cache" / APP_NAME
ACTIONS_FILE = CONFIG_DIR / "actions.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "textpik.desktop"
PERMISSIONS_FILE = CONFIG_DIR / "permissions.json"
EXTENSIONS_DIR = Path.home() / ".local" / "share" / APP_NAME / "extensions"
LOG_FILE = CACHE_DIR / "textpik.log"
RANKING_FILE = CONFIG_DIR / "ranking.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
AUTOMATIONS_FILE = CONFIG_DIR / "automations.json"

DEFAULT_ACTIONS = [
    {"name": "Copiar", "icon": "copy.svg", "cmd": "copy", "enabled": True},
    {"name": "Pegar", "icon": "paste.svg", "cmd": "paste", "enabled": True},
    {
        "name": "Abrir link en una pestaña nueva",
        "icon": "open-link.svg",
        "cmd": "open-url",
        "enabled": True,
        "context": ["url"],
    },
    {
        "name": "Buscar en Google",
        "icon": "search-google.svg",
        "cmd": "xdg-open 'https://www.google.com/search?q={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Buscar en YouTube",
        "icon": "search-youtube.svg",
        "cmd": "xdg-open 'https://www.youtube.com/results?search_query={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Buscar en Google Maps",
        "icon": "search-maps.svg",
        "cmd": "xdg-open 'https://www.google.com/maps?q={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Preguntar a ChatGPT",
        "icon": "chatgpt.svg",
        "cmd": "xdg-open 'https://chatgpt.com/?q={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Preguntar a DeepSeek",
        "icon": "deepseek.svg",
        "cmd": "xdg-open 'https://chat.deepseek.com/?q={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Buscar en DuckDuckGo",
        "icon": "duckduckgo.svg",
        "cmd": "xdg-open 'https://duckduckgo.com/?q={url}'",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Ejecutar en terminal",
        "icon": "terminal.svg",
        "cmd": "terminal",
        "enabled": True,
        "context": ["text", "code", "ip", "number"],
    },
    {"name": "Imprimir", "icon": "print.svg", "cmd": "print", "enabled": True},
    {
        "name": "Traducir con Google",
        "icon": "translate-with-google.svg",
        "cmd": "xdg-open 'https://translate.google.com/?sl=auto&tl=es&text={url}'",
        "enabled": True,
    },
    {
        "name": "Abrir en Ollama",
        "icon": "open-in-ollama.svg",
        "cmd": "ollama",
        "enabled": True,
    },
    {
        "name": "Enviar al movil",
        "icon": "kdeconnect.svg",
        "cmd": "kdeconnect",
        "enabled": True,
    },
    {
        "name": "Guardar en Klipper",
        "icon": "klipper.svg",
        "cmd": "klipper-save",
        "enabled": True,
    },
    {
        "name": "Historial Klipper",
        "icon": "klipper-history.svg",
        "cmd": "klipper-menu",
        "enabled": True,
    },
    {
        "name": "Contar palabras",
        "icon": "counter.svg",
        "cmd": "count",
        "enabled": True,
    },
    {
        "name": "Corrección ortográfica",
        "icon": "spellcheck.svg",
        "cmd": "spellcheck",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Calcular o convertir",
        "icon": "counter.svg",
        "cmd": "insight",
        "enabled": True,
        "context": ["number", "currency", "text"],
    },
    {
        "name": "Revisar gramática",
        "icon": "spellcheck.svg",
        "cmd": "grammar",
        "enabled": True,
        "context": ["text"],
        "permissions": ["network"],
    },
    {
        "name": "Deshacer cambio",
        "icon": "paste.svg",
        "cmd": "undo",
        "enabled": True,
        "context": ["text"],
    },
    {
        "name": "Historial privado de TextPik",
        "icon": "klipper-history.svg",
        "cmd": "textpik-history",
        "enabled": True,
    },
    {
        "name": "OCR de imagen",
        "icon": "dictionary.svg",
        "cmd": "ocr-image",
        "enabled": True,
        "permissions": ["filesystem", "process"],
    },
    {
        "name": "OCR de región de pantalla",
        "icon": "dictionary.svg",
        "cmd": "ocr-region",
        "enabled": True,
        "permissions": ["filesystem", "process"],
    },
    {
        "name": "MAYUSCULAS",
        "icon": "uppercase.svg",
        "cmd": "uppercase",
        "enabled": True,
    },
    {
        "name": "minusculas",
        "icon": "lowercase.svg",
        "cmd": "lowercase",
        "enabled": True,
    },
    {
        "name": "Capitalizar",
        "icon": "capitalize.svg",
        "cmd": "capitalize",
        "enabled": True,
    },
    {
        "name": "Quitar saltos",
        "icon": "remove-breaks.svg",
        "cmd": "remove-breaks",
        "enabled": True,
    },
    {
        "name": "Diccionario RAE",
        "icon": "dictionary.svg",
        "cmd": "xdg-open 'https://dle.rae.es/{url}'",
        "enabled": True,
    },
]

KWIN_CURSOR_DBUS_CANDIDATES = (
    ("org.kde.KWin", "/Cursor"),
    ("org.kde.KWin", "/org/kde/KWin/Cursor"),
    ("org.kde.kwin", "/Cursor"),
)
CURSOR_BRIDGE_SERVICE = "org.textpik.CursorBridge"
CURSOR_BRIDGE_PATH = "/Cursor"
CURSOR_BRIDGE_INTERFACE = "org.textpik.CursorBridge"
CURSOR_BRIDGE_MAX_AGE_SECONDS = 3.0

logger = logging.getLogger(APP_NAME)
kwin_bridge_cursor = None
_SHUTDOWN_GUARDS = []


def normalize_color(value, fallback):
    color = QColor(str(value))
    return color.name() if color.isValid() else fallback


def normalize_bool(value, fallback=False):
    return normalize_core_bool(value, fallback)


def normalize_settings(settings):
    return normalize_core_settings(settings, color_normalizer=normalize_color)


def load_settings():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    needs_write = True
    if SETTINGS_FILE.exists():
        try:
            persisted = read_json(SETTINGS_FILE)
            settings = normalize_settings(persisted)
            needs_write = settings != persisted
        except Exception as exc:
            logger.debug("No se pudo cargar settings.json: %s", exc)
            settings = dict(DEFAULT_SETTINGS)
    else:
        settings = dict(DEFAULT_SETTINGS)

    if needs_write:
        write_json_atomic(SETTINGS_FILE, settings)
    return settings


def setup_logging(settings):
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not settings.get("log_enabled", True):
        logger.addHandler(logging.NullHandler())
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=512 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)


class X11Pointer:
    BUTTON_MASKS = 0x100 | 0x200 | 0x400 | 0x800 | 0x1000

    def __init__(self):
        self.x11 = None
        try:
            self.x11 = ctypes.CDLL("libX11.so.6")
            self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self.x11.XOpenDisplay.restype = ctypes.c_void_p
            self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self.x11.XQueryPointer.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_uint),
            ]
            self.x11.XQueryPointer.restype = ctypes.c_int
            self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            self.x11.XCloseDisplay.restype = ctypes.c_int
        except OSError:
            self.x11 = None

    def state(self):
        if self.x11 is None or not os.environ.get("DISPLAY"):
            return None

        display = self.x11.XOpenDisplay(None)
        if not display:
            return None

        try:
            root = self.x11.XDefaultRootWindow(display)
            root_return = ctypes.c_ulong()
            child_return = ctypes.c_ulong()
            root_x = ctypes.c_int()
            root_y = ctypes.c_int()
            win_x = ctypes.c_int()
            win_y = ctypes.c_int()
            mask = ctypes.c_uint()

            ok = self.x11.XQueryPointer(
                display,
                root,
                ctypes.byref(root_return),
                ctypes.byref(child_return),
                ctypes.byref(root_x),
                ctypes.byref(root_y),
                ctypes.byref(win_x),
                ctypes.byref(win_y),
                ctypes.byref(mask),
            )
            if not ok:
                return None
            return root_x.value, root_y.value, mask.value
        finally:
            self.x11.XCloseDisplay(display)


class ProcessFilter:
    def __init__(self, settings):
        self.settings = settings

    def is_foreground_process_game(self):
        if not self.settings.get("disable_in_games", False):
            return False

        pid = self._active_window_pid()
        if pid <= 0:
            return False

        return self._cmdline_matches(pid) or self._maps_look_like_game(pid)

    def _active_window_pid(self):
        if not check_command("xdotool"):
            return -1
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True,
                text=True,
                timeout=0.4,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception as exc:
            logger.debug("No se pudo obtener PID activo: %s", exc)
        return -1

    def _cmdline_matches(self, pid):
        keywords = self.settings.get("game_filter_keywords", [])
        try:
            content = (
                Path(f"/proc/{pid}/cmdline")
                .read_text(encoding="utf-8", errors="ignore")
                .lower()
            )
        except OSError:
            return False
        return any(keyword in content for keyword in keywords)

    def _maps_look_like_game(self, pid):
        try:
            lines = (
                Path(f"/proc/{pid}/maps")
                .read_text(encoding="utf-8", errors="ignore")
                .lower()
                .splitlines()
            )
        except OSError:
            return False

        hits = 0
        for line in lines:
            if any(token in line for token in ("dxvk", "vkd3d", "libvulkan.so")):
                hits += 1
                if hits >= 2:
                    return True
        return False

    def _active_window_class(self):
        if not check_command("xdotool"):
            return ""
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowclassname"],
                capture_output=True,
                text=True,
                timeout=0.4,
            )
            return result.stdout.strip().lower() if result.returncode == 0 else ""
        except Exception as exc:
            logger.debug("No se pudo obtener clase de ventana activa: %s", exc)
            return ""

    def is_foreground_process_blocked(self):
        if not self.settings.get("blocked_apps_enabled", False):
            return False
        blocked = self.settings.get("blocked_apps", [])
        if not blocked:
            return False
        wm_class = self._active_window_class()
        return self.matches_blocked_application(wm_class)

    def matches_blocked_application(self, application):
        """Match an AT-SPI application name without spawning desktop tools."""
        if not self.settings.get("blocked_apps_enabled", False):
            return False
        name = str(application or "").strip().casefold()
        blocked = self.settings.get("blocked_apps", [])
        return bool(name and any(token in name for token in blocked))

    def is_foreground_activity_blocked(self):
        if not self.settings.get("blocked_activities_enabled", False):
            return False
        blocked = self.settings.get("blocked_activities", [])
        if not blocked:
            return False
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface

            bus = QDBusConnection.sessionBus()
            iface = QDBusInterface(
                "org.kde.ActivityManager",
                "/ActivityManager/Activities",
                "org.kde.ActivityManager.Activities",
                bus,
            )
            if iface.isValid():
                reply = iface.call("CurrentActivity")
                if reply.arguments():
                    current_id = str(reply.arguments()[0])
                    short_id = (
                        current_id.split("-")[0] if "-" in current_id else current_id
                    )
                    return any(b in current_id or b in short_id for b in blocked)
        except Exception as exc:
            logger.debug("No se pudo consultar actividad: %s", exc)
        return False


def load_icon(path, fallback_theme=None):
    icon_path = Path(path)
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    if icon.isNull() and icon_path.suffix.lower() == ".svg":
        for size in (256, 128, 64, 48, 32, 24, 16):
            png_path = icon_path.with_name(f"{icon_path.stem}-{size}.png")
            if png_path.exists():
                icon = QIcon(str(png_path))
                if not icon.isNull():
                    break
    if icon.isNull() and fallback_theme:
        icon = QIcon.fromTheme(fallback_theme)
    return icon


def resolve_action_icon(icon_name, variant=None):
    icon_path = Path(icon_name)
    if icon_path.is_absolute():
        return load_icon(icon_path, icon_path.stem), False

    base_path = ACTIONS_ASSETS_DIR / icon_name
    # Los SVG base se recolorean al renderizar. Esto evita depender de las
    # variantes -black/-white (algunas provienen de fuentes distintas) y
    # garantiza contraste con cualquier tema personalizado.
    icon = load_icon(base_path, icon_name)
    return icon, True


def color_luminance(color_name):
    color = QColor(color_name)
    if not color.isValid():
        color = QColor("#f7f7f7")
    return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255


def icon_color_for_background(color_name):
    return (
        QColor("#000000") if color_luminance(color_name) >= 0.5 else QColor("#ffffff")
    )


def icon_variant_for_background(color_name):
    return "black" if color_luminance(color_name) >= 0.5 else "white"


def recolor_icon(icon, color, size):
    pixmap = icon.pixmap(size, size)
    if pixmap.isNull():
        return icon
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), color)
    painter.end()
    return QIcon(result)


def qt_dbus_available():
    try:
        from PySide6 import QtDBus  # noqa: F401

        return True
    except ImportError:
        return False


def log_cursor_position_diagnostics(qt_platform):
    logger.info(
        "Diagnostico cursor: session=%s wayland=%s qt_platform=%s display=%s wayland_display=%s",
        os.environ.get("XDG_SESSION_TYPE", ""),
        is_wayland(),
        qt_platform,
        bool(os.environ.get("DISPLAY")),
        bool(os.environ.get("WAYLAND_DISPLAY")),
    )

    if not is_wayland():
        logger.info("Diagnostico cursor: sesion no Wayland, se usara posicion X11/Qt")
        return

    if not is_kde():
        logger.info(
            "Diagnostico cursor: Wayland no KDE; se usara posicion segura de fallback"
        )
        return

    if not qt_dbus_available():
        logger.info(
            "Diagnostico cursor: QtDBus no disponible; se usara fallback Wayland"
        )
        return

    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

        bus = QDBusConnection.sessionBus()
        any_valid = False
        for service, path in KWIN_CURSOR_DBUS_CANDIDATES:
            iface = QDBusInterface(service, path, "org.kde.KWin.Cursor", bus)
            if not iface.isValid():
                logger.info("Diagnostico cursor: D-Bus invalido %s %s", service, path)
                continue

            any_valid = True
            reply = iface.call("cursorPos")
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                logger.info(
                    "Diagnostico cursor: cursorPos fallo en %s %s", service, path
                )
            else:
                logger.info(
                    "Diagnostico cursor: cursorPos disponible en %s %s", service, path
                )
                return

        if not any_valid:
            logger.info(
                "Diagnostico cursor: KWin no expone rutas D-Bus de cursor conocidas"
            )
        else:
            logger.info(
                "Diagnostico cursor: rutas D-Bus existen pero cursorPos no respondio"
            )
    except Exception as exc:
        logger.warning("Diagnostico cursor: error consultando KWin D-Bus: %s", exc)


def offer_install_system_packages(packages, parent=None):
    packages = sorted(set(packages))
    if not packages:
        return True

    logger.warning(
        "Integraciones opcionales no disponibles: %s",
        ", ".join(packages),
    )
    return False


def check_runtime_dependencies(parent=None):
    optional_packages = []

    if is_qt_wayland():
        if is_kde() and not qt_dbus_available() and not check_command("wl-paste"):
            logger.warning(
                "QtDBus y wl-paste no están disponibles; la detección de "
                "selección en KDE Wayland quedará degradada"
            )
        if not check_command("wtype") and not check_command("ydotool"):
            optional_packages.append("wtype")
        if not check_command("wl-paste"):
            optional_packages.append("wl-clipboard")
    elif not check_command("xdotool"):
        optional_packages.append("xdotool")

    if available_terminal() is None:
        optional_packages.append("konsole" if is_kde() else "gnome-terminal")

    if not check_command("xdg-open"):
        optional_packages.append("xdg-utils")

    offer_install_system_packages(optional_packages, parent)


class BaseSelectionMonitor(QObject):
    selection_changed = Signal()
    selection_cleared = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or dict(DEFAULT_SETTINGS)
        self._active = True
        self._last_text = ""
        self._force_emit = False
        self._last_emit_text = ""
        self._last_emit_at = 0.0
        self._suppress_events_until = 0.0
        self._revision = 0
        self._scheduled_revision = 0
        self._pointer = X11Pointer()
        self.timer_debounce = QTimer(self)
        self.timer_debounce.setSingleShot(True)
        self.timer_debounce.timeout.connect(self._debounce_expired)

    def _next_revision(self):
        self._revision += 1
        return self._revision

    def _schedule_read(self, force_emit=True, revision=None):
        if self._active:
            revision = revision if revision is not None else self._next_revision()
            if revision != self._revision:
                return
            self._scheduled_revision = revision
            self._force_emit = self._force_emit or force_emit
            delay = max(70, int(self.settings.get("popup_delay_ms", 0)))
            self.timer_debounce.start(delay)

    def _selection_event(self, *args):
        if time.monotonic() < self._suppress_events_until:
            logger.debug("Evento de selección propio ignorado")
            return
        if self._secondary_button_pressed():
            self.suppress_events(500)
            self._next_revision()
            logger.debug("Evento de selección ignorado durante clic secundario")
            return
        # Wayland notifications may repeat for the same PRIMARY payload when a
        # context menu opens. A changed payload is sufficient to prove selection.
        revision = self._next_revision()
        self._schedule_read(force_emit=not is_wayland(), revision=revision)

    def _secondary_button_pressed(self):
        try:
            if QApplication.mouseButtons() & Qt.RightButton:
                return True
        except Exception:
            pass
        state = self._pointer.state()
        return bool(state is not None and state[2] & 0x400)

    def _primary_button_pressed(self):
        try:
            if QApplication.mouseButtons() & Qt.LeftButton:
                return True
        except Exception:
            pass
        state = self._pointer.state()
        return bool(state is not None and state[2] & 0x100)

    def suppress_events(self, milliseconds=400):
        self._suppress_events_until = max(
            self._suppress_events_until,
            time.monotonic() + (milliseconds / 1000),
        )

    def _read_selection_text(self):
        return ""

    def _debounce_expired(self):
        revision = self._scheduled_revision
        if revision != self._revision:
            return
        if self._secondary_button_pressed():
            self._force_emit = False
            self.suppress_events(500)
            self._next_revision()
            logger.debug("Lectura de selección cancelada por clic secundario")
            return
        if self._primary_button_pressed():
            self.timer_debounce.start(45)
            return
        self._accept_selection_text(self._read_selection_text(), revision)

    def _accept_selection_text(self, raw_text, revision=None):
        """Validate and emit a completed synchronous or asynchronous read."""
        revision = self._revision if revision is None else revision
        if not self._active or revision != self._revision:
            logger.debug("Resultado de selección obsoleto descartado: %s", revision)
            return False
        text = str(raw_text or "").strip()
        now = time.monotonic()
        should_emit = self._force_emit or text != self._last_text
        self._force_emit = False
        if not text:
            if self._last_text:
                logger.info("Seleccion primaria vacia; ocultando popup")
            self._last_text = ""
            self.selection_cleared.emit()
            return True

        max_length = self.settings.get("max_selection_length", 5000)
        if len(text) > max_length:
            logger.info(
                "Seleccion ignorada por tamano: %d caracteres (max %d)",
                len(text),
                max_length,
            )
            self._last_text = ""
            self.selection_cleared.emit()
            return True

        if text and should_emit:
            if text == self._last_emit_text and now - self._last_emit_at < 0.45:
                logger.debug("Seleccion duplicada ignorada")
                return True
            logger.info("Seleccion detectada: %d caracteres", len(text))
            self._last_text = text
            self._last_emit_text = text
            self._last_emit_at = now
            self.selection_changed.emit()
        return True

    def get_last_text(self):
        return self._last_text

    def pause(self):
        self._active = False
        self._next_revision()
        self.timer_debounce.stop()

    def resume(self):
        self._active = True


class X11SelectionMonitor(BaseSelectionMonitor):
    def __init__(self, settings=None):
        super().__init__(settings)
        self.clipboard = QApplication.clipboard()
        if self.clipboard.supportsSelection():
            self.clipboard.selectionChanged.connect(self._selection_event)
        else:
            QMessageBox.warning(
                None,
                "Seleccion no disponible",
                "Qt informa que PRIMARY selection no esta disponible en esta sesion.",
            )

    def _read_selection_text(self):
        return self.clipboard.text(QClipboard.Mode.Selection)


class WaylandSelectionMonitor(BaseSelectionMonitor):
    def __init__(self, settings=None):
        super().__init__(settings)
        self.iface = None
        self._dbus_monitor = None
        self._wl_paste_monitor = None
        self._wl_read_process = None
        self._wl_read_revision = 0
        self._ignore_next_wl_paste_event = True
        self._last_wl_paste_event_at = 0.0
        self._wl_restart_attempts = 0
        self.clipboard = QApplication.clipboard()
        self._use_wl_paste = check_command("wl-paste")
        if not self._use_wl_paste and self.clipboard.supportsSelection():
            self.clipboard.selectionChanged.connect(self._selection_event)

        self._start_wl_paste_primary_monitor()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(lambda: self._schedule_read(force_emit=False))
        if self.settings.get("enable_wayland_polling", True) and not self._use_wl_paste:
            self._poll_timer.start(500)

        if self._use_wl_paste or not qt_dbus_available():
            return

        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        self.bus = QDBusConnection.sessionBus()
        self.iface = QDBusInterface(
            "org.kde.klipper",
            "/klipper",
            "org.kde.klipper.klipper",
            self.bus,
        )
        self._start_klipper_signal_monitor()

    def _start_wl_paste_primary_monitor(self):
        if not check_command("wl-paste"):
            logger.info("wl-paste no disponible; no se puede observar PRIMARY Wayland")
            return

        if (
            self._wl_paste_monitor is not None
            and self._wl_paste_monitor.state() != QProcess.ProcessState.NotRunning
        ):
            return

        self._wl_paste_monitor = QProcess(self)
        self._wl_paste_monitor.readyReadStandardOutput.connect(
            self._on_wl_paste_monitor_output
        )
        self._wl_paste_monitor.finished.connect(self._on_wl_paste_monitor_finished)
        self._wl_paste_monitor.start(
            "wl-paste",
            [
                "--primary",
                "--watch",
                shutil.which("printf") or "printf",
                "textpik-selection-changed\n",
            ],
        )
        logger.info("Monitor wl-paste PRIMARY iniciado")

    def _on_wl_paste_monitor_finished(self, exit_code, exit_status):
        if not self._active or not self._use_wl_paste:
            return
        self._wl_restart_attempts += 1
        delay = min(30000, 1000 * (2 ** min(self._wl_restart_attempts - 1, 5)))
        logger.warning(
            "Monitor wl-paste termino (codigo=%s, estado=%s); reiniciando en %d ms",
            exit_code,
            exit_status,
            delay,
        )
        self._wl_paste_monitor = None
        QTimer.singleShot(delay, self._start_wl_paste_primary_monitor)

    def _stop_process(self, process):
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        process.terminate()
        if not process.waitForFinished(150):
            process.kill()
            process.waitForFinished(150)

    def pause(self):
        super().pause()
        self._poll_timer.stop()
        self._stop_process(self._wl_paste_monitor)
        self._stop_process(self._dbus_monitor)
        self._stop_process(self._wl_read_process)
        self._wl_paste_monitor = None
        self._dbus_monitor = None
        self._wl_read_process = None

    def resume(self):
        super().resume()
        self._ignore_next_wl_paste_event = True
        if self._use_wl_paste:
            self._start_wl_paste_primary_monitor()
        elif self.settings.get("enable_wayland_polling", True):
            self._poll_timer.start(500)
        if (
            not self._use_wl_paste
            and qt_dbus_available()
            and self._dbus_monitor is None
        ):
            self._start_klipper_signal_monitor()

    def _on_wl_paste_monitor_output(self):
        if self._wl_paste_monitor is None:
            return
        output = bytes(self._wl_paste_monitor.readAllStandardOutput())
        if output:
            self._wl_restart_attempts = 0
            now = time.monotonic()
            if self._ignore_next_wl_paste_event:
                self._ignore_next_wl_paste_event = False
                logger.info("Seleccion PRIMARY inicial ignorada")
                return
            if now - self._last_wl_paste_event_at < 0.08:
                logger.debug("Evento wl-paste duplicado ignorado")
                return
            self._last_wl_paste_event_at = now
            logger.info("Cambio de seleccion PRIMARY recibido desde wl-paste")
            self._selection_event()

    def _start_klipper_signal_monitor(self):
        if not check_command("dbus-monitor"):
            logger.info("dbus-monitor no disponible; se usara fallback por polling")
            return

        self._dbus_monitor = QProcess(self)
        self._dbus_monitor.readyReadStandardOutput.connect(self._on_dbus_monitor_output)
        self._dbus_monitor.start(
            "dbus-monitor",
            [
                "--session",
                "type='signal',path='/klipper',"
                "interface='org.kde.klipper.klipper',member='selectionChanged'",
            ],
        )

    def _on_dbus_monitor_output(self):
        if self._dbus_monitor is None:
            return
        output = bytes(self._dbus_monitor.readAllStandardOutput())
        if b"selectionChanged" in output:
            logger.info("Klipper selectionChanged recibido")
            self._selection_event()

    def _debounce_expired(self):
        if not self._use_wl_paste:
            super()._debounce_expired()
            return
        revision = self._scheduled_revision
        if revision != self._revision:
            return
        if self._secondary_button_pressed():
            self._force_emit = False
            self.suppress_events(500)
            self._next_revision()
            return
        if self._primary_button_pressed():
            self.timer_debounce.start(45)
            return
        if self._wl_read_process is not None and (
            self._wl_read_process.state() != QProcess.ProcessState.NotRunning
        ):
            return
        process = QProcess(self)
        self._wl_read_process = process
        self._wl_read_revision = revision
        process.finished.connect(self._on_wl_read_finished)
        process.start("wl-paste", ["--primary", "--no-newline"])

    def _on_wl_read_finished(self, exit_code, _exit_status):
        process, self._wl_read_process = self._wl_read_process, None
        revision, self._wl_read_revision = self._wl_read_revision, 0
        if process is None:
            return
        text = ""
        if exit_code == 0:
            text = bytes(process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            )
        else:
            error = bytes(process.readAllStandardError()).decode(
                "utf-8", errors="replace"
            ).strip()
            logger.debug("wl-paste no pudo leer PRIMARY: %s", error)
        process.deleteLater()
        if not self._active:
            return
        accepted = self._accept_selection_text(text, revision)
        if not accepted and self._scheduled_revision == self._revision:
            # An event arrived while wl-paste was still reading the previous
            # selection. Start one fresh read instead of showing stale text.
            self.timer_debounce.start(0)

    def _read_selection_text(self):
        if self._use_wl_paste:
            return ""

        if self.clipboard.supportsSelection():
            text = self.clipboard.text(QClipboard.Mode.Selection).strip()
            if text:
                return text

        return ""


def get_cursor_pos_wayland():
    global kwin_bridge_cursor

    if not is_kde():
        return None

    if kwin_bridge_cursor is not None:
        x, y, timestamp = kwin_bridge_cursor
        if time.monotonic() - timestamp <= CURSOR_BRIDGE_MAX_AGE_SECONDS:
            return x, y

    if not qt_dbus_available():
        return None

    try:
        from PySide6.QtCore import QPoint as QtPoint
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

        bus = QDBusConnection.sessionBus()

        for service, path in KWIN_CURSOR_DBUS_CANDIDATES:
            iface = QDBusInterface(service, path, "org.kde.KWin.Cursor", bus)
            if not iface.isValid():
                logger.debug(
                    "cursorPos D-Bus interfaz invalida en %s %s", service, path
                )
                continue

            reply = iface.call("cursorPos")
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                logger.debug("cursorPos D-Bus no disponible en %s %s", service, path)
                continue

            values = reply.arguments()
            if not values:
                continue
            pos = values[0]
            if isinstance(pos, QtPoint):
                logger.debug(
                    "cursorPos D-Bus obtenido via %s %s: %s,%s",
                    service,
                    path,
                    pos.x(),
                    pos.y(),
                )
                return pos.x(), pos.y()
            if isinstance(pos, (tuple, list)) and len(pos) >= 2:
                x, y = int(pos[0]), int(pos[1])
                logger.debug(
                    "cursorPos D-Bus obtenido via %s %s: %s,%s", service, path, x, y
                )
                return x, y
    except Exception as exc:
        logger.warning("cursorPos D-Bus error: %s", exc)
        return None

    if not getattr(get_cursor_pos_wayland, "_fallback_logged", False):
        logger.info(
            "No se pudo obtener la posicion del cursor via KWin D-Bus; usando fallback"
        )
        get_cursor_pos_wayland._fallback_logged = True
    return None


class CursorBridge(QObject):
    def update_cursor(self, x, y):
        global kwin_bridge_cursor
        first_update = kwin_bridge_cursor is None
        kwin_bridge_cursor = (int(x), int(y), time.monotonic())
        if first_update:
            logger.info("Cursor actualizado via KWin script: %s,%s", x, y)
        logger.debug("Cursor actualizado via KWin script: %s,%s", x, y)

    def notify_click_outside(self):
        logger.info("KWin notifico activacion de otra ventana")
        if hasattr(self, "_on_click_outside") and self._on_click_outside:
            self._on_click_outside()


def create_cursor_bridge_adaptor(parent):
    from PySide6.QtDBus import QDBusAbstractAdaptor

    @ClassInfo({"D-Bus Interface": CURSOR_BRIDGE_INTERFACE})
    class CursorBridgeAdaptor(QDBusAbstractAdaptor):
        @Slot(int, int)
        def updateCursor(self, x, y):
            parent.update_cursor(x, y)

        @Slot()
        def notifyClickOutside(self):
            parent.notify_click_outside()

    return CursorBridgeAdaptor(parent)


def get_cursor_pos_xdotool():
    if not check_command("xdotool") or not os.environ.get("DISPLAY"):
        return None
    try:
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            capture_output=True,
            text=True,
            timeout=0.2,
        )
    except Exception as exc:
        logger.debug("xdotool getmouselocation fallo: %s", exc)
        return None
    if result.returncode != 0:
        return None

    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    try:
        return int(values["X"]), int(values["Y"])
    except (KeyError, ValueError):
        return None


def get_cursor_pos():
    if is_qt_wayland():
        pos = get_cursor_pos_wayland()
        if pos is not None:
            return pos[0], pos[1], True

    pos = get_cursor_pos_xdotool()
    if pos is not None:
        return pos[0], pos[1], True

    pointer_state = X11Pointer().state()
    if pointer_state is not None:
        return pointer_state[0], pointer_state[1], not is_qt_wayland()

    pos = QCursor.pos()
    return pos.x(), pos.y(), not is_qt_wayland()


class MoreActionsButton(QPushButton):
    """Crisp vector ellipsis independent of fonts and theme glyphs."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.dot_color = QColor(color)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.dot_color)
        radius = max(1.35, self.width() / 17)
        center_y = self.height() / 2
        separation = radius * 3.25
        center_x = self.width() / 2
        for offset in (-separation, 0, separation):
            painter.drawEllipse(
                QPoint(round(center_x + offset), round(center_y)),
                round(radius),
                round(radius),
            )


class ActionPalette(QWidget):
    """Searchable overflow palette that stays a transient desktop surface."""

    action_triggered = Signal(str)
    pin_requested = Signal(str)
    suppress_app_requested = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        # Giving the popup an owning window establishes a Wayland transient
        # parent; compositors may reject unparented popup surfaces entirely.
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("textpikActionPalette")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(1.0)
        self.setMinimumWidth(300)
        self.resize(324, 360)
        self._actions = []
        self._surface = QColor("#25262a")
        self._border = QColor("#45474c")
        self._foreground = QColor("#f5f6f7")
        self._application = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(8)
        self.title = QLabel("Acciones", self)
        self.title.setObjectName("paletteTitle")
        self.subtitle = QLabel("", self)
        self.subtitle.setObjectName("paletteSubtitle")
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Buscar acciones…")
        self.search.setAccessibleName("Buscar en más acciones")
        self.search.setAccessibleDescription(
            "Filtra acciones por nombre o categoría mientras escribes"
        )
        self.search.setClearButtonEnabled(True)
        self.list = QListWidget(self)
        self.list.setAccessibleName("Resultados de acciones")
        self.list.setUniformItemSizes(True)
        self.list.setIconSize(QSize(17, 17))
        self.list.setMinimumHeight(150)
        self.pin = QPushButton("Fijar", self)
        self.pin.setAccessibleDescription(
            "Mueve la acción seleccionada al inicio de la barra"
        )
        self.pin.setObjectName("primaryAction")
        self.suppress_app = QPushButton("Ocultar aquí", self)
        self.suppress_app.setObjectName("secondaryAction")
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(7)
        footer.addWidget(self.pin, 1)
        footer.addWidget(self.suppress_app, 1)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addLayout(footer)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate_current)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(lambda _: self.pin.setEnabled(True))
        self.pin.clicked.connect(self._pin_current)
        self.suppress_app.clicked.connect(self._suppress_application)

    def apply_theme(self, settings):
        dark = color_luminance(settings["popup_background_color"]) < 0.5
        bg, fg = ("#1c1c20", "#fafafa") if dark else ("#ffffff", "#18181b")
        muted = "#a1a1aa" if dark else "#71717a"
        field = "#28282e" if dark else "#f4f4f5"
        hover = "#303037" if dark else "#ececee"
        press = "#3a3a42" if dark else "#e4e4e7"
        scroll_track = "transparent"
        scroll_thumb = "#52525b" if dark else "#c4c4ca"
        self._surface = QColor(bg)
        self._border = QColor(settings["popup_border_color"])
        self._foreground = QColor(fg)
        self.setStyleSheet(
            f"""
            QWidget#textpikActionPalette {{ background: transparent; color: {fg}; }}
            QLabel#paletteTitle {{ color: {fg}; font-size: 14px; font-weight: 700;
                padding: 1px 3px 0 3px; }}
            QLabel#paletteSubtitle {{ color: {muted}; font-size: 10px;
                padding: 0 3px 2px 3px; }}
            QLineEdit {{ background: {field}; color: {fg}; border: 1px solid transparent;
                border-radius: 10px; padding: 8px 10px; selection-background-color: {press}; }}
            QLineEdit:focus {{ border-color: {scroll_thumb}; }}
            QListWidget {{ background: transparent; color: {fg}; border: none; outline: none; }}
            QListWidget::item {{ padding: 8px 8px; margin: 1px 0; border-radius: 9px; }}
            QListWidget::item:selected, QListWidget::item:hover {{ background: {hover}; }}
            QPushButton {{ background: {field}; color: {fg}; border: none;
                border-radius: 9px; padding: 7px 12px; min-height: 18px; }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {press}; }}
            QPushButton#primaryAction {{ font-weight: 650; }}
            QPushButton#secondaryAction {{ color: {muted}; }}
            QScrollBar:vertical {{ background: {scroll_track}; width: 7px;
                margin: 2px 0; border: none; border-radius: 3px; }}
            QScrollBar::handle:vertical {{ background: {scroll_thumb};
                min-height: 24px; border-radius: 3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent; }}
            """
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, self._surface)
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        # Subtle top highlight keeps the surface defined on dark themes.
        highlight = QColor(255, 255, 255, 20)
        painter.setPen(QPen(highlight, 1))
        painter.drawLine(13, 1, max(13, self.width() - 13), 1)
        super().paintEvent(event)

    def open_for(self, actions, origin, settings, application=""):
        self._actions = list(actions)
        self.subtitle.setText(
            f"{len(self._actions)} disponibles  ·  Enter para ejecutar  ·  Esc para cerrar"
        )
        self._application = str(application or "").strip()
        self.suppress_app.setVisible(bool(self._application))
        if self._application:
            compact_name = (
                self._application
                if len(self._application) <= 32
                else f"{self._application[:29]}…"
            )
            self.suppress_app.setText(f"Ocultar en {compact_name}")
            self.suppress_app.setToolTip(self._application)
        self.apply_theme(settings)
        self.search.clear()
        self._populate(self._actions)
        # 457 px deja exactamente ocho filas de 37 px con la escala estándar,
        # evitando el aspecto de una novena fila accidentalmente recortada.
        desired_height = min(457, max(280, 182 + 39 * len(self._actions)))
        self.resize(324, desired_height)
        anchor_point = origin.mapToGlobal(QPoint(origin.width(), origin.height()))
        screen = QApplication.screenAt(anchor_point) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            owner = origin.window()
            owner_top_left = owner.mapToGlobal(QPoint(0, 0))
            owner_rect = (
                owner_top_left.x(),
                owner_top_left.y(),
                owner.width(),
                owner.height(),
            )
            x, y = place_popup(
                (anchor_point.x(), anchor_point.y()),
                (self.width(), self.height()),
                (area.x(), area.y(), area.width(), area.height()),
                owner_rect,
                7,
            )
            self.move(x, y)
        self.show()
        self.raise_()
        self.search.setFocus()

    def _suppress_application(self):
        if self._application:
            self.suppress_app_requested.emit(self._application)
            self.hide()

    def _populate(self, actions):
        self.list.clear()
        for action in actions:
            item = QListWidgetItem(action["name"])
            category = action.get("category", "General")
            item.setToolTip(f"{category} · {action['name']}")
            item.setData(Qt.UserRole, action["cmd"])
            item.setData(Qt.UserRole + 1, action.get("id", action["cmd"]))
            icon, needs_recolor = resolve_action_icon(action["icon"])
            if not icon.isNull():
                if needs_recolor:
                    icon = recolor_icon(icon, self._foreground, 17)
                item.setIcon(icon)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.pin.setEnabled(bool(self.list.count()))

    def _filter(self, query):
        ranked = []
        for index, action in enumerate(self._actions):
            label = f"{action.get('category', '')} {action['name']}"
            score = fuzzy_score(query, label)
            if score is not None:
                ranked.append((score, index, action))
        ranked.sort(key=lambda item: (item[0], item[1]))
        self._populate(action for _, _, action in ranked)

    def _activate_current(self):
        self._activate(self.list.currentItem())

    def _activate(self, item):
        if item is not None:
            command = item.data(Qt.UserRole)
            self.hide()
            self.action_triggered.emit(command)

    def _pin_current(self):
        item = self.list.currentItem()
        if item is not None:
            self.pin_requested.emit(item.data(Qt.UserRole + 1))
            self.hide()

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)


class PopupWindow(QWidget):
    action_triggered = Signal(str, str)
    pin_requested = Signal(str)
    suppress_app_requested = Signal(str)
    interaction_started = Signal()
    interaction_finished = Signal()
    dismissed = Signal()

    def __init__(self, actions, monitor, settings=None):
        super().__init__()
        self.actions = actions
        self.monitor = monitor
        self.settings = settings or dict(DEFAULT_SETTINGS)
        self.setWindowTitle(APP_NAME)
        self.setAccessibleName("Barra de acciones de TextPik")
        self.setAccessibleDescription(
            "Acciones disponibles para el texto seleccionado"
        )
        self.setWindowIcon(QIcon())
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self._actions_key = None
        self.visible_actions = []
        self._action_buttons = []
        self._more_button = None
        self._keyboard_index = -1
        self._more_menu_open = False
        self._application = ""
        self._last_stable_position = None
        self._last_position_at = 0.0
        self._last_pointer_sample = None
        self.palette = ActionPalette(self)
        self.palette.action_triggered.connect(self._on_click)
        self.palette.pin_requested.connect(self.pin_requested.emit)
        self.palette.suppress_app_requested.connect(self.suppress_app_requested.emit)
        self.palette.closed.connect(self._on_more_menu_closed)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.buttons_layout = QHBoxLayout()
        self.root_layout.addLayout(self.buttons_layout)
        self.insight_card = QLabel(self)
        self.insight_card.setObjectName("insightCard")
        self.insight_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.insight_card.setWordWrap(True)
        self.insight_card.setAccessibleName("Resultado de TextPik")
        self.insight_card.hide()
        self.root_layout.addWidget(self.insight_card)
        self.apply_settings(self.settings)
        self.set_actions(self.actions)

    def apply_settings(self, settings):
        self.settings = normalize_settings(settings)
        icon_size = self.settings["popup_icon_size"]
        padding = self.settings["popup_button_padding"]
        button_size = icon_size + (padding * 2)
        radius = self.settings["popup_border_radius"]
        button_radius = max(5, min(radius - 3, 9))
        self.icon_color = icon_color_for_background(
            self.settings["popup_background_color"]
        )
        self.icon_variant = icon_variant_for_background(
            self.settings["popup_background_color"]
        )

        self.buttons_layout.setContentsMargins(padding + 1, padding, padding + 1, padding)
        self.buttons_layout.setSpacing(self.settings["popup_spacing"])

        self.setWindowOpacity(self.settings["popup_opacity"])
        dark_surface = color_luminance(self.settings["popup_background_color"]) < 0.5
        hover_overlay = "rgba(255,255,255,24)" if dark_surface else "rgba(0,0,0,18)"
        press_overlay = "rgba(255,255,255,39)" if dark_surface else "rgba(0,0,0,32)"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {button_radius}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {hover_overlay};
            }}
            QPushButton[keyboardSelected="true"] {{
                background-color: {hover_overlay};
            }}
            QPushButton:pressed {{
                background-color: {press_overlay};
                border: none;
            }}
            QToolTip {{
                background-color: {self.settings['popup_background_color']};
                color: {self.icon_color.name()};
                border: 1px solid {self.settings['popup_border_color']};
                border-radius: 7px;
                padding: 5px 7px;
            }}
            QLabel#insightCard {{
                color: {self.icon_color.name()};
                background-color: {hover_overlay};
                border-top: 1px solid {self.settings['popup_border_color']};
                padding: 8px 11px;
                font-size: 12px;
                font-weight: 500;
            }}
            """
        )
        self.update()

        variant = getattr(self, "icon_variant", None)
        for button in self._action_buttons:
            button.setFixedSize(button_size, button_size)
            button.setIconSize(QSize(icon_size, icon_size))
            icon_name = getattr(button, "source_icon_name", None)
            if icon_name:
                icon, needs_recolor = resolve_action_icon(icon_name, variant)
                if icon.isNull():
                    icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
                    needs_recolor = False
                button.source_icon = icon
                if needs_recolor:
                    button.setIcon(recolor_icon(icon, self.icon_color, icon_size))
                else:
                    button.setIcon(icon)
        if self._more_button is not None:
            self._more_button.dot_color = QColor(self.icon_color)
            self._more_button.setFixedSize(button_size, button_size)
            self._more_button.update()
        self.adjustSize()

    def show_inline_result(self, title, value, detail=""):
        content = f"<b>{html.escape(str(title))}</b><br>{html.escape(str(value))}"
        if detail:
            content += f"<br><small>{html.escape(str(detail))}</small>"
        self.insight_card.setText(content)
        self.insight_card.setToolTip("Haz clic y arrastra para copiar el resultado")
        self.insight_card.show()
        self.adjustSize()
        if not self.isVisible():
            self.show()
            self.raise_()

    def clear_inline_result(self):
        self.insight_card.clear()
        self.insight_card.hide()
        self.adjustSize()

    def set_actions(self, actions, *, compact=False):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        available_width = screen.availableGeometry().width() if screen else 1920
        actions_key = (
            self.settings.get("max_popup_actions", 8),
            self.settings.get("show_all_popup_actions", False),
            self.settings.get("show_numeric_badges", False),
            compact,
            available_width,
            tuple(
                (
                    action["name"],
                    action["icon"],
                    action["cmd"],
                    tuple(action.get("context", [])),
                )
                for action in actions
            ),
        )
        if actions_key == self._actions_key:
            return

        self._actions_key = actions_key
        self.actions = actions
        self._action_buttons = []
        self._more_button = None
        self._keyboard_index = -1
        while self.buttons_layout.count():
            item = self.buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        icon_size = self.settings["popup_icon_size"]
        button_size = icon_size + (self.settings["popup_button_padding"] * 2)
        spacing = self.settings["popup_spacing"]
        horizontal_margins = (self.settings["popup_button_padding"] + 1) * 2
        slot_width = max(1, button_size + spacing)
        screen_capacity = max(
            4, (available_width - horizontal_margins - 32 + spacing) // slot_width
        )
        requested = (
            len(self.actions)
            if self.settings.get("show_all_popup_actions", False)
            else self.settings.get("max_popup_actions", 8)
        )
        if (
            compact
            and self.settings.get("adaptive_popup", True)
            and not self.settings.get("show_all_popup_actions", False)
        ):
            requested = min(
                requested,
                self.settings.get("popup_compact_actions", 4),
            )
        direct_count = min(len(self.actions), requested, screen_capacity)
        has_overflow = len(self.actions) > direct_count
        if has_overflow and direct_count >= screen_capacity:
            direct_count = max(3, screen_capacity - 1)
        self.visible_actions = self.actions[:direct_count]

        variant = getattr(self, "icon_variant", None)
        for i, action in enumerate(self.visible_actions):
            button = QPushButton()
            icon, needs_recolor = resolve_action_icon(action["icon"], variant)
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
                needs_recolor = False
            button.source_icon = icon
            button.source_icon_name = action["icon"]
            if needs_recolor:
                button.setIcon(
                    recolor_icon(
                        icon, self.icon_color, self.settings["popup_icon_size"]
                    )
                )
            else:
                button.setIcon(icon)
            shortcut = f"{i + 1}: " if i < 9 else ""
            button.setToolTip(f"{shortcut}{action['name']}")
            button.setAccessibleName(action["name"])
            button.setAccessibleDescription(
                f"Ejecutar {action['name']} sobre el texto seleccionado"
            )
            button.setFixedSize(button_size, button_size)
            button.setIconSize(QSize(icon_size, icon_size))
            button.setFlat(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            command = action["cmd"]
            button.clicked.connect(
                lambda checked=False, cmd=command: self._on_click(cmd)
            )
            self.buttons_layout.addWidget(button)
            self._action_buttons.append(button)
            if self.settings.get("show_numeric_badges", False) and i < 9:
                badge = QLabel(str(i + 1), button)
                badge.setStyleSheet(
                    "background: rgba(0,0,0,40); color: #888; "
                    "font-size: 8px; font-weight: bold; "
                    "border-radius: 4px; padding: 0 3px;"
                )
                badge.adjustSize()
                badge.move(1, 1)
                badge.setAttribute(Qt.WA_TransparentForMouseEvents)
                badge.show()

        if has_overflow:
            self.buttons_layout.addSpacing(2)
            more_button = MoreActionsButton(self.icon_color)
            self._more_button = more_button
            more_button.setObjectName("moreActions")
            more_button.setToolTip(f"Más acciones ({len(self.actions) - direct_count})")
            more_button.setAccessibleName("Más acciones")
            more_button.setAccessibleDescription(
                f"Mostrar {len(self.actions) - direct_count} acciones adicionales"
            )
            more_button.setFixedSize(button_size, button_size)
            more_button.setFlat(True)
            more_button.setFocusPolicy(Qt.NoFocus)
            more_button.setCursor(Qt.PointingHandCursor)
            palette_actions = list(self.actions[direct_count:])
            more_button.clicked.connect(
                lambda checked=False, values=palette_actions, button=more_button: self._open_palette(
                    values, button
                )
            )
            self.buttons_layout.addWidget(more_button)

        self.buttons_layout.activate()
        self.adjustSize()

    def paintEvent(self, event):
        radius = self.settings.get("popup_border_radius", 16)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        background = QColor(self.settings["popup_background_color"])
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, background.lighter(103))
        gradient.setColorAt(0.42, background)
        gradient.setColorAt(1.0, background.darker(102))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(self.settings["popup_border_color"]), 1))
        painter.drawPath(path)
        top_glint = QColor(255, 255, 255, 18)
        painter.setPen(QPen(top_glint, 1))
        painter.drawLine(radius, 1, max(radius, self.width() - radius), 1)
        super().paintEvent(event)

    def _on_more_menu_opened(self):
        self._more_menu_open = True

    def _on_more_menu_closed(self):
        self._more_menu_open = False
        self.interaction_finished.emit()

    def _open_palette(self, actions, button):
        self._more_menu_open = True
        self.interaction_started.emit()
        self.palette.open_for(actions, button, self.settings, self._application)

    def set_context(self, context):
        self._application = str(getattr(context, "application", "") or "").strip()

    def _on_click(self, cmd):
        text = self.monitor.get_last_text() if self.monitor else ""
        self.hide()
        self.action_triggered.emit(cmd, text)

    def hideEvent(self, event):
        self.dismissed.emit()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        QTimer.singleShot(0, self.hide_if_focus_outside)
        super().focusOutEvent(event)

    def hide_if_focus_outside(self):
        if self.settings.get("sticky_popup", False) or self._more_menu_open:
            return
        focus_widget = QApplication.focusWidget()
        if focus_widget is self or (
            focus_widget is not None and self.isAncestorOf(focus_widget)
        ):
            return
        logger.info("Popup perdio foco hacia fuera; ocultando")
        self.hide()

    def is_sticky(self):
        return bool(self.settings.get("sticky_popup", False))

    def is_interacting(self):
        return self.is_sticky() or self._more_menu_open

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Up, Qt.Key_Right, Qt.Key_Down):
            if self.visible_actions:
                step = -1 if key in (Qt.Key_Left, Qt.Key_Up) else 1
                start = self._keyboard_index
                if start < 0:
                    start = 0 if step < 0 else -1
                self._set_keyboard_index((start + step) % len(self.visible_actions))
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if 0 <= self._keyboard_index < len(self.visible_actions):
                self._on_click(self.visible_actions[self._keyboard_index]["cmd"])
                return
        if Qt.Key_1 <= key <= Qt.Key_9:
            idx = key - Qt.Key_1
            if idx < len(self.visible_actions):
                self._on_click(self.visible_actions[idx]["cmd"])
                return
        if key == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def _set_keyboard_index(self, index):
        self._keyboard_index = index
        for button_index, button in enumerate(self._action_buttons):
            button.setProperty("keyboardSelected", button_index == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def show_at_cursor(self, anchor=None, avoid_rect=None):
        if anchor is not None:
            cx, cy, cursor_reliable = anchor.x, anchor.y, anchor.confidence >= 0.65
        else:
            cx, cy, cursor_reliable = get_cursor_pos()
        screen = QApplication.screenAt(QPoint(cx, cy)) or QApplication.primaryScreen()
        self.adjustSize()
        size = self.sizeHint()
        self.resize(size)
        if screen:
            geo = screen.availableGeometry()
            width = size.width()
            height = size.height()

            if cursor_reliable:
                now = time.monotonic()
                pointer_direction = None
                if self._last_pointer_sample is not None:
                    px, py, sampled_at = self._last_pointer_sample
                    if now - sampled_at <= 0.8:
                        pointer_direction = (cx - px, cy - py)
                self._last_pointer_sample = (cx, cy, now)
                x, y = place_popup(
                    (cx, cy),
                    (width, height),
                    (geo.x(), geo.y(), geo.width(), geo.height()),
                    avoid_rect,
                    self.settings.get("popup_cursor_gap", 6),
                    pointer_direction,
                )
            else:
                if self.settings.get("popup_wayland_fallback_horizontal") == "cursor":
                    x = cx + 14
                else:
                    x = geo.left() + ((geo.width() - width) // 2)
                y = geo.top() + self.settings.get("popup_wayland_fallback_top", 112)
                logger.info("Usando posicion fallback para popup: x=%s y=%s", x, y)

            if x + width > geo.right() + 1:
                x = geo.right() - width + 1
                if (
                    not cursor_reliable
                    and self.settings.get("popup_wayland_fallback_horizontal")
                    == "center"
                ):
                    x = geo.right() - width + 1
            if y + height > geo.bottom():
                y = geo.bottom() - height + 1

            x = max(geo.left(), x)
            y = max(geo.top(), y)
            previous = (
                self._last_stable_position
                if time.monotonic() - self._last_position_at <= 1.5
                else None
            )
            x, y = stabilize_popup_position(
                (x, y),
                previous,
                (width, height),
                avoid_rect,
                threshold=14,
            )
            self._last_stable_position = (x, y)
            self._last_position_at = time.monotonic()
            self.move(x, y)
            logger.info(
                "Popup: cursor=(%s,%s reliable=%s) screen=%s,%s %sx%s pos=(%s,%s) size=%sx%s",
                cx,
                cy,
                cursor_reliable,
                geo.x(),
                geo.y(),
                geo.width(),
                geo.height(),
                x,
                y,
                width,
                height,
            )
        else:
            logger.warning("Popup: no se encontro pantalla para cursor=(%s,%s)", cx, cy)

        self.show()
        self.raise_()
        logger.info("Popup visible=%s geometry=%s", self.isVisible(), self.geometry())


def validate_actions(actions):
    if not isinstance(actions, list):
        actions = DEFAULT_ACTIONS

    valid = []
    for action in actions:
        entry = migrate_action(action)
        if entry is None:
            continue
        # Versiones anteriores marcaron por error todas las búsquedas como
        # exclusivas para URLs. Se migra sin tocar acciones personalizadas.
        if entry.get("context") == ["url"] and entry["cmd"].startswith(
            (
                "xdg-open 'https://www.google.com/search",
                "xdg-open 'https://www.youtube.com/results",
                "xdg-open 'https://www.google.com/maps",
                "xdg-open 'https://chatgpt.com/",
                "xdg-open 'https://chat.deepseek.com/",
                "xdg-open 'https://duckduckgo.com/",
            )
        ):
            entry["context"] = ["text"]
        valid.append(entry)

    if valid:
        return valid
    return [entry for action in DEFAULT_ACTIONS if (entry := migrate_action(action))]


def load_actions_file():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIONS_FILE.exists():
        try:
            return validate_actions(read_json(ACTIONS_FILE))
        except Exception as exc:
            logger.warning("No se pudo cargar actions.json: %s", exc)

    write_json_atomic(ACTIONS_FILE, DEFAULT_ACTIONS)
    return validate_actions(DEFAULT_ACTIONS)


def is_terminal_execution(cmd):
    return core_is_terminal_execution(cmd)


def run_cli_action(args):
    if not args:
        print(
            "Uso: textpik run <accion-o-comando> [texto]",
            file=sys.stderr,
        )
        return 2

    action_or_command = args[0]
    if len(args) >= 2:
        text = args[1]
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        text = ""

    actions = validate_actions(load_actions_file())
    command = action_or_command
    for action in actions:
        if action["name"] == action_or_command:
            command = action["cmd"]
            break

    if command in {"copy", "paste", "terminal", "print", "ollama"}:
        print(
            f"La accion '{command}' requiere la interfaz grafica de textpik.",
            file=sys.stderr,
        )
        return 2

    if command == "open-url":
        url = normalize_url(text)
        if not url:
            print("No hay URL para abrir.", file=sys.stderr)
            return 2
        command = "xdg-open '{}'"
        text = url

    try:
        argv = build_command_argv(command, text)
    except ValueError as exc:
        print(f"Comando invalido: {exc}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["TEXTPIK_TEXT"] = text
    env["TEXTPIK_URL"] = quote_plus(text)

    try:
        return subprocess.run(argv, env=env).returncode
    except FileNotFoundError:
        print(f"Comando no encontrado: {argv[0]}", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"Error ejecutando comando: {exc}", file=sys.stderr)
        return 1


class ActionEditDialog(QDialog):
    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar accion" if action else "Anadir accion")
        self.setMinimumWidth(520)
        action = action or {}
        self.original_action = dict(action)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(action.get("name", ""), self)
        self.name_edit.setPlaceholderText("Ej: Buscar en Wikipedia")
        form.addRow("Nombre", self.name_edit)

        self.category_edit = QComboBox(self)
        self.category_edit.setEditable(True)
        self.category_edit.addItems(
            ["General", "Portapapeles", "Buscar", "Texto", "Compartir", "Sistema", "IA"]
        )
        category = action.get("category", "General")
        self.category_edit.setCurrentText(category)
        form.addRow("Categoría", self.category_edit)

        self.icon_edit = QComboBox(self)
        self.icon_edit.setEditable(True)
        for path in sorted(ACTIONS_ASSETS_DIR.glob("*.svg")):
            if path.stem.endswith(("-black", "-white")):
                continue
            self.icon_edit.addItem(load_icon(path), path.name)
        self.icon_edit.setCurrentText(action.get("icon", "copy.svg"))
        form.addRow("Icono", self.icon_edit)

        self.cmd_edit = QLineEdit(action.get("cmd", ""), self)
        self.cmd_edit.setPlaceholderText("Ej: xdg-open 'https://example.com?q={url}'")
        form.addRow("Comando", self.cmd_edit)

        self.enabled_check = QCheckBox("Mostrar esta accion", self)
        self.enabled_check.setChecked(bool(action.get("enabled", True)))
        form.addRow("Activa", self.enabled_check)

        self.context_edit = QLineEdit(", ".join(action.get("context", [])), self)
        self.context_edit.setPlaceholderText("text, url, email, ip, number, code")
        form.addRow("Contextos", self.context_edit)

        self.operation_edit = QComboBox(self)
        for label, value in (
            ("Comando o integración", "command"),
            ("Transformar texto", "transform"),
            ("Abrir URL", "open-url"),
            ("Copiar", "copy"),
            ("Sistema", "system"),
        ):
            self.operation_edit.addItem(label, value)
        operation = action.get("operation", "command")
        self.operation_edit.setCurrentIndex(
            max(0, self.operation_edit.findData(operation))
        )
        form.addRow("Tipo de acción", self.operation_edit)

        self.result_edit = QComboBox(self)
        for label, value in (
            ("Sin resultado", "none"),
            ("Copiar resultado", "copy"),
            ("Reemplazar selección", "replace-selection"),
            ("Abrir recurso", "open"),
            ("Mostrar diálogo", "dialog"),
        ):
            self.result_edit.addItem(label, value)
        result = action.get("result", "none")
        self.result_edit.setCurrentIndex(max(0, self.result_edit.findData(result)))
        form.addRow("Resultado", self.result_edit)

        layout.addLayout(form)

        help_label = QLabel(
            "Marcadores: {url} para texto codificado en URL, {} o *** para texto literal.",
            self,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if not self.get_action(validate=False):
            QMessageBox.warning(
                self,
                "Accion incompleta",
                "Nombre, icono y comando son obligatorios.",
            )
            return
        super().accept()

    def get_action(self, validate=True):
        action = {
            **self.original_action,
            "name": self.name_edit.text().strip(),
            "icon": self.icon_edit.currentText().strip(),
            "cmd": self.cmd_edit.text().strip(),
            "enabled": self.enabled_check.isChecked(),
            "category": self.category_edit.currentText().strip() or "General",
            "operation": self.operation_edit.currentData(),
            "result": self.result_edit.currentData(),
        }
        contexts = [
            value.strip().lower()
            for value in self.context_edit.text().split(",")
            if value.strip()
        ]
        if contexts:
            action["context"] = list(dict.fromkeys(contexts))
        if validate and not all(action[key] for key in ("name", "icon", "cmd")):
            return None
        if not validate and not all(action[key] for key in ("name", "icon", "cmd")):
            return None
        return action


class ContextProfileDialog(QDialog):
    """Edits one compact application/text-type action profile."""

    def __init__(self, actions, profile=None, parent=None):
        super().__init__(parent)
        profile = profile or {}
        self.setWindowTitle("Editar perfil" if profile else "Nuevo perfil contextual")
        self.setMinimumSize(520, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(str(profile.get("name", "")), self)
        self.name_edit.setPlaceholderText("Ej: Navegación web")
        form.addRow("Nombre", self.name_edit)
        self.application_edit = QLineEdit(
            str(profile.get("application", "")), self
        )
        self.application_edit.setPlaceholderText("Ej: firefox, libreoffice, code")
        form.addRow("Aplicación contiene", self.application_edit)
        self.types_edit = QLineEdit(
            ", ".join(profile.get("text_types", [])), self
        )
        self.types_edit.setPlaceholderText("text, url, email, code, number, ip")
        form.addRow("Tipos de texto", self.types_edit)
        layout.addLayout(form)
        note = QLabel(
            "La primera regla coincidente limita la barra a las acciones marcadas, "
            "sin cambiar su orden global.",
            self,
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")
        layout.addWidget(note)
        self.action_list = QListWidget(self)
        self.action_list.setAlternatingRowColors(True)
        selected = set(profile.get("action_ids", []))
        for action in actions:
            action_id = action.get("id", action.get("cmd", ""))
            item = QListWidgetItem(action["name"], self.action_list)
            item.setData(Qt.UserRole, action_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if action_id in selected else Qt.Unchecked)
        layout.addWidget(self.action_list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_profile(self):
        types = [
            value.strip().lower()
            for value in self.types_edit.text().split(",")
            if value.strip()
        ]
        action_ids = [
            self.action_list.item(index).data(Qt.UserRole)
            for index in range(self.action_list.count())
            if self.action_list.item(index).checkState() == Qt.Checked
        ]
        return {
            "name": self.name_edit.text().strip(),
            "application": self.application_edit.text().strip(),
            "text_types": list(dict.fromkeys(types)),
            "action_ids": action_ids,
        }

    def accept(self):
        profile = self.get_profile()
        if not profile["name"]:
            QMessageBox.warning(self, "Perfil incompleto", "Indica un nombre.")
            return
        if not profile["application"] and not profile["text_types"]:
            QMessageBox.warning(
                self,
                "Perfil incompleto",
                "Indica una aplicación o al menos un tipo de texto.",
            )
            return
        if not profile["action_ids"]:
            QMessageBox.warning(
                self, "Perfil incompleto", "Selecciona al menos una acción."
            )
            return
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, settings, actions, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TextPik — Configuracion")
        self.setMinimumSize(720, 560)
        self.resize(820, 720)
        self.controller = controller
        self.settings = normalize_settings(settings)
        self.actions = list(actions)
        self.context_profiles = list(self.settings.get("context_profiles", []))
        self.automations = [
            dict(flow) for flow in getattr(controller, "automations", [])
        ]
        self._color_swatches = {}

        layout = QVBoxLayout(self)
        hero = QHBoxLayout()
        hero.setSpacing(12)
        hero_icon = QLabel(self)
        hero_icon.setPixmap(load_icon(APP_ICON_FILE).pixmap(42, 42))
        hero_text = QVBoxLayout()
        hero_title = QLabel("TextPik", self)
        hero_title.setObjectName("heroTitle")
        hero_subtitle = QLabel(
            "Acciones rápidas, privadas y contextuales para Linux", self
        )
        hero_subtitle.setObjectName("heroSubtitle")
        hero_text.addWidget(hero_title)
        hero_text.addWidget(hero_subtitle)
        hero.addWidget(hero_icon)
        hero.addLayout(hero_text, 1)
        layout.addLayout(hero)
        tabs = QTabWidget(self)
        tabs.tabBar().setExpanding(True)

        # ── Pestaña 1: Apariencia ──
        ap_tab = QWidget()
        ap_layout = QVBoxLayout(ap_tab)

        # Swatches de color — botones visuales con el color real
        colors_group = QGroupBox("Colores de la barra")
        colors_grid = QGridLayout(colors_group)
        self._make_swatch(colors_grid, 0, 0, "popup_background_color", "Fondo")
        self._make_swatch(colors_grid, 0, 1, "popup_border_color", "Borde")

        ap_layout.addWidget(colors_group)

        # Tema predefinido
        theme_group = QGroupBox("Tema")
        theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox(self)
        self.theme_combo.addItem("Personalizado", "custom")
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Oscuro", "dark")
        self.theme_combo.addItem("OLED", "oled")
        idx = self.theme_combo.findData(self.settings.get("theme_preset", "custom"))
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._apply_theme_preset)
        theme_form.addRow("Predefinido", self.theme_combo)
        self.icon_size = self._spin(12, 64, self.settings["popup_icon_size"])
        theme_form.addRow("Tamaño de iconos", self.icon_size)
        self.button_padding = self._spin(
            2, 12, self.settings.get("popup_button_padding", 4)
        )
        theme_form.addRow("Altura y aire de la barra", self.button_padding)
        self.popup_spacing = self._spin(
            0, 8, self.settings.get("popup_spacing", 1)
        )
        theme_form.addRow("Separación entre acciones", self.popup_spacing)
        self.radius = self._spin(0, 48, int(self.settings["popup_border_radius"]))
        theme_form.addRow("Bordes redondeados", self.radius)
        self.opacity = self._spin(
            25, 100, int(float(self.settings["popup_opacity"]) * 100)
        )
        theme_form.addRow("Opacidad (%)", self.opacity)
        ap_layout.addWidget(theme_group)

        # Extras
        extra_group = QGroupBox("Extras")
        extra_form = QFormLayout(extra_group)
        self.show_numeric_badges = QCheckBox(
            "Mostrar numeros de atajo (1-9) en iconos", self
        )
        self.show_numeric_badges.setChecked(
            bool(self.settings.get("show_numeric_badges", False))
        )
        extra_form.addRow("Badges numericos", self.show_numeric_badges)
        ap_layout.addWidget(extra_group)
        ap_layout.addStretch()

        # ── Pestaña 2: Comportamiento ──
        beh_tab = QWidget()
        beh_layout = QVBoxLayout(beh_tab)
        beh_group = QGroupBox("Activacion")
        beh_form = QFormLayout(beh_group)
        self.show_on_selection = QCheckBox("Mostrar popup al seleccionar texto", self)
        self.show_on_selection.setChecked(bool(self.settings["show_on_selection"]))
        beh_form.addRow("Activacion", self.show_on_selection)
        self.popup_delay = self._spin(
            0, 5000, int(self.settings.get("popup_delay_ms", 0))
        )
        self.popup_delay.setSuffix(" ms")
        beh_form.addRow("Retardo", self.popup_delay)
        self.auto_hide = self._spin(
            0, 30000, int(self.settings.get("popup_auto_hide_ms", 5000))
        )
        self.auto_hide.setSingleStep(500)
        self.auto_hide.setSuffix(" ms")
        self.auto_hide.setSpecialValueText("Desactivado")
        beh_form.addRow("Ocultar si no se usa", self.auto_hide)
        self.cursor_gap = self._spin(
            2, 24, int(self.settings.get("popup_cursor_gap", 6))
        )
        self.cursor_gap.setSuffix(" px")
        beh_form.addRow("Distancia a la selección", self.cursor_gap)
        self.sticky_popup = QCheckBox(
            "Mantener popup hasta elegir accion o Escape", self
        )
        self.sticky_popup.setChecked(bool(self.settings.get("sticky_popup", False)))
        beh_form.addRow("Modo sticky", self.sticky_popup)
        self.context_aware = QCheckBox(
            "Mostrar solo acciones relevantes segun el texto", self
        )
        self.context_aware.setChecked(bool(self.settings.get("context_aware", True)))
        beh_form.addRow("Contexto inteligente", self.context_aware)
        self.local_recommendations = QCheckBox(
            "Sugerir hasta dos acciones según uso local (sin guardar texto)", self
        )
        self.local_recommendations.setChecked(
            bool(self.settings.get("local_recommendations", False))
        )
        beh_form.addRow("Recomendaciones locales", self.local_recommendations)
        self.history_enabled = QCheckBox(
            "Guardar historial local limitado (desactivado por defecto)", self
        )
        self.history_enabled.setChecked(
            bool(self.settings.get("history_enabled", False))
        )
        beh_form.addRow("Historial privado", self.history_enabled)
        self.history_max_items = self._spin(
            10, 1000, int(self.settings.get("history_max_items", 100))
        )
        beh_form.addRow("Máximo del historial", self.history_max_items)
        self.adaptive_popup = QCheckBox(
            "Reducir la barra cuando falte contexto fiable", self
        )
        self.adaptive_popup.setChecked(
            bool(self.settings.get("adaptive_popup", True))
        )
        beh_form.addRow("Barra adaptativa", self.adaptive_popup)
        self.popup_min_confidence = self._spin(
            0, 90, int(self.settings.get("popup_min_confidence", 45))
        )
        self.popup_min_confidence.setSuffix(" %")
        beh_form.addRow("Confianza mínima", self.popup_min_confidence)
        self.popup_full_confidence = self._spin(
            50, 100, int(self.settings.get("popup_full_confidence", 78))
        )
        self.popup_full_confidence.setSuffix(" %")
        beh_form.addRow("Confianza para barra completa", self.popup_full_confidence)
        self.popup_compact_actions = self._spin(
            3, 8, int(self.settings.get("popup_compact_actions", 4))
        )
        beh_form.addRow("Acciones en modo compacto", self.popup_compact_actions)
        self.enable_global_hotkey = QCheckBox("Atajo global Ctrl+Shift+P", self)
        self.enable_global_hotkey.setChecked(
            bool(self.settings.get("enable_global_hotkey", False))
        )
        beh_form.addRow("Atajo global", self.enable_global_hotkey)

        self.max_selection = self._spin(
            1, 50000, int(self.settings["max_selection_length"])
        )
        beh_form.addRow("Tamano maximo de texto", self.max_selection)
        self.confirm_terminal = QCheckBox(
            "Confirmar antes de ejecutar en terminal", self
        )
        self.confirm_terminal.setChecked(
            bool(self.settings.get("confirm_terminal_execution", True))
        )
        beh_form.addRow("Confirmacion terminal", self.confirm_terminal)
        self.disable_in_games = QCheckBox(
            "No mostrar con juegos/pantalla completa", self
        )
        self.disable_in_games.setChecked(bool(self.settings["disable_in_games"]))
        beh_form.addRow("Filtro anti-juegos", self.disable_in_games)
        self.disable_in_sensitive = QCheckBox(
            "No mostrar ni leer selecciones en campos sensibles", self
        )
        self.disable_in_sensitive.setChecked(
            bool(self.settings.get("disable_in_sensitive_fields", True))
        )
        beh_form.addRow("Privacidad", self.disable_in_sensitive)
        self.ignore_file_selections = QCheckBox(
            "No abrir al seleccionar archivos o elementos del explorador", self
        )
        self.ignore_file_selections.setChecked(
            bool(self.settings.get("ignore_file_selections", True))
        )
        beh_form.addRow("Trabajo con archivos", self.ignore_file_selections)
        beh_layout.addWidget(beh_group)
        beh_layout.addStretch()

        # ── Pestaña 3: Filtros ──
        flt_tab = QWidget()
        flt_layout = QVBoxLayout(flt_tab)

        apps_group = QGroupBox("Aplicaciones bloqueadas")
        apps_layout = QVBoxLayout(apps_group)
        self.blocked_apps_enabled = QCheckBox(
            "No mostrar popup en estas aplicaciones", self
        )
        self.blocked_apps_enabled.setChecked(
            bool(self.settings.get("blocked_apps_enabled", False))
        )
        apps_layout.addWidget(self.blocked_apps_enabled)
        self.blocked_list = QListWidget(self)
        self.blocked_list.setMaximumHeight(100)
        self._populate_blocked_list()
        apps_layout.addWidget(self.blocked_list)
        abtn = QHBoxLayout()
        abtn_add = QPushButton("+", self)
        abtn_add.clicked.connect(self._add_blocked_app)
        abtn_add.setFixedWidth(32)
        abtn_rm = QPushButton("−", self)
        abtn_rm.clicked.connect(self._remove_blocked_app)
        abtn_rm.setFixedWidth(32)
        abtn.addWidget(abtn_add)
        abtn.addWidget(abtn_rm)
        abtn.addStretch()
        apps_layout.addLayout(abtn)
        flt_layout.addWidget(apps_group)

        profiles_group = QGroupBox("Perfiles contextuales")
        profiles_layout = QVBoxLayout(profiles_group)
        self.context_profiles_enabled = QCheckBox(
            "Usar perfiles por aplicación y tipo de texto", self
        )
        self.context_profiles_enabled.setChecked(
            bool(self.settings.get("context_profiles_enabled", False))
        )
        profiles_layout.addWidget(self.context_profiles_enabled)
        self.context_profiles_list = QListWidget(self)
        self.context_profiles_list.setMaximumHeight(105)
        self.context_profiles_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.context_profiles_list.setDefaultDropAction(Qt.MoveAction)
        self.context_profiles_list.setDragEnabled(True)
        self.context_profiles_list.setAcceptDrops(True)
        self.context_profiles_list.setDropIndicatorShown(True)
        self.context_profiles_list.model().rowsMoved.connect(
            lambda *_: QTimer.singleShot(0, self._sync_context_profiles_from_list)
        )
        self.context_profiles_list.itemDoubleClicked.connect(
            lambda _item: self._edit_context_profile()
        )
        profiles_layout.addWidget(self.context_profiles_list)
        profile_buttons = QHBoxLayout()
        add_profile = QPushButton("Añadir", self)
        add_profile.clicked.connect(self._add_context_profile)
        edit_profile = QPushButton("Editar", self)
        edit_profile.clicked.connect(self._edit_context_profile)
        remove_profile = QPushButton("Eliminar", self)
        remove_profile.clicked.connect(self._remove_context_profile)
        profile_buttons.addWidget(add_profile)
        profile_buttons.addWidget(edit_profile)
        profile_buttons.addWidget(remove_profile)
        profile_buttons.addStretch()
        profiles_layout.addLayout(profile_buttons)
        self._populate_context_profiles()
        flt_layout.addWidget(profiles_group)

        act_group = QGroupBox("Actividades de Plasma bloqueadas")
        act_layout = QVBoxLayout(act_group)
        self.blocked_activities_enabled = QCheckBox(
            "No mostrar en estas actividades", self
        )
        self.blocked_activities_enabled.setChecked(
            bool(self.settings.get("blocked_activities_enabled", False))
        )
        act_layout.addWidget(self.blocked_activities_enabled)
        self.blocked_activities_list = QListWidget(self)
        self.blocked_activities_list.setMaximumHeight(80)
        for act in self.settings.get("blocked_activities", []):
            self.blocked_activities_list.addItem(str(act))
        act_layout.addWidget(self.blocked_activities_list)
        abtn2 = QHBoxLayout()
        abtn2_add = QPushButton("+", self)
        abtn2_add.clicked.connect(self._add_blocked_activity)
        abtn2_add.setFixedWidth(32)
        abtn2_rm = QPushButton("−", self)
        abtn2_rm.clicked.connect(self._remove_blocked_activity)
        abtn2_rm.setFixedWidth(32)
        abtn2.addWidget(abtn2_add)
        abtn2.addWidget(abtn2_rm)
        abtn2.addStretch()
        act_layout.addLayout(abtn2)
        flt_layout.addWidget(act_group)
        flt_layout.addStretch()

        # ── Pestaña 4: Wayland ──
        wl_tab = QWidget()
        wl_layout = QVBoxLayout(wl_tab)
        wl_group = QGroupBox("Posicionamiento (fallback)")
        wl_form = QFormLayout(wl_group)
        self.fallback_top = self._spin(
            0, 600, int(self.settings["popup_wayland_fallback_top"])
        )
        self.fallback_top.setSuffix(" px")
        wl_form.addRow("Posicion superior", self.fallback_top)
        self.fallback_horizontal = QComboBox(self)
        self.fallback_horizontal.addItem("Centrada", "center")
        self.fallback_horizontal.addItem("Junto al cursor", "cursor")
        idx = self.fallback_horizontal.findData(
            self.settings["popup_wayland_fallback_horizontal"]
        )
        self.fallback_horizontal.setCurrentIndex(max(0, idx))
        wl_form.addRow("Anclaje horizontal", self.fallback_horizontal)
        self.enable_wl_polling = QCheckBox("Habilitar polling en Wayland", self)
        self.enable_wl_polling.setChecked(
            bool(self.settings.get("enable_wayland_polling", True))
        )
        wl_form.addRow("Polling", self.enable_wl_polling)
        wl_layout.addWidget(wl_group)
        wl_layout.addStretch()

        # ── Pestaña 5: Sistema ──
        system_tab = QWidget()
        system_layout = QVBoxLayout(system_tab)
        startup_group = QGroupBox("Integración con el escritorio")
        startup_form = QFormLayout(startup_group)
        self.start_at_login = QCheckBox(
            "Iniciar TextPik al entrar en la sesión", self
        )
        self.start_at_login.setChecked(
            bool(self.settings.get("start_at_login", True))
        )
        if os.environ.get("FLATPAK_ID"):
            self.start_at_login.setEnabled(False)
            self.start_at_login.setToolTip(
                "En Flatpak, el inicio en segundo plano lo administra el portal del escritorio."
            )
        startup_form.addRow("Inicio automático", self.start_at_login)
        desktop_value = QLabel(desktop_environment() or "No identificado", self)
        session_value = QLabel(
            "Wayland" if is_qt_wayland() else "X11", self
        )
        tray_value = QLabel(
            "Disponible" if QSystemTrayIcon.isSystemTrayAvailable() else "No disponible",
            self,
        )
        atspi_value = QLabel(
            "Activo" if self.controller.atspi.available else "No disponible", self
        )
        startup_form.addRow("Escritorio", desktop_value)
        startup_form.addRow("Sesión gráfica", session_value)
        startup_form.addRow("Bandeja del sistema", tray_value)
        startup_form.addRow("Accesibilidad AT-SPI", atspi_value)
        system_layout.addWidget(startup_group)

        integration_note = QLabel(
            "TextPik usa las APIs nativas disponibles y degrada cada integración "
            "de forma segura cuando el escritorio no ofrece una capacidad.",
            self,
        )
        integration_note.setWordWrap(True)
        integration_note.setObjectName("mutedText")
        system_layout.addWidget(integration_note)
        system_layout.addStretch()

        # ── Pestaña 6: Diagnostico ──
        diag_tab = QWidget()
        diag_layout = QVBoxLayout(diag_tab)
        diag_group = QGroupBox("Sistema")
        diag_form = QFormLayout(diag_group)
        self.log_enabled = QCheckBox("Guardar archivo de log", self)
        self.log_enabled.setChecked(bool(self.settings["log_enabled"]))
        diag_form.addRow("Log", self.log_enabled)
        self.diagnostics_text = QTextEdit(self)
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setMinimumHeight(120)
        self.diagnostics_text.setPlainText(self.controller.build_diagnostics())
        diag_form.addRow("Estado", self.diagnostics_text)
        dbtn = QHBoxLayout()
        refresh_btn = QPushButton("Actualizar", self)
        refresh_btn.clicked.connect(self._refresh_diagnostics)
        test_btn = QPushButton("Probar popup", self)
        test_btn.clicked.connect(self._test_popup)
        dbtn.addWidget(refresh_btn)
        dbtn.addWidget(test_btn)
        dbtn.addStretch()
        diag_form.addRow("Acciones", dbtn)
        diag_layout.addWidget(diag_group)
        diag_layout.addStretch()

        # ── Pestaña 7: Acciones ──
        acttab = QWidget()
        acttab_layout = QVBoxLayout(acttab)
        bar_group = QGroupBox("Composición de la barra")
        bar_form = QFormLayout(bar_group)
        self.show_all_popup_actions = QCheckBox(
            "Mostrar todas las acciones activas directamente", self
        )
        self.show_all_popup_actions.setChecked(
            bool(self.settings.get("show_all_popup_actions", False))
        )
        bar_form.addRow("Modo", self.show_all_popup_actions)
        self.max_popup_actions = self._spin(
            3, 40, int(self.settings.get("max_popup_actions", 8))
        )
        self.max_popup_actions.setSuffix(" iconos")
        self.max_popup_actions.setEnabled(
            not self.show_all_popup_actions.isChecked()
        )
        self.show_all_popup_actions.toggled.connect(
            lambda checked: self.max_popup_actions.setEnabled(not checked)
        )
        bar_form.addRow("Iconos directos", self.max_popup_actions)
        bar_note = QLabel(
            "La barra puede crecer hasta el ancho disponible de la pantalla. "
            "Más acciones contendrá únicamente el excedente real.",
            self,
        )
        bar_note.setWordWrap(True)
        bar_note.setObjectName("mutedText")
        bar_form.addRow("", bar_note)
        acttab_layout.addWidget(bar_group)
        self.action_list = QListWidget(self)
        self.action_list.setAlternatingRowColors(True)
        self.action_list.setMinimumHeight(160)
        self.action_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.action_list.setDefaultDropAction(Qt.MoveAction)
        self.action_list.setDragEnabled(True)
        self.action_list.setAcceptDrops(True)
        self.action_list.setDropIndicatorShown(True)
        self.action_list.model().rowsMoved.connect(
            lambda *_: QTimer.singleShot(0, self._sync_actions_from_list)
        )
        self._populate_action_list()
        acttab_layout.addWidget(self.action_list)
        btns = QHBoxLayout()
        for text, slot in [
            ("Agregar acción", self._add_action),
            ("Editar", self._edit_action),
            ("−", self._delete_action),
            ("↑", self._move_up),
            ("↓", self._move_down),
        ]:
            b = QPushButton(text, self)
            b.clicked.connect(slot)
            if text == "−":
                b.setFixedWidth(32)
            btns.addWidget(b)
        btns.addStretch()
        acttab_layout.addLayout(btns)
        note = QLabel(
            "Arrastra las acciones para distribuirlas en el orden exacto que quieras; "
            "también puedes usar ↑ y ↓. Activa solo las que necesites.",
            self,
        )
        note.setWordWrap(True)
        acttab_layout.addWidget(note)
        automation_group = QGroupBox("Automatizaciones visuales")
        automation_layout = QVBoxLayout(automation_group)
        self.automation_list = QListWidget(self)
        self.automation_list.setMaximumHeight(110)
        automation_layout.addWidget(self.automation_list)
        self._populate_automations()
        automation_buttons = QHBoxLayout()
        add_automation = QPushButton("Crear flujo", self)
        add_automation.clicked.connect(self._add_automation)
        remove_automation = QPushButton("Eliminar flujo", self)
        remove_automation.clicked.connect(self._remove_automation)
        automation_buttons.addWidget(add_automation)
        automation_buttons.addWidget(remove_automation)
        automation_buttons.addStretch()
        automation_layout.addLayout(automation_buttons)
        acttab_layout.addWidget(automation_group)

        # ── Pestaña 8: Acerca de ──
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setContentsMargins(28, 24, 28, 24)
        about_layout.setSpacing(16)

        about_card = QGroupBox()
        about_card.setObjectName("aboutCard")
        about_card_layout = QVBoxLayout(about_card)
        about_card_layout.setContentsMargins(24, 22, 24, 24)
        about_card_layout.setSpacing(12)

        identity = QHBoxLayout()
        identity.setSpacing(16)
        about_icon = QLabel(about_card)
        about_icon.setPixmap(load_icon(APP_ICON_FILE).pixmap(72, 72))
        about_icon.setFixedSize(72, 72)
        identity_text = QVBoxLayout()
        identity_text.setSpacing(3)
        about_title = QLabel("TextPik", about_card)
        about_title.setObjectName("aboutTitle")
        self.about_version_label = QLabel(f"Versión {APP_VERSION}", about_card)
        self.about_version_label.setObjectName("versionBadge")
        self.about_version_label.setMaximumWidth(160)
        identity_text.addWidget(about_title)
        identity_text.addWidget(self.about_version_label)
        identity_text.addStretch()
        identity.addWidget(about_icon)
        identity.addLayout(identity_text, 1)
        about_card_layout.addLayout(identity)

        self.about_description_label = QLabel(
            "Una barra de acciones rápida, privada y contextual para trabajar "
            "con texto seleccionado en Linux. Diseñada para integrarse con "
            "Wayland y X11 sin interrumpir tu flujo de trabajo.",
            about_card,
        )
        self.about_description_label.setObjectName("aboutDescription")
        self.about_description_label.setWordWrap(True)
        about_card_layout.addWidget(self.about_description_label)

        author = QLabel("Creado por Cristian Rosas  ·  @pitydah", about_card)
        author.setObjectName("mutedText")
        about_card_layout.addWidget(author)

        about_buttons = QHBoxLayout()
        about_buttons.setSpacing(9)
        self.github_profile_button = QPushButton("Ver perfil en GitHub", about_card)
        self.github_profile_button.setObjectName("githubProfileButton")
        self.github_profile_button.setCursor(Qt.PointingHandCursor)
        self.github_profile_button.clicked.connect(
            lambda: self._open_external_url(GITHUB_PROFILE_URL)
        )
        self.sponsor_button = QPushButton(
            "Contribuir en GitHub Sponsors", about_card
        )
        self.sponsor_button.setObjectName("sponsorButton")
        self.sponsor_button.setCursor(Qt.PointingHandCursor)
        self.sponsor_button.clicked.connect(
            lambda: self._open_external_url(GITHUB_SPONSORS_URL)
        )
        about_buttons.addWidget(self.github_profile_button)
        about_buttons.addWidget(self.sponsor_button)
        about_buttons.addStretch()
        about_card_layout.addLayout(about_buttons)

        support_note = QLabel(
            "TextPik es software libre. Tu contribución ayuda a mantener el "
            "desarrollo, las pruebas multidistribución y el soporte de Wayland.",
            about_card,
        )
        support_note.setObjectName("mutedText")
        support_note.setWordWrap(True)
        about_card_layout.addWidget(support_note)

        about_layout.addWidget(about_card)
        about_layout.addStretch()

        # ── Montar tabs ──
        tabs.addTab(ap_tab, "  Apariencia  ")
        tabs.addTab(beh_tab, "  Comportamiento  ")
        tabs.addTab(flt_tab, "  Filtros  ")
        tabs.addTab(wl_tab, "  Wayland  ")
        tabs.addTab(system_tab, "  Sistema  ")
        tabs.addTab(diag_tab, "  Diagnostico  ")
        tabs.addTab(acttab, "  Acciones  ")
        tabs.addTab(about_tab, "  Acerca de  ")
        layout.addWidget(tabs, 1)

        # ── Botones OK / Cancelar / Aplicar ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_clicked)
        buttons.button(QDialogButtonBox.Ok).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.button(QDialogButtonBox.Apply).setText("Aplicar")
        layout.addWidget(buttons)
        self._apply_premium_style()

    def _apply_premium_style(self):
        dark = color_luminance(self.settings["popup_background_color"]) < 0.5
        bg, panel, field, fg, muted, accent = (
            ("#191a1d", "#23252a", "#2d3036", "#f4f5f7", "#aeb3bd", "#7c9cff")
            if dark
            else ("#f5f6f8", "#ffffff", "#eef0f4", "#202228", "#69707d", "#4263eb")
        )
        border = "#393c44" if dark else "#d9dde5"
        self.setStyleSheet(
            f"""
            QDialog {{ background: {bg}; color: {fg}; }}
            QLabel, QCheckBox, QRadioButton {{ color: {fg}; background: transparent; }}
            QLabel#heroTitle {{ font-size: 20px; font-weight: 700; color: {fg}; }}
            QLabel#heroSubtitle, QLabel#mutedText {{ color: {muted}; }}
            QLabel#aboutTitle {{ font-size: 25px; font-weight: 750; color: {fg}; }}
            QLabel#aboutDescription {{ color: {fg}; font-size: 13px; }}
            QLabel#versionBadge {{ background: {field}; color: {accent};
                border: 1px solid {border}; border-radius: 8px;
                padding: 4px 8px; font-weight: 650; }}
            QTabWidget::pane {{ background: {panel}; border: 1px solid {border};
                border-radius: 12px; top: -1px; }}
            QTabBar::tab {{ background: transparent; color: {muted}; padding: 9px 12px;
                margin-right: 2px; border-bottom: 2px solid transparent; }}
            QTabBar::tab:selected {{ color: {fg}; border-bottom: 2px solid {accent}; }}
            QGroupBox {{ background: {panel}; border: 1px solid {border};
                border-radius: 10px; margin-top: 10px; padding: 12px 8px 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px;
                color: {fg}; font-weight: 650; }}
            QLineEdit, QSpinBox, QComboBox, QTextEdit, QListWidget {{ background: {field};
                color: {fg}; border: 1px solid {border}; border-radius: 8px;
                padding: 6px; selection-background-color: {accent}; }}
            QPushButton {{ background: {field}; color: {fg}; border: 1px solid {border};
                border-radius: 8px; padding: 7px 12px; }}
            QPushButton:hover {{ border-color: {accent}; background: {panel}; }}
            QPushButton:pressed {{ background: {accent}; color: white; }}
            QPushButton#sponsorButton {{ background: {accent}; color: white;
                border-color: {accent}; font-weight: 700; }}
            QPushButton#sponsorButton:hover {{ background: {accent};
                border-color: {fg}; }}
            QGroupBox#aboutCard {{ margin-top: 0; padding: 0;
                border-radius: 14px; }}
            QCheckBox {{ spacing: 7px; }}
            QToolTip {{ background: {panel}; color: {fg}; border: 1px solid {border}; }}
            """
        )

    @staticmethod
    def _open_external_url(url):
        target = QUrl(str(url))
        if target.scheme() != "https" or target.host() != "github.com":
            return False
        return QDesktopServices.openUrl(target)

    def _spin(self, lo, hi, val):
        s = QSpinBox(self)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _make_swatch(self, grid, row, col, key, label):
        container = QWidget(self)
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        swatch = QPushButton(container)
        swatch.setFixedSize(44, 24)
        swatch.setCursor(Qt.PointingHandCursor)
        swatch.clicked.connect(
            lambda checked=False, k=key, b=swatch: self._pick_color(k, b)
        )
        self._update_swatch(swatch, self.settings[key])
        name = QLabel(label, container)
        name.setStyleSheet("font-size: 11px;")
        h.addWidget(swatch)
        h.addWidget(name)
        self._color_swatches[key] = swatch
        grid.addWidget(container, row, col)

    def _pick_color(self, key, button):
        color = QColorDialog.getColor(QColor(self.settings[key]), self, "Elegir color")
        if color.isValid():
            self.settings[key] = color.name()
            self._update_swatch(button, color.name())

    def _update_swatch(self, button, color_name):
        button.setStyleSheet(
            "background-color: %s; border: 1px solid #888; border-radius: 4px;"
            % color_name
        )
        button.setToolTip(color_name)

    def _apply_theme_preset(self):
        preset = self.theme_combo.currentData()
        if preset == "custom":
            return
        presets = {
            "light": {
                "popup_background_color": "#f7f7f7",
                "popup_border_color": "#d0d0d0",
                "popup_button_color": "#ffffff",
                "popup_hover_color": "#eeeeee",
                "popup_button_border_color": "#c8c8c8",
            },
            "dark": {
                "popup_background_color": "#2d2d2d",
                "popup_border_color": "#555555",
                "popup_button_color": "#383838",
                "popup_hover_color": "#4a4a4a",
                "popup_button_border_color": "#555555",
            },
            "oled": {
                "popup_background_color": "#000000",
                "popup_border_color": "#333333",
                "popup_button_color": "#090909",
                "popup_hover_color": "#222222",
                "popup_button_border_color": "#333333",
            },
        }
        colors = presets.get(preset, {})
        for key, value in colors.items():
            self.settings[key] = value
            swatch = self._color_swatches.get(key)
            if swatch:
                self._update_swatch(swatch, value)

    def _refresh_diagnostics(self):
        self.diagnostics_text.setPlainText(self.controller.build_diagnostics())

    def _test_popup(self):
        settings, actions = self.collect_settings()
        if actions != self.controller.actions:
            self.controller.actions = actions
            self.controller.save_actions()
            self.controller.popup.set_actions(actions)
        self.controller.update_settings(settings)
        self.controller.test_popup()
        self._refresh_diagnostics()

    def _populate_blocked_list(self):
        self.blocked_list.clear()
        for app in self.settings.get("blocked_apps", []):
            self.blocked_list.addItem(app)

    def _populate_context_profiles(self):
        self.context_profiles_list.clear()
        for profile in self.context_profiles:
            scope = profile.get("application") or ", ".join(
                profile.get("text_types", [])
            )
            item = QListWidgetItem(
                f"{profile.get('name', 'Perfil')}  ·  {scope}",
                self.context_profiles_list,
            )
            item.setData(Qt.UserRole, dict(profile))
            item.setToolTip(
                "Arrastra para cambiar la prioridad · "
                f"{len(profile.get('action_ids', []))} acciones"
            )

    def _sync_context_profiles_from_list(self):
        self.context_profiles = [
            dict(self.context_profiles_list.item(index).data(Qt.UserRole) or {})
            for index in range(self.context_profiles_list.count())
        ]

    def _add_context_profile(self):
        dialog = ContextProfileDialog(self.actions, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.context_profiles.append(dialog.get_profile())
            self._populate_context_profiles()

    def _edit_context_profile(self):
        self._sync_context_profiles_from_list()
        row = self.context_profiles_list.currentRow()
        if row < 0:
            return
        dialog = ContextProfileDialog(
            self.actions, self.context_profiles[row], self
        )
        if dialog.exec() == QDialog.Accepted:
            self.context_profiles[row] = dialog.get_profile()
            self._populate_context_profiles()
            self.context_profiles_list.setCurrentRow(row)

    def _remove_context_profile(self):
        self._sync_context_profiles_from_list()
        row = self.context_profiles_list.currentRow()
        if row >= 0:
            self.context_profiles.pop(row)
            self._populate_context_profiles()

    def _add_blocked_app(self):
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self,
            "Anadir aplicacion",
            "Nombre de la clase de ventana (ej: firefox, konsole, code):",
        )
        if ok and text.strip():
            self.blocked_list.addItem(text.strip().lower())

    def _remove_blocked_app(self):
        row = self.blocked_list.currentRow()
        if row >= 0:
            self.blocked_list.takeItem(row)

    def _add_blocked_activity(self):
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self, "Anadir actividad", "UUID o nombre de la actividad de Plasma:"
        )
        if ok and text.strip():
            self.blocked_activities_list.addItem(text.strip())

    def _remove_blocked_activity(self):
        row = self.blocked_activities_list.currentRow()
        if row >= 0:
            self.blocked_activities_list.takeItem(row)

    def _populate_action_list(self):
        self.action_list.clear()
        for action in self.actions:
            availability = self.controller.action_integration_status(action)
            state = (
                "Disponible con fallback"
                if availability.degraded
                else ("Disponible" if availability.available else "No disponible")
            )
            item = QListWidgetItem(f"{action['name']}   ·   {state}")
            item.setData(Qt.UserRole, dict(action))
            icon, needs_recolor = resolve_action_icon(action["icon"])
            if not icon.isNull():
                if needs_recolor:
                    icon = recolor_icon(
                        icon,
                        icon_color_for_background(
                            self.settings["popup_background_color"]
                        ),
                        18,
                    )
                item.setIcon(icon)
            details = [action["cmd"], availability.label]
            if action.get("extension"):
                details.append(f"Extensión: {action['extension']}")
            if action.get("permissions"):
                details.append(
                    "Permisos: " + ", ".join(action.get("permissions", []))
                )
            if availability.degraded:
                details.append("Modo limitado")
            item.setToolTip("\n".join(details))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if action.get("enabled", True) else Qt.Unchecked
            )
            self.action_list.addItem(item)

    def _move_up(self):
        self._sync_actions_from_list()
        row = self.action_list.currentRow()
        if row <= 0:
            return
        item = self.action_list.takeItem(row)
        self.action_list.insertItem(row - 1, item)
        self.action_list.setCurrentRow(row - 1)
        self._sync_actions_from_list()

    def _move_down(self):
        self._sync_actions_from_list()
        row = self.action_list.currentRow()
        if row < 0 or row >= self.action_list.count() - 1:
            return
        item = self.action_list.takeItem(row)
        self.action_list.insertItem(row + 1, item)
        self.action_list.setCurrentRow(row + 1)
        self._sync_actions_from_list()

    def _add_action(self):
        self._sync_enabled_from_list()
        dialog = ActionEditDialog(parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        action = dialog.get_action()
        if action is None:
            return
        self.actions.append(action)
        self._populate_action_list()
        self.action_list.setCurrentRow(self.action_list.count() - 1)

    def _edit_action(self):
        self._sync_actions_from_list()
        row = self.action_list.currentRow()
        if row < 0 or row >= len(self.actions):
            QMessageBox.information(
                self, "Editar accion", "Selecciona una accion primero."
            )
            return
        dialog = ActionEditDialog(dict(self.actions[row]), self)
        if dialog.exec() != QDialog.Accepted:
            return
        action = dialog.get_action()
        if action is None:
            return
        self.actions[row] = action
        self._populate_action_list()
        self.action_list.setCurrentRow(row)

    def _delete_action(self):
        self._sync_actions_from_list()
        row = self.action_list.currentRow()
        if row < 0 or row >= len(self.actions):
            QMessageBox.information(
                self, "Eliminar accion", "Selecciona una accion primero."
            )
            return
        answer = QMessageBox.question(
            self,
            "Eliminar accion",
            f"Eliminar '{self.actions[row]['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.actions.pop(row)
        self._populate_action_list()
        if self.action_list.count():
            self.action_list.setCurrentRow(min(row, self.action_list.count() - 1))

    def _sync_enabled_from_list(self):
        self._sync_actions_from_list()

    def _sync_actions_from_list(self):
        ordered_actions = []
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            action = dict(item.data(Qt.UserRole) or {})
            action["enabled"] = item.checkState() == Qt.Checked
            ordered_actions.append(action)
        self.actions = ordered_actions

    def _populate_automations(self):
        self.automation_list.clear()
        for flow in self.automations:
            operations = " → ".join(
                str(step.get("operation", "")) for step in flow.get("steps", [])
            )
            item = QListWidgetItem(f"{flow.get('name', 'Flujo')} · {operations}")
            item.setData(Qt.UserRole, flow.get("id"))
            self.automation_list.addItem(item)

    def _add_automation(self):
        from PySide6.QtWidgets import QInputDialog

        name, accepted = QInputDialog.getText(self, "Nuevo flujo", "Nombre:")
        if not accepted or not name.strip():
            return
        operations, accepted = QInputDialog.getText(
            self,
            "Pasos del flujo",
            "Operaciones separadas por coma\n"
            "(uppercase, lowercase, capitalize, remove-breaks):",
        )
        if not accepted:
            return
        allowed = {"uppercase", "lowercase", "capitalize", "remove-breaks"}
        values = [value.strip() for value in operations.split(",") if value.strip()]
        if not values or any(value not in allowed for value in values):
            QMessageBox.warning(self, "Flujo inválido", "Hay operaciones no admitidas")
            return
        identifier = stable_action_id(name, ",".join(values))[:80]
        self.automations.append(
            {
                "id": identifier,
                "name": name.strip()[:120],
                "enabled": True,
                "conditions": {"text_types": ["text"]},
                "steps": [{"operation": value} for value in values],
            }
        )
        self._populate_automations()

    def _remove_automation(self):
        row = self.automation_list.currentRow()
        if 0 <= row < len(self.automations):
            self.automations.pop(row)
            self._populate_automations()

    def collect_settings(self):
        self._sync_enabled_from_list()
        self._sync_context_profiles_from_list()
        self.settings["popup_icon_size"] = self.icon_size.value()
        self.settings["popup_button_padding"] = self.button_padding.value()
        self.settings["popup_spacing"] = self.popup_spacing.value()
        self.settings["popup_border_radius"] = self.radius.value()
        self.settings["popup_opacity"] = self.opacity.value() / 100
        self.settings["show_numeric_badges"] = self.show_numeric_badges.isChecked()
        self.settings["popup_delay_ms"] = self.popup_delay.value()
        self.settings["popup_auto_hide_ms"] = self.auto_hide.value()
        self.settings["popup_cursor_gap"] = self.cursor_gap.value()
        self.settings["confirm_terminal_execution"] = self.confirm_terminal.isChecked()
        self.settings["enable_wayland_polling"] = self.enable_wl_polling.isChecked()
        self.settings["popup_wayland_fallback_top"] = self.fallback_top.value()
        self.settings["popup_wayland_fallback_horizontal"] = (
            self.fallback_horizontal.currentData()
        )
        self.settings["max_selection_length"] = self.max_selection.value()
        self.settings["max_popup_actions"] = self.max_popup_actions.value()
        self.settings["show_all_popup_actions"] = (
            self.show_all_popup_actions.isChecked()
        )
        self.settings["show_on_selection"] = self.show_on_selection.isChecked()
        self.settings["start_at_login"] = self.start_at_login.isChecked()
        self.settings["disable_in_games"] = self.disable_in_games.isChecked()
        self.settings["disable_in_sensitive_fields"] = (
            self.disable_in_sensitive.isChecked()
        )
        self.settings["ignore_file_selections"] = (
            self.ignore_file_selections.isChecked()
        )
        self.settings["sticky_popup"] = self.sticky_popup.isChecked()
        self.settings["enable_global_hotkey"] = self.enable_global_hotkey.isChecked()
        self.settings["context_aware"] = self.context_aware.isChecked()
        self.settings["local_recommendations"] = (
            self.local_recommendations.isChecked()
        )
        self.settings["history_enabled"] = self.history_enabled.isChecked()
        self.settings["history_max_items"] = self.history_max_items.value()
        self.settings["context_profiles_enabled"] = (
            self.context_profiles_enabled.isChecked()
        )
        self.settings["context_profiles"] = list(self.context_profiles)
        self.settings["adaptive_popup"] = self.adaptive_popup.isChecked()
        self.settings["popup_min_confidence"] = self.popup_min_confidence.value()
        self.settings["popup_full_confidence"] = self.popup_full_confidence.value()
        self.settings["popup_compact_actions"] = self.popup_compact_actions.value()
        self.settings["theme_preset"] = self.theme_combo.currentData()
        self.settings["blocked_apps_enabled"] = self.blocked_apps_enabled.isChecked()
        self.settings["blocked_apps"] = [
            self.blocked_list.item(i).text() for i in range(self.blocked_list.count())
        ]
        self.settings["blocked_activities_enabled"] = (
            self.blocked_activities_enabled.isChecked()
        )
        self.settings["blocked_activities"] = [
            self.blocked_activities_list.item(i).text()
            for i in range(self.blocked_activities_list.count())
        ]
        self.settings["log_enabled"] = self.log_enabled.isChecked()
        return normalize_settings(self.settings), list(self.actions)

    def apply_clicked(self):
        settings, actions = self.collect_settings()
        actions = [
            action
            for action in actions
            if not str(action.get("cmd", "")).startswith("automation:")
        ]
        if actions != self.controller.actions:
            self.controller.actions = actions
            self.controller.save_actions()
            self.controller.popup.set_actions(actions)
        self.controller.update_settings(settings)
        write_json_atomic(AUTOMATIONS_FILE, {"automations": self.automations})
        self.controller.reload_automations()


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    """Ejecuta una función lenta sin bloquear el hilo gráfico."""

    def __init__(self, function):
        super().__init__()
        # PySide may otherwise destroy the QRunnable and its QObject signals in
        # the worker thread before queued receivers have processed the result.
        self.setAutoDelete(False)
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


class TextPikApp(QObject):
    hotkey_requested = Signal()
    background_error = Signal(str, str)
    atspi_selection_changed = Signal(object)
    runtime_probe_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setApplicationDisplayName("TextPik")
        self.app.setOrganizationName("pitydah")
        self.app.setOrganizationDomain("github.com/pitydah")
        self.app.setDesktopFileName(os.environ.get("FLATPAK_ID", APP_NAME))
        self.app.setWindowIcon(load_icon(APP_ICON_FILE, "edit-select-all"))
        self.app.setQuitOnLastWindowClosed(False)
        self.app.aboutToQuit.connect(self.cleanup)

        self.settings = load_settings()
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers = set()
        self._cleaned_up = False
        self.performance = PerformanceTracker(
            {
                "text-classification": 5.0,
                "action-planning": 5.0,
                "popup-hot-path": 50.0,
            }
        )
        setup_logging(self.settings)
        logger.info("Iniciando textpik con plataforma Qt: %s", self.app.platformName())
        log_cursor_position_diagnostics(self.app.platformName())

        self.lock_file = QLockFile(str(CONFIG_DIR / "textpik.lock"))
        self.lock_file.setStaleLockTime(0)
        if not self.lock_file.tryLock(100):
            logger.warning("textpik ya esta ejecutandose; saliendo")
            if check_command("notify-send"):
                subprocess.Popen(
                    ["notify-send", APP_NAME, "textpik ya esta ejecutandose"]
                )
            sys.exit(0)

        check_runtime_dependencies()
        self.cursor_bridge = None
        self.cursor_bridge_adaptor = None
        self.cursor_bridge_bus = None
        self.setup_cursor_bridge()

        self.actions = self.load_actions()
        if not self.settings.get("spelling_action_migrated", False):
            if not any(action.get("cmd") == "spellcheck" for action in self.actions):
                spelling_action = next(
                    action
                    for action in DEFAULT_ACTIONS
                    if action.get("cmd") == "spellcheck"
                )
                migrated = migrate_action(spelling_action)
                if migrated is not None:
                    self.actions.append(migrated)
                    self.save_actions()
            self.settings["spelling_action_migrated"] = True
            self.save_settings()
        new_core_commands = {
            "insight",
            "grammar",
            "undo",
            "textpik-history",
            "ocr-image",
            "ocr-region",
        }
        existing_commands = {action.get("cmd") for action in self.actions}
        added_core_action = False
        for default_action in DEFAULT_ACTIONS:
            if (
                default_action.get("cmd") in new_core_commands
                and default_action.get("cmd") not in existing_commands
            ):
                migrated = migrate_action(default_action)
                if migrated is not None:
                    self.actions.append(migrated)
                    existing_commands.add(migrated["cmd"])
                    added_core_action = True
        if added_core_action:
            self.save_actions()
        extension_actions, self.extension_issues = inspect_local_extensions(
            EXTENSIONS_DIR
        )
        existing_ids = {action.get("id") for action in self.actions}
        for action in extension_actions:
            action_id = action.get("id")
            if action_id in existing_ids:
                continue
            self.actions.append(action)
            existing_ids.add(action_id)
        self.automations = self._load_automations()
        for flow in self.automations:
            action_id = f"automation-{flow['id']}"
            if action_id in existing_ids:
                continue
            self.actions.append(
                {
                    "id": action_id,
                    "name": flow["name"],
                    "icon": flow.get("icon", "capitalize.svg"),
                    "cmd": f"automation:{flow['id']}",
                    "enabled": bool(flow.get("enabled", True)),
                    "context": list(flow.get("conditions", {}).get("text_types", [])),
                    "permissions": [],
                    "category": "Automatizaciones",
                }
            )
            existing_ids.add(action_id)
        self.permissions = PermissionStore(PERMISSIONS_FILE)
        self.spelling = SpellingService(
            ignored=self.settings.get("spelling_ignored_words", []),
            personal=self.settings.get("spelling_personal_words", []),
        )
        self.grammar = LanguageToolService()
        self.ollama = OllamaProvider()
        self.ocr = TesseractProvider()
        self.undo = UndoManager()
        try:
            ranking_payload = read_json(RANKING_FILE) if RANKING_FILE.exists() else {}
        except (OSError, ValueError):
            ranking_payload = {}
        self.ranker = LocalActionRanker(ranking_payload)
        self.history = HistoryStore(
            HISTORY_FILE,
            maximum=self.settings.get("history_max_items", 100),
            max_age_days=self.settings.get("history_max_age_days", 30),
            key=os.environ.get("TEXTPIK_HISTORY_KEY", "").encode() or None,
        )
        self.atspi = AtspiSelectionBackend()
        self.popup_state = PopupStateMachine()
        self._service_cache = (0.0, set())
        self.anchor_resolver = AnchorResolver()
        self.selection_context = SelectionContext(text="")
        self._selection_session = 0
        self.monitor = (
            WaylandSelectionMonitor(self.settings)
            if is_qt_wayland()
            else X11SelectionMonitor(self.settings)
        )
        self.monitor.selection_changed.connect(self._monitor_selection_changed)
        self.monitor.selection_cleared.connect(self._monitor_selection_cleared)

        self.popup = PopupWindow(self.actions, self.monitor, self.settings)
        self.popup.action_triggered.connect(self.execute_action)
        self.popup.pin_requested.connect(self.pin_action)
        self.popup.suppress_app_requested.connect(self.block_application)
        self.popup.interaction_started.connect(self.popup_state.interacting)
        self.popup.interaction_finished.connect(self._finish_popup_interaction)
        self.popup.dismissed.connect(self._on_popup_dismissed)
        self.pointer = X11Pointer()
        self.process_filter = ProcessFilter(self.settings)
        self._animating = False
        self._popup_animation = None
        self._popup_immunity_until = 0.0
        self._outside_count = 0
        self._selection_released = False
        self._last_popup_text = ""
        self._last_popup_at = 0.0
        self._last_intent_confidence = 0.0
        self._last_context_profile = ""
        self._last_text_types = frozenset()
        self._last_atspi_signature = None
        self._pending_atspi_node = None
        self._runtime_probe_running = False
        self._runtime_snapshot = {
            "game": False,
            "blocked": False,
            "activity_blocked": False,
            "compositor_anchor": None,
        }

        self.atspi_selection_changed.connect(self._queue_atspi_selection)
        self.atspi_events_active = self.atspi.subscribe_selection_changes(
            self.atspi_selection_changed.emit
        )
        self.atspi_event_timer = QTimer(self)
        self.atspi_event_timer.setSingleShot(True)
        self.atspi_event_timer.timeout.connect(self._consume_atspi_selection)

        self.atspi_timer = QTimer(self)
        self.atspi_timer.timeout.connect(self._poll_atspi_selection)
        if (
            is_qt_wayland()
            and self.atspi.available
            and self.settings.get("enable_wayland_polling", True)
        ):
            # Events are primary. A low-frequency safety poll covers apps that
            # expose AT-SPI text but fail to emit selection notifications.
            self.atspi_timer.start(1500 if self.atspi_events_active else 300)

        self.runtime_probe_ready.connect(self._apply_runtime_probe)
        self.runtime_probe_timer = QTimer(self)
        self.runtime_probe_timer.timeout.connect(self._schedule_runtime_probe)
        self.runtime_probe_timer.start(2500)
        self._schedule_runtime_probe()

        self.activity_probe_timer = QTimer(self)
        self.activity_probe_timer.timeout.connect(self._refresh_activity_snapshot)
        self.activity_probe_timer.start(3000)

        self.service_probe_timer = QTimer(self)
        self.service_probe_timer.timeout.connect(self._refresh_service_cache)
        self.service_probe_timer.start(10000)

        self.hide_check_timer = QTimer(self)
        self.hide_check_timer.timeout.connect(self.hide_popup_on_external_click)
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.timeout.connect(self._auto_hide_popup)
        self.app.applicationStateChanged.connect(self.on_application_state_changed)
        self.app.focusWindowChanged.connect(self.on_focus_window_changed)

        self.hotkey_active = False
        self.keyboard = None
        self.hotkey_handle = None
        self.hotkey_requested.connect(self.hotkey_triggered)
        self.background_error.connect(
            lambda title, message: QMessageBox.warning(None, title, message)
        )
        self.setup_hotkey()

        self.create_tray_icon()
        self.set_autostart_enabled(self.settings.get("start_at_login", True))

    def setup_cursor_bridge(self):
        if not is_qt_wayland() or not is_kde() or not qt_dbus_available():
            return

        try:
            from PySide6.QtDBus import QDBusConnection

            bus = QDBusConnection.sessionBus()
            if not bus.registerService(CURSOR_BRIDGE_SERVICE):
                logger.warning(
                    "No se pudo registrar servicio D-Bus %s", CURSOR_BRIDGE_SERVICE
                )
                return

            bridge = CursorBridge()
            bridge._on_click_outside = lambda: (
                self.popup.is_interacting() or self.hide_popup()
            )
            adaptor = create_cursor_bridge_adaptor(bridge)
            if not bus.registerObject(
                CURSOR_BRIDGE_PATH,
                bridge,
                QDBusConnection.ExportAdaptors,
            ):
                bus.unregisterService(CURSOR_BRIDGE_SERVICE)
                logger.warning(
                    "No se pudo registrar objeto D-Bus %s", CURSOR_BRIDGE_PATH
                )
                return

            self.cursor_bridge = bridge
            self.cursor_bridge_adaptor = adaptor
            self.cursor_bridge_bus = bus
            logger.info(
                "Puente de cursor KWin registrado en %s %s %s",
                CURSOR_BRIDGE_SERVICE,
                CURSOR_BRIDGE_PATH,
                CURSOR_BRIDGE_INTERFACE,
            )
        except Exception as exc:
            logger.warning("No se pudo iniciar puente de cursor KWin: %s", exc)

    def setup_hotkey(self):
        self.teardown_hotkey()
        if not self.settings.get("enable_global_hotkey", False):
            return
        try:
            import keyboard

            self.keyboard = keyboard
            self.hotkey_handle = self.keyboard.add_hotkey(
                "ctrl+shift+p", self.hotkey_requested.emit
            )
            self.hotkey_active = True
        except ImportError:
            print("Libreria 'keyboard' no encontrada. Atajo global deshabilitado.")
        except Exception as exc:
            print("Error registrando atajo global:", exc)

    def teardown_hotkey(self):
        if self.hotkey_active and self.keyboard is not None:
            try:
                if self.hotkey_handle is not None:
                    self.keyboard.remove_hotkey(self.hotkey_handle)
            except Exception as exc:
                logger.debug("Error al desregistrar hotkey: %s", exc)
        self.hotkey_active = False
        self.hotkey_handle = None

    def _schedule_runtime_probe(self):
        """Refresh slow desktop facts outside the selection-to-popup path."""
        if self._runtime_probe_running:
            return
        needs_process = self.settings.get("disable_in_games", False) or self.settings.get(
            "blocked_apps_enabled", False
        )
        desktop = desktop_environment()
        needs_compositor = is_qt_wayland() and any(
            name in desktop for name in ("hyprland", "sway")
        )
        if not needs_process and not needs_compositor:
            return
        self._runtime_probe_running = True
        settings = dict(self.settings)

        def task():
            process_filter = ProcessFilter(settings)
            anchor = None
            if needs_compositor:
                candidates = (hyprland_cursor_anchor(), sway_cursor_anchor())
                anchor = self.anchor_resolver.resolve(candidates)
            return {
                "game": process_filter.is_foreground_process_game()
                if settings.get("disable_in_games", False)
                else False,
                "blocked": process_filter.is_foreground_process_blocked()
                if settings.get("blocked_apps_enabled", False)
                else False,
                "compositor_anchor": anchor,
            }

        worker = FunctionWorker(task)
        worker.signals.succeeded.connect(self.runtime_probe_ready.emit)
        worker.signals.failed.connect(lambda _: self._finish_runtime_probe())
        self._start_worker(worker)

    def _start_worker(self, worker):
        """Keep a strong reference until all queued result signals are handled."""
        self._active_workers.add(worker)
        worker.signals.finished.connect(
            lambda active_worker=worker: self._worker_finished(active_worker)
        )
        self.thread_pool.start(worker)

    def _worker_finished(self, worker):
        self._active_workers.discard(worker)

    def _finish_runtime_probe(self):
        self._runtime_probe_running = False

    def _apply_runtime_probe(self, snapshot):
        if isinstance(snapshot, dict):
            self._runtime_snapshot.update(snapshot)
        self._runtime_probe_running = False

    def _refresh_activity_snapshot(self):
        # QtDBus objects belong to the UI thread, but this probe is deliberately
        # decoupled from popup display and only runs when the feature is enabled.
        if self.settings.get("blocked_activities_enabled", False):
            self._runtime_snapshot["activity_blocked"] = (
                self.process_filter.is_foreground_activity_blocked()
            )
        else:
            self._runtime_snapshot["activity_blocked"] = False

    def _refresh_service_cache(self):
        # Force refresh before action planning needs integration availability.
        self._service_cache = (0.0, self._service_cache[1])
        self._desktop_dbus_services()

    def _begin_selection_session(self, source):
        self._selection_session += 1
        logger.debug(
            "Sesión de selección %d iniciada por %s",
            self._selection_session,
            source,
        )
        return self._selection_session

    def _selection_session_is_current(self, session_id):
        return session_id == self._selection_session

    def _monitor_selection_changed(self):
        session_id = self._begin_selection_session("clipboard")
        self.show_popup(session_id=session_id)

    def _monitor_selection_cleared(self):
        self._begin_selection_session("clipboard-cleared")
        self.hide_popup(invalidate_session=False)

    def _queue_atspi_selection(self, node):
        if not self.monitor._active or self.popup.is_interacting():
            return
        session_id = self._begin_selection_session("atspi-event")
        self._pending_atspi_node = (node, session_id)
        # Accessibility events can arrive before the final range is committed.
        self.popup_state.transition(PopupPhase.STABILIZING)
        self.atspi_event_timer.start(max(45, self.settings.get("popup_delay_ms", 0)))

    def _finish_popup_interaction(self):
        if self.popup.isVisible():
            self.popup_state.visible()
        else:
            self.popup_state.reset()

    def _consume_atspi_selection(self):
        if self.monitor._primary_button_pressed():
            self.atspi_event_timer.start(45)
            return
        pending, self._pending_atspi_node = self._pending_atspi_node, None
        if pending is None:
            return
        node, session_id = pending
        if not self._selection_session_is_current(session_id):
            logger.debug("Evento AT-SPI obsoleto descartado: %s", session_id)
            return
        context = self.atspi.read_selection(node)
        if not self._selection_session_is_current(session_id):
            return
        if context is None or not context.text.strip():
            self.hide_popup(invalidate_session=False)
            return
        if len(context.text.strip()) > self.settings.get("max_selection_length", 5000):
            self.hide_popup(invalidate_session=False)
            return
        self.selection_context = context
        self.monitor._last_text = context.text.strip()
        self.show_popup(context=context, session_id=session_id)

    def hotkey_triggered(self):
        if self.popup.isVisible():
            self.hide_popup()
        else:
            self.show_popup(force=True)
            if self.popup.isVisible():
                QTimer.singleShot(0, self._focus_popup_for_keyboard)

    def _focus_popup_for_keyboard(self):
        """Only an explicit hotkey may take focus from the user's application."""
        self.popup.activateWindow()
        self.popup.setFocus(Qt.ShortcutFocusReason)

    def on_application_state_changed(self, state):
        if self.popup.is_interacting():
            return
        if state != Qt.ApplicationActive:
            self.hide_popup()

    def on_focus_window_changed(self, focus_window):
        if not self.popup.isVisible():
            return
        if self.popup.is_interacting():
            return
        popup_window = self.popup.windowHandle()
        if focus_window is popup_window:
            return
        logger.info("El foco cambio fuera del popup; ocultando")
        self.hide_popup()

    def hide_popup_on_external_click(self):
        if not self.popup.isVisible():
            self.hide_check_timer.stop()
            return

        if self.popup.is_interacting():
            self._outside_count = 0
            return

        if time.monotonic() < self._popup_immunity_until:
            self._outside_count = 0
            return

        pointer_state = self.pointer.state()
        if pointer_state is None:
            buttons_pressed = QApplication.mouseButtons() != Qt.NoButton
            px, py = QCursor.pos().x(), QCursor.pos().y()
        else:
            px, py, mask = pointer_state
            buttons_pressed = bool(mask & X11Pointer.BUTTON_MASKS)

        if not self._selection_released:
            if not buttons_pressed:
                self._selection_released = True
            return

        local_pos = self.popup.mapFromGlobal(QPoint(px, py))
        outside = not self.popup.rect().contains(local_pos)

        if buttons_pressed and outside:
            if self.popup.is_interacting():
                self._outside_count += 1
                return
            logger.info("Click externo detectado; ocultando popup")
            self.hide_popup()

    def load_actions(self):
        return load_actions_file()

    def save_actions(self):
        write_json_atomic(ACTIONS_FILE, self.actions)

    def save_settings(self):
        self.settings = normalize_settings(self.settings)
        write_json_atomic(SETTINGS_FILE, self.settings)

    def set_autostart_enabled(self, enabled):
        """Synchronize XDG autostart without desktop-specific control panels."""
        if os.environ.get("FLATPAK_ID"):
            logger.info("Autoinicio gestionado externamente dentro de Flatpak")
            return
        if not enabled:
            AUTOSTART_FILE.unlink(missing_ok=True)
            return
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        executable = shutil.which("textpik")
        command = executable or shlex.join(
            [sys.executable, str(Path(__file__).resolve())]
        )
        AUTOSTART_FILE.write_text(
            "\n".join(
                (
                    "[Desktop Entry]",
                    "Type=Application",
                    "Name=TextPik",
                    "Comment=Acciones rápidas para texto seleccionado",
                    f"Exec={command}",
                    "Icon=textpik",
                    "Terminal=false",
                    "NoDisplay=true",
                    "X-GNOME-Autostart-enabled=true",
                    "X-KDE-autostart-phase=2",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def reload_actions(self):
        self.actions = self.load_actions()
        self.popup.set_actions(self.actions)
        QMessageBox.information(None, "Configuracion", "Acciones recargadas.")

    def reload_automations(self):
        self.actions = [
            action
            for action in self.actions
            if not str(action.get("cmd", "")).startswith("automation:")
        ]
        self.automations = self._load_automations()
        for flow in self.automations:
            self.actions.append(
                {
                    "id": f"automation-{flow['id']}",
                    "name": flow["name"],
                    "icon": flow.get("icon", "capitalize.svg"),
                    "cmd": f"automation:{flow['id']}",
                    "enabled": bool(flow.get("enabled", True)),
                    "context": list(
                        flow.get("conditions", {}).get("text_types", [])
                    ),
                    "permissions": [],
                    "category": "Automatizaciones",
                }
            )
        self.popup._actions_key = None
        self.popup.set_actions(self.actions)

    def reload_settings(self):
        self.settings = load_settings()
        setup_logging(self.settings)
        self.monitor.settings = self.settings
        self.process_filter.settings = self.settings
        self.spelling = SpellingService(
            ignored=self.settings.get("spelling_ignored_words", []),
            personal=self.settings.get("spelling_personal_words", []),
        )
        self.history = HistoryStore(
            HISTORY_FILE,
            maximum=self.settings.get("history_max_items", 100),
            max_age_days=self.settings.get("history_max_age_days", 30),
            key=os.environ.get("TEXTPIK_HISTORY_KEY", "").encode() or None,
        )
        self.popup.apply_settings(self.settings)
        if hasattr(self.monitor, "_poll_timer"):
            if self.settings.get("enable_wayland_polling", True) and not getattr(
                self.monitor, "_use_wl_paste", False
            ):
                self.monitor._poll_timer.start(500)
            else:
                self.monitor._poll_timer.stop()
        if is_qt_wayland() and self.atspi.available:
            if self.settings.get("enable_wayland_polling", True):
                self.atspi_timer.start(1500 if self.atspi_events_active else 300)
            else:
                self.atspi_timer.stop()
        self._schedule_runtime_probe()
        self._refresh_activity_snapshot()
        QMessageBox.information(None, "Configuracion", "Ajustes recargados.")

    def _animate_popup_fade_in(self):
        if self._animating:
            return
        target = self.settings["popup_opacity"]
        # QtWayland no soporta windowOpacity
        if is_qt_wayland():
            self._animating = False
            return
        self.popup.setWindowOpacity(0.0)
        try:
            from PySide6.QtCore import QPropertyAnimation

            self._animating = True
            self._popup_animation = QPropertyAnimation(
                self.popup, b"windowOpacity", self
            )
            self._popup_animation.setDuration(120)
            self._popup_animation.setStartValue(0.0)
            self._popup_animation.setEndValue(target)
            self._popup_animation.finished.connect(
                lambda: setattr(self, "_animating", False)
            )
            self._popup_animation.start()
        except Exception as exc:
            logger.debug("Animacion del popup fallo: %s", exc)
            self.popup.setWindowOpacity(target)
            self._animating = False

    def _on_popup_dismissed(self):
        self._begin_selection_session("popup-dismissed")
        self.popup_state.reset()

    def hide_popup(self, invalidate_session=True):
        if invalidate_session:
            self._begin_selection_session("popup-hidden")
        self.hide_check_timer.stop()
        self.auto_hide_timer.stop()
        self._popup_immunity_until = 0.0
        self._outside_count = 0
        self._selection_released = False
        if self.popup.isVisible():
            if not self._animating:
                self.popup.hide()
            else:
                self._animating = False
                self.popup.hide()
        self.popup_state.reset()

    def _suppress_popup(self, reason):
        self.hide_popup(invalidate_session=False)
        self.popup_state.suppress(reason)

    def update_settings(self, settings):
        hotkey_was_enabled = self.settings.get("enable_global_hotkey", False)
        autostart_was_enabled = self.settings.get("start_at_login", True)
        self.settings = normalize_settings(settings)
        self.save_settings()
        setup_logging(self.settings)
        self.monitor.settings = self.settings
        self.process_filter.settings = self.settings
        self.spelling = SpellingService(
            ignored=self.settings.get("spelling_ignored_words", []),
            personal=self.settings.get("spelling_personal_words", []),
        )
        self.history = HistoryStore(
            HISTORY_FILE,
            maximum=self.settings.get("history_max_items", 100),
            max_age_days=self.settings.get("history_max_age_days", 30),
            key=os.environ.get("TEXTPIK_HISTORY_KEY", "").encode() or None,
        )
        self.popup.apply_settings(self.settings)
        self.popup.set_actions(self.popup.actions)
        if hotkey_was_enabled != self.settings.get("enable_global_hotkey", False):
            self.setup_hotkey()
        if autostart_was_enabled != self.settings.get("start_at_login", True):
            self.set_autostart_enabled(self.settings["start_at_login"])

        if hasattr(self.monitor, "_poll_timer"):
            if self.settings.get("enable_wayland_polling", True) and not getattr(
                self.monitor, "_use_wl_paste", False
            ):
                self.monitor._poll_timer.start(500)
            else:
                self.monitor._poll_timer.stop()
        if is_qt_wayland() and self.atspi.available:
            if self.settings.get("enable_wayland_polling", True):
                self.atspi_timer.start(1500 if self.atspi_events_active else 300)
            else:
                self.atspi_timer.stop()
        self._schedule_runtime_probe()
        self._refresh_activity_snapshot()

    def build_diagnostics(self):
        bridge_status = "inactivo"
        if kwin_bridge_cursor is not None:
            x, y, timestamp = kwin_bridge_cursor
            age = time.monotonic() - timestamp
            bridge_status = f"activo ({x},{y}, hace {age:.1f}s)"

        enabled_actions = len([a for a in self.actions if a.get("enabled", True)])
        popup_geo = self.popup.geometry() if hasattr(self, "popup") else "sin popup"
        performance = getattr(self, "performance", None)
        performance_lines = []
        if performance is not None:
            performance_lines = [
                (
                    f"Latencia {metric.name}: {metric.last_ms:.2f} ms "
                    f"(media {metric.average_ms:.2f}, max {metric.maximum_ms:.2f})"
                )
                for metric in performance.snapshots()
            ]
        lines = [
            f"Sesion: {os.environ.get('XDG_SESSION_TYPE', '') or 'desconocida'}",
            f"Escritorio: {desktop_environment() or 'desconocido'}",
            f"Qt platform: {self.app.platformName()}",
            f"DISPLAY: {'si' if os.environ.get('DISPLAY') else 'no'}",
            f"WAYLAND_DISPLAY: {'si' if os.environ.get('WAYLAND_DISPLAY') else 'no'}",
            f"Backend seleccion: {'Wayland/wl-paste' if is_qt_wayland() else 'X11/PRIMARY'}",
            f"Monitor activo: {'si' if self.monitor._active else 'no'}",
            f"Mostrar al seleccionar: {'si' if self.settings.get('show_on_selection', True) else 'no'}",
            f"wl-paste: {'ok' if check_command('wl-paste') else 'falta'}",
            f"wl-copy: {'ok' if check_command('wl-copy') else 'falta'}",
            f"xdotool: {'ok' if check_command('xdotool') else 'falta'}",
            f"ydotool: {'ok' if check_command('ydotool') else 'falta'}",
            f"xdg-open: {'ok' if check_command('xdg-open') else 'falta'}",
            f"QtDBus: {'ok' if qt_dbus_available() else 'falta'}",
            f"AT-SPI: {'ok' if self.atspi.available else 'falta'}",
            f"AT-SPI deteccion: {'eventos' if self.atspi_events_active else 'polling/fallback'}",
            f"Estado popup: {self.popup_state.phase.value}",
            f"Autoinicio: {'activo' if AUTOSTART_FILE.exists() else 'inactivo'}",
            f"Puente KWin: {bridge_status}",
            f"Popup visible: {'si' if self.popup.isVisible() else 'no'}",
            f"Popup geometry: {popup_geo}",
            f"Acciones habilitadas: {enabled_actions}/{len(self.actions)}",
            f"Extensiones rechazadas: {len(self.extension_issues)}",
            f"Confianza última selección: {self._last_intent_confidence:.0%}",
            f"Perfil contextual: {self._last_context_profile or 'ninguno'}",
            *performance_lines,
            f"Log: {LOG_FILE}",
        ]
        return "\n".join(lines)

    def test_popup(self):
        if not self.monitor._active:
            self.monitor.resume()
        self.monitor._last_text = "Texto de prueba de textpik"
        self.show_popup(force=True)

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.settings, self.actions, self)
        if dialog.exec() == QDialog.Accepted:
            settings, actions = dialog.collect_settings()
            if actions != self.actions:
                self.actions = actions
                self.save_actions()
                self.popup.set_actions(actions)
            self.update_settings(settings)

    def request_cursor_update(self):
        if not is_qt_wayland() or not is_kde() or not qt_dbus_available():
            return
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

            bus = QDBusConnection.sessionBus()
            for service, path in KWIN_CURSOR_DBUS_CANDIDATES:
                iface = QDBusInterface(service, path, "org.kde.KWin.Cursor", bus)
                if not iface.isValid():
                    continue
                reply = iface.call("cursorPos")
                if reply.type() != QDBusMessage.MessageType.ErrorMessage:
                    values = reply.arguments()
                    if values:
                        from PySide6.QtCore import QPoint as QtPoint

                        pos = values[0]
                        if isinstance(pos, QtPoint) and self.cursor_bridge is not None:
                            self.cursor_bridge.update_cursor(pos.x(), pos.y())
                            return
                        if (
                            isinstance(pos, (tuple, list))
                            and len(pos) >= 2
                            and self.cursor_bridge is not None
                        ):
                            self.cursor_bridge.update_cursor(int(pos[0]), int(pos[1]))
                            return
        except Exception as exc:
            logger.debug("request_cursor_update fallo: %s", exc)

    def _fast_pointer_anchor(self):
        """Return cached/native coordinates without subprocess or D-Bus waits."""
        if is_qt_wayland() and kwin_bridge_cursor is not None:
            x, y, timestamp = kwin_bridge_cursor
            if time.monotonic() - timestamp <= CURSOR_BRIDGE_MAX_AGE_SECONDS:
                return PopupAnchor(x, y, AnchorSource.KWIN, 0.98)
        if not is_qt_wayland():
            state = self.pointer.state()
            if state is not None:
                return PopupAnchor(state[0], state[1], AnchorSource.X11_POINTER, 0.96)
        pos = QCursor.pos()
        return PopupAnchor(
            pos.x(),
            pos.y(),
            AnchorSource.QT_POINTER,
            0.72 if not is_qt_wayland() else 0.2,
        )

    def show_popup(self, force=False, context=None, session_id=None):
        if session_id is None:
            session_id = self._begin_selection_session(
                "manual" if force else "selection"
            )
        elif not self._selection_session_is_current(session_id):
            logger.debug("Solicitud de popup obsoleta descartada: %s", session_id)
            return
        if not force and not self.monitor._active:
            return
        if not force and not self.settings.get("show_on_selection", True):
            return
        if not force and self._runtime_snapshot.get("game", False):
            logger.info("Popup omitido por filtro anti-juegos")
            self._suppress_popup("game")
            return
        if not force and self._runtime_snapshot.get("activity_blocked", False):
            logger.info("Popup omitido por filtro de actividades")
            self._suppress_popup("activity")
            return
        text = self.monitor.get_last_text().strip()
        atspi_context = context or (
            self.atspi.read_selection() if self.atspi.available else None
        )
        if not self._selection_session_is_current(session_id):
            logger.debug("Lectura AT-SPI obsoleta descartada: %s", session_id)
            return
        if atspi_context and atspi_context.sensitive:
            self.selection_context = atspi_context
        elif atspi_context and (not text or atspi_context.text.strip() == text):
            self.selection_context = atspi_context
            text = atspi_context.text.strip()
        else:
            self.selection_context = SelectionContext(text=text)
        blocked_by_name = self.process_filter.matches_blocked_application(
            self.selection_context.application
        )
        if not force and (
            blocked_by_name
            or (
                not self.selection_context.application
                and self._runtime_snapshot.get("blocked", False)
            )
        ):
            logger.info("Popup omitido por filtro de aplicaciones")
            self._suppress_popup("application")
            return
        intent = evaluate_selection_intent(
            self.selection_context,
            text,
            ignore_files=(
                not force and self.settings.get("ignore_file_selections", True)
            ),
            reject_sensitive=(
                not force
                and self.settings.get("disable_in_sensitive_fields", True)
            ),
        )
        if not intent.allowed:
            logger.info(
                "Popup omitido por intención %s: app=%s role=%s",
                intent.reason,
                self.selection_context.application,
                self.selection_context.role,
            )
            self._suppress_popup(intent.reason)
            return
        if self.settings.get("history_enabled", False) and not self.selection_context.sensitive:
            try:
                self.history.add(
                    text,
                    self.selection_context.application,
                    self.settings.get("blocked_apps", []),
                )
            except (OSError, ValueError, ImportError):
                logger.debug("No se pudo actualizar el historial privado", exc_info=True)
        self._last_intent_confidence = 1.0 if force else intent.confidence
        adaptive_popup = self.settings.get("adaptive_popup", True)
        minimum_confidence = self.settings.get("popup_min_confidence", 45) / 100
        if not force and adaptive_popup and intent.confidence < minimum_confidence:
            logger.info(
                "Popup omitido por baja confianza: %.0f%% < %.0f%%",
                intent.confidence * 100,
                minimum_confidence * 100,
            )
            self._suppress_popup("low-confidence")
            return
        compact_popup = (
            not force
            and adaptive_popup
            and intent.confidence
            < self.settings.get("popup_full_confidence", 78) / 100
        )
        if text:
            now = time.monotonic()
            signature = (
                text,
                self.selection_context.application,
                self.selection_context.role,
                self.selection_context.selection_rect,
            )
            if (
                not force
                and self.popup.isVisible()
                and text == self._last_popup_text
                and now - self._last_popup_at < 0.7
            ):
                logger.debug("Popup duplicado ignorado")
                return
            if not force and not self.popup_state.begin(signature):
                logger.debug("Transicion duplicada de popup ignorada")
                return
            logger.info("Mostrando popup para seleccion de %d caracteres", len(text))
            hot_path_started = self.performance.start()
            context_aware = self.settings.get("context_aware", True)
            text_types = frozenset()
            if context_aware and text:
                classification_started = self.performance.start()
                text_types = self._detect_text_type(text)
                self.performance.observe(
                    "text-classification", classification_started
                )
            self._last_text_types = text_types
            snapshot = ContextSnapshot.from_selection(
                self.selection_context,
                text_types=text_types,
                clipboard_has_text=clipboard_has_text(),
            )
            profile = None
            if self.settings.get("context_profiles_enabled", False):
                profile = resolve_profile(
                    self.settings.get("context_profiles", []), snapshot
                )
            self._last_context_profile = profile.name if profile else ""
            planning_started = self.performance.start()
            visible = plan_actions(
                self.actions,
                snapshot,
                context_aware=context_aware,
                is_available=self._action_available,
                allowed_action_ids=profile.action_ids if profile else None,
            )
            self.performance.observe("action-planning", planning_started)
            if not visible:
                logger.info("Popup omitido: no hay acciones habilitadas")
                self._suppress_popup("no-actions")
                return
            if self.settings.get("local_recommendations", False):
                suggested_ids = self.ranker.suggest(
                    [action.get("id", action.get("cmd", "")) for action in visible],
                    self.selection_context.application,
                    text_types,
                )
                if suggested_ids:
                    suggested = set(suggested_ids)
                    by_id = {
                        action.get("id", action.get("cmd", "")): action
                        for action in visible
                    }
                    visible = [by_id[value] for value in suggested_ids]
                    visible.extend(
                        action
                        for action in plan_actions(
                            self.actions,
                            snapshot,
                            context_aware=context_aware,
                            is_available=self._action_available,
                            allowed_action_ids=profile.action_ids if profile else None,
                        )
                        if action.get("id", action.get("cmd", "")) not in suggested
                    )
            self.popup.set_context(self.selection_context)
            self.popup.clear_inline_result()
            self.popup.set_actions(visible, compact=compact_popup)
            pointer_anchor = self._fast_pointer_anchor()
            anchor = self.anchor_resolver.resolve(
                (
                    self.selection_context.anchor,
                    self._runtime_snapshot.get("compositor_anchor"),
                    pointer_anchor,
                )
            )
            if not self._selection_session_is_current(session_id):
                return
            self.popup.show_at_cursor(anchor, self.selection_context.selection_rect)
            self.popup_state.visible()
            self.performance.observe("popup-hot-path", hot_path_started)
            self._animate_popup_fade_in()
            self._last_popup_text = text
            self._last_popup_at = now
            self._popup_immunity_until = time.monotonic() + 0.3
            self._outside_count = 0
            self._selection_released = False
            self.hide_check_timer.start(50)
            auto_hide_ms = self.settings.get("popup_auto_hide_ms", 5000)
            if auto_hide_ms > 0 and not self.popup.is_sticky():
                self.auto_hide_timer.start(auto_hide_ms)

    def _auto_hide_popup(self):
        if not self.popup.isVisible():
            return
        if self.popup.is_interacting() or self.popup.underMouse():
            self.auto_hide_timer.start(1000)
            return
        logger.info("Popup ocultado por inactividad")
        self.hide_popup()

    def _poll_atspi_selection(self):
        """Covers Wayland desktops where PRIMARY selection is not observable."""
        if not self.monitor._active or self.popup.is_interacting():
            return
        if self.monitor._primary_button_pressed():
            return
        context = self.atspi.read_selection()
        if context is None:
            return
        if context.sensitive:
            self._begin_selection_session("atspi-sensitive")
            self.selection_context = context
            self.hide_popup()
            return
        text = context.text.strip()
        signature = (
            text,
            context.application,
            context.role,
            context.selection_rect,
        )
        if not text or signature == self._last_atspi_signature:
            return
        self._last_atspi_signature = signature
        if len(text) > self.settings.get("max_selection_length", 5000):
            return
        session_id = self._begin_selection_session("atspi-poll")
        self.selection_context = context
        self.monitor._last_text = text
        self.show_popup(context=context, session_id=session_id)

    def _action_available(self, action):
        return self.action_integration_status(action).available

    def _desktop_dbus_services(self):
        cached_at, cached_services = self._service_cache
        if time.monotonic() - cached_at < 10.0:
            return set(cached_services)
        services = set()
        if not qt_dbus_available():
            return services
        try:
            from PySide6.QtDBus import QDBusConnection

            interface = QDBusConnection.sessionBus().interface()
            for name in ("org.kde.klipper", "org.kde.kdeconnect"):
                reply = interface.isServiceRegistered(name) if interface else None
                if reply and reply.isValid() and bool(reply.value()):
                    services.add(name)
        except Exception as exc:
            logger.debug("No se pudieron consultar servicios D-Bus: %s", exc)
        self._service_cache = (time.monotonic(), set(services))
        return services

    def action_integration_status(self, action):
        return action_availability(
            action.get("cmd", ""),
            wayland=is_qt_wayland(),
            kde=is_kde(),
            dbus_services=self._desktop_dbus_services(),
        )

    def pin_action(self, action_id):
        """Moves an action to the first slot and persists the user's fixed order."""
        index = next(
            (
                index
                for index, action in enumerate(self.actions)
                if action.get("id", action.get("cmd")) == action_id
            ),
            None,
        )
        if index is None:
            return
        action = self.actions.pop(index)
        self.actions.insert(0, action)
        self.save_actions()
        self.popup._actions_key = None
        self.popup.set_actions(self.actions)
        self._show_toast(f"{action['name']} fijada en la barra")

    def block_application(self, application):
        """Persist an application-level never-show rule from the action palette."""
        name = str(application or "").strip().casefold()
        if not name:
            return
        blocked = list(self.settings.get("blocked_apps", []))
        if name not in blocked:
            blocked.append(name)
        self.settings["blocked_apps"] = blocked
        self.settings["blocked_apps_enabled"] = True
        self.save_settings()
        self.process_filter.settings = self.settings
        self.hide_popup()
        self._schedule_runtime_probe()
        self._show_toast(f"TextPik no se mostrará en {application}")

    def execute_action(self, cmd, text):
        text = text or ""
        manifest = next(
            (action for action in self.actions if action.get("cmd") == cmd), None
        )
        if manifest and not self._authorize_action(manifest):
            return
        if manifest:
            action_id = manifest.get("id", manifest.get("cmd", cmd))
            self.ranker.record(
                action_id,
                self.selection_context.application,
                self._last_text_types,
            )
            try:
                write_json_atomic(RANKING_FILE, self.ranker.serialize())
            except OSError:
                logger.debug("No se pudo guardar ranking local", exc_info=True)
        if cmd == "copy":
            self.monitor.suppress_events()
            self.copy_text_to_clipboard(text)
            self._show_toast("Texto copiado")
            return

        if cmd == "paste":
            self.paste_clipboard()
            return

        if cmd == "terminal":
            self.open_terminal_with_command(text)
            return

        if cmd == "print":
            self.print_text(text)
            return

        if cmd == "ollama":
            self.query_ollama(text)
            return

        if cmd == "open-url":
            url = normalize_url(text)
            if not url:
                QMessageBox.warning(None, "URL vacia", "No hay URL para abrir.")
                return
            try:
                if not QDesktopServices.openUrl(QUrl(url)):
                    raise RuntimeError("El escritorio rechazó la URL")
            except Exception as exc:
                QMessageBox.warning(None, "Error", f"No se pudo abrir la URL:\n{exc}")
            return

        if cmd in {"uppercase", "lowercase", "capitalize", "remove-breaks"}:
            result = transform_text(cmd, text)
            replaced = self.atspi.replace_selection(self.selection_context, result)
            if not replaced:
                QApplication.clipboard().setText(result)
                self._show_toast("Resultado copiado; la app no permite reemplazo directo")
            else:
                self.undo.remember(
                    text,
                    result,
                    self.selection_context.application,
                )
                self._show_toast("Selección reemplazada")
            return

        if cmd == "count":
            insight = text_statistics(text)
            self.popup.show_inline_result(insight.title, insight.value)
            return

        if cmd == "insight":
            insight = local_insight(text)
            if insight is None:
                self.popup.show_inline_result(
                    "Sin resultado",
                    "Usa una operación como 2 + 2 o una conversión como 10 km a mi.",
                )
            else:
                self.popup.show_inline_result(
                    insight.title, insight.value, insight.detail
                )
            return

        if cmd == "grammar":
            self._check_grammar(text)
            return

        if cmd == "undo":
            record = self.undo.pop(self.selection_context.application)
            if record is None:
                self._show_toast("No hay cambios recientes para deshacer")
                return
            if self.atspi.replace_selection(self.selection_context, record.before):
                self._show_toast("Cambio deshecho")
            else:
                QApplication.clipboard().setText(record.before)
                self._show_toast("Texto anterior copiado; la selección cambió")
            return

        if cmd == "textpik-history":
            self._show_private_history()
            return

        if cmd == "ocr-image":
            self._run_ocr_image()
            return

        if cmd == "ocr-region":
            self._run_ocr_region()
            return

        if cmd.startswith("automation:"):
            self._run_automation(cmd.split(":", 1)[1], text)
            return

        if cmd.startswith("wasi:"):
            relative = Path(cmd.split(":", 1)[1])
            module = (EXTENSIONS_DIR / relative).resolve()
            root = EXTENSIONS_DIR.resolve()
            if root not in module.parents:
                QMessageBox.warning(None, "Extensión WASI", "Ruta de módulo inválida")
                return
            timeout_ms = int((manifest or {}).get("timeout_ms", 2000))
            worker = FunctionWorker(lambda: run_wasi(module, text, timeout_ms=timeout_ms))
            worker.signals.succeeded.connect(
                lambda result: self.popup.show_inline_result(
                    manifest["name"] if manifest else "Extensión WASI",
                    result,
                )
            )
            worker.signals.failed.connect(
                lambda message: QMessageBox.warning(None, "Extensión WASI", message)
            )
            self._start_worker(worker)
            return

        if cmd == "spellcheck":
            self._check_spelling(text)
            return

        if cmd == "kdeconnect":
            self._kdeconnect_send(text)
            return

        if cmd == "klipper-save":
            self._klipper_save(text)
            return

        if cmd == "klipper-menu":
            self._klipper_show_menu()
            return

        if is_terminal_execution(cmd) and self.settings.get(
            "confirm_terminal_execution", True
        ):
            answer = QMessageBox.question(
                None,
                "Ejecutar en terminal",
                "Se ejecutara el texto seleccionado como comando. Deseas continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            argv = build_command_argv(cmd, text)
        except ValueError as exc:
            QMessageBox.warning(None, "Comando invalido", str(exc))
            return

        if argv:
            try:
                if argv[0] == "xdg-open" and len(argv) == 2:
                    if not QDesktopServices.openUrl(QUrl.fromUserInput(argv[1])):
                        raise RuntimeError("El escritorio rechazó el recurso")
                else:
                    subprocess.Popen(argv)
                self._show_toast(f"Acción iniciada: {manifest['name'] if manifest else cmd}")
            except Exception as exc:
                QMessageBox.warning(
                    None, "Error", f"No se pudo ejecutar el comando:\n{exc}"
                )

    def _check_spelling(self, text):
        """Resolve spelling only after an explicit action, outside the hot path."""
        word = self.spelling.eligible_word(text)
        if not word:
            QMessageBox.information(
                None,
                "Corrección ortográfica",
                "Selecciona una sola palabra de entre 2 y 64 caracteres.",
            )
            return
        context = self.selection_context
        session_id = self._selection_session
        languages = self.spelling.language_candidates(
            text,
            os.environ.get("LANG", "").split(".", 1)[0],
        )
        self._show_toast("Revisando ortografía…")
        worker = FunctionWorker(lambda: self.spelling.suggest(word, languages))
        worker.signals.succeeded.connect(
            lambda result: self._show_spelling_result(
                result, context, session_id
            )
        )
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(
                None, "Corrección ortográfica", message
            )
        )
        self._start_worker(worker)

    def _show_spelling_result(self, result, context, session_id):
        if result is None:
            QMessageBox.information(
                None,
                "Diccionario no disponible",
                "Instala pyenchant y un diccionario Hunspell del idioma. "
                "TextPik solo los carga al usar esta acción.",
            )
            return
        if not result.misspelled:
            self._show_toast(f"“{result.word}” está correctamente escrita")
            return
        dialog = QMessageBox(self.popup)
        dialog.setWindowTitle("Corrección ortográfica")
        dialog.setText(f"Sugerencias para “{result.word}”")
        suggestion_buttons = {
            dialog.addButton(value, QMessageBox.AcceptRole): value
            for value in result.suggestions
        }
        ignore_button = dialog.addButton("Ignorar", QMessageBox.ActionRole)
        add_button = dialog.addButton("Añadir al diccionario", QMessageBox.ActionRole)
        dialog.addButton(QMessageBox.Cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is ignore_button:
            self.spelling.ignore(result.word)
            values = list(self.settings.get("spelling_ignored_words", []))
            values.append(result.word.casefold())
            self.settings["spelling_ignored_words"] = list(dict.fromkeys(values))[-500:]
            self.save_settings()
            self._show_toast("Palabra ignorada")
            return
        if clicked is add_button:
            self.spelling.add(result.word, result.language)
            values = list(self.settings.get("spelling_personal_words", []))
            values.append(result.word.casefold())
            self.settings["spelling_personal_words"] = list(dict.fromkeys(values))[-500:]
            self.save_settings()
            self._show_toast("Palabra añadida al diccionario personal")
            return
        replacement = suggestion_buttons.get(clicked, "").strip()
        if not replacement:
            return
        if self._selection_session_is_current(session_id):
            replaced = self.atspi.replace_selection(context, replacement)
        else:
            replaced = False
        if replaced:
            self.undo.remember(
                result.word,
                replacement,
                context.application,
            )
            self._show_toast("Corrección aplicada")
        else:
            QApplication.clipboard().setText(replacement)
            self._show_toast("Corrección copiada; la selección ya no está disponible")

    def _load_automations(self):
        if not AUTOMATIONS_FILE.exists():
            return []
        try:
            payload = read_json(AUTOMATIONS_FILE)
        except (OSError, ValueError):
            logger.warning("No se pudieron cargar automatizaciones", exc_info=True)
            return []
        flows = payload.get("automations", []) if isinstance(payload, dict) else []
        accepted = []
        for flow in flows[:64] if isinstance(flows, list) else []:
            if not isinstance(flow, dict):
                continue
            identifier = str(flow.get("id", ""))[:80]
            name = str(flow.get("name", ""))[:120]
            if identifier and name and isinstance(flow.get("steps"), list):
                accepted.append(dict(flow, id=identifier, name=name))
        return accepted

    def _run_automation(self, identifier, text):
        flow = next((item for item in self.automations if item["id"] == identifier), None)
        if flow is None or not automation_matches(flow, self.selection_context, self._last_text_types):
            self._show_toast("La automatización no coincide con este contexto")
            return
        try:
            preview = preview_automation(flow, text)
        except ValueError as exc:
            QMessageBox.warning(None, "Automatización inválida", str(exc))
            return
        answer = QMessageBox.question(
            None,
            flow["name"],
            f"Vista previa:\n\n{preview.before[:500]}\n\n→\n\n{preview.after[:500]}\n\n¿Aplicar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self.atspi.replace_selection(self.selection_context, preview.after):
            self.undo.remember(
                preview.before,
                preview.after,
                self.selection_context.application,
            )
            self._show_toast("Automatización aplicada")
        else:
            QApplication.clipboard().setText(preview.after)
            self._show_toast("Resultado de automatización copiado")

    def _show_private_history(self):
        from PySide6.QtWidgets import QInputDialog

        try:
            entries = self.history.load()
        except (OSError, ValueError, ImportError):
            entries = []
        if not entries:
            self.popup.show_inline_result(
                "Historial privado",
                "Está vacío o desactivado en Configuración.",
            )
            return
        labels = [entry.text.replace("\n", " ")[:120] for entry in entries]
        selected, accepted = QInputDialog.getItem(
            None, "Historial privado", "Copiar elemento:", labels, 0, False
        )
        if accepted:
            index = labels.index(selected)
            QApplication.clipboard().setText(entries[index].text)
            self._show_toast("Elemento del historial copiado")

    def _run_ocr_image(self):
        if not shutil.which("tesseract"):
            self.popup.show_inline_result(
                "OCR no disponible",
                "Instala Tesseract; TextPik lo ejecuta únicamente bajo demanda.",
            )
            return
        filename, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "Seleccionar imagen para OCR",
            str(Path.home()),
            "Imágenes (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)",
        )
        if not filename:
            return
        self._show_toast("Reconociendo texto localmente…")
        worker = FunctionWorker(lambda: self.ocr.recognize(Path(filename)))
        worker.signals.succeeded.connect(self._show_ocr_result)
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(None, "OCR", message)
        )
        self._start_worker(worker)

    def _show_ocr_result(self, response):
        if not response.text:
            self.popup.show_inline_result("OCR", "No se detectó texto")
            return
        QApplication.clipboard().setText(response.text)
        self.popup.show_inline_result(
            "OCR local",
            response.text[:500],
            "Resultado completo copiado al portapapeles",
        )

    def _run_ocr_region(self):
        if not shutil.which("tesseract"):
            self.popup.show_inline_result("OCR", "Tesseract no está instalado")
            return

        def capture_and_recognize():
            with tempfile.TemporaryDirectory(prefix="textpik-ocr-") as temporary:
                target = Path(temporary) / "region.png"
                if shutil.which("spectacle"):
                    command = ["spectacle", "-r", "-b", "-n", "-o", str(target)]
                    subprocess.run(command, timeout=90, check=True)
                elif shutil.which("gnome-screenshot"):
                    command = ["gnome-screenshot", "-a", "-f", str(target)]
                    subprocess.run(command, timeout=90, check=True)
                elif shutil.which("slurp") and shutil.which("grim"):
                    region = subprocess.run(
                        ["slurp"], capture_output=True, text=True, timeout=90, check=True
                    ).stdout.strip()
                    if not region:
                        raise RuntimeError("Selección de región cancelada")
                    subprocess.run(
                        ["grim", "-g", region, str(target)], timeout=20, check=True
                    )
                else:
                    raise RuntimeError(
                        "No hay adaptador de captura: instala Spectacle, "
                        "gnome-screenshot o grim+slurp"
                    )
                return self.ocr.recognize(target)

        self._show_toast("Selecciona una región para OCR…")
        worker = FunctionWorker(capture_and_recognize)
        worker.signals.succeeded.connect(self._show_ocr_result)
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(None, "OCR de región", message)
        )
        self._start_worker(worker)

    def _check_grammar(self, text):
        if not text.strip():
            return
        context = self.selection_context
        session_id = self._selection_session
        self._show_toast("Revisando gramática con LanguageTool…")
        worker = FunctionWorker(lambda: self.grammar.check(text, "auto"))
        worker.signals.succeeded.connect(
            lambda suggestions: self._show_grammar_result(
                text, suggestions, context, session_id
            )
        )
        worker.signals.failed.connect(
            lambda message: self.popup.show_inline_result(
                "LanguageTool no disponible",
                "Inicia el servidor local en 127.0.0.1:8010.",
                message,
            )
        )
        self._start_worker(worker)

    def _show_grammar_result(self, text, suggestions, context, session_id):
        if not suggestions:
            self.popup.show_inline_result("Gramática", "No se encontraron problemas")
            return
        corrected = apply_suggestions(text, suggestions)
        answer = QMessageBox.question(
            None,
            "Revisión gramatical",
            f"Se encontraron {len(suggestions)} sugerencias. ¿Aplicar todas?\n\n"
            f"Antes:\n{text[:500]}\n\nDespués:\n{corrected[:500]}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.popup.show_inline_result(
                "Gramática",
                f"{len(suggestions)} sugerencias disponibles",
                suggestions[0].message,
            )
            return
        replaced = self._selection_session_is_current(session_id) and self.atspi.replace_selection(
            context, corrected
        )
        if replaced:
            self.undo.remember(text, corrected, context.application)
            self._show_toast("Correcciones aplicadas")
        else:
            QApplication.clipboard().setText(corrected)
            self._show_toast("Texto corregido copiado; la selección cambió")

    def _authorize_action(self, action):
        action_id = action.get("id", action.get("cmd", "unknown"))
        for permission in action.get("permissions", []):
            if self.permissions.allows(action_id, permission):
                continue
            answer = QMessageBox.question(
                None,
                "Permiso de acción",
                f"“{action['name']}” solicita acceso a: {permission}.\n\n"
                "El permiso se guarda solo en este equipo. ¿Permitir?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
            self.permissions.grant(action_id, permission)
        return True

    def print_text(self, text):
        def task():
            if not check_command("lp"):
                raise RuntimeError("No se encontró el comando de impresión 'lp'.")
            path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".txt",
                    prefix="textpik-print-",
                    delete=False,
                    encoding="utf-8",
                ) as file:
                    file.write(text)
                    path = file.name
                result = subprocess.run(
                    ["lp", path], capture_output=True, text=True, timeout=15
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        result.stderr.strip() or "La impresora rechazó el trabajo."
                    )
                return result.stdout.strip()
            finally:
                if path:
                    Path(path).unlink(missing_ok=True)

        worker = FunctionWorker(task)
        worker.signals.succeeded.connect(
            lambda _: self._show_toast("Texto enviado a la impresora")
        )
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(
                None, "Error de impresión", f"No se pudo imprimir:\n{message}"
            )
        )
        self._start_worker(worker)

    def query_ollama(self, text):
        if not shutil.which("ollama"):
            QMessageBox.information(
                None,
                "Ollama no instalado",
                "Ollama no está instalado en el sistema.\n\n"
                "Instalalo desde: https://ollama.com/download\n"
                "O con: curl -fsSL https://ollama.com/install.sh | sh",
            )
            return

        from PySide6.QtWidgets import QInputDialog

        labels = {
            "Reescribir": "rewrite",
            "Resumir": "summarize",
            "Simplificar": "simplify",
            "Extraer tareas": "tasks",
            "Explicar": "explain",
        }
        label, accepted = QInputDialog.getItem(
            None, "Ollama local", "Tarea:", list(labels), 0, False
        )
        if not accepted:
            return
        model = "llama3"

        self._show_toast("Consultando Ollama…")
        worker = FunctionWorker(
            lambda: self.ollama.generate(
                text,
                task=labels[label],
                model=model,
            )
        )
        worker.signals.succeeded.connect(
            lambda response: self.show_ollama_response(model, response.text)
        )
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(None, "Error de Ollama", message)
        )
        self._start_worker(worker)

    def show_ollama_response(self, model, response_text):

        dialog = QDialog(self.popup)
        dialog.setWindowTitle(f"Ollama ({model})")
        dialog.setMinimumSize(500, 350)
        dialog.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit(dialog)
        text_edit.setReadOnly(True)
        text_edit.setPlainText(response_text)
        text_edit.setWordWrapMode(True)
        layout.addWidget(text_edit)

        btn_layout = QHBoxLayout()
        copy_btn = QPushButton("Copiar respuesta", dialog)
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(response_text),
                QMessageBox.information(
                    dialog, "Copiado", "Respuesta copiada al portapapeles."
                ),
            )
        )
        btn_layout.addWidget(copy_btn)
        close_btn = QPushButton("Cerrar", dialog)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.show()

    def _show_toast(self, msg):
        if (
            hasattr(self, "tray")
            and self.tray is not None
            and QSystemTrayIcon.supportsMessages()
        ):
            try:
                self.tray.showMessage(
                    "TextPik", msg, QSystemTrayIcon.MessageIcon.Information, 2000
                )
                return
            except Exception as exc:
                logger.debug("Toast fallo: %s", exc)
        if check_command("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "--app-name=TextPik", "--icon=textpik", "TextPik", msg]
                )
            except Exception as exc:
                logger.debug("Notificación del sistema falló: %s", exc)

    def _kdeconnect_send(self, text):
        if check_command("kdeconnect-cli"):
            def task():
                devices = subprocess.run(
                    ["kdeconnect-cli", "--list-available", "--id-only"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                ).stdout.split()
                if not devices:
                    raise RuntimeError("No hay dispositivos disponibles")
                result = subprocess.run(
                    [
                        "kdeconnect-cli",
                        "--device",
                        devices[0],
                        "--share-text",
                        text,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        result.stderr.strip() or "KDE Connect rechazó el texto"
                    )
                return devices[0]

            worker = FunctionWorker(task)
            worker.signals.succeeded.connect(
                lambda _: self._show_toast("Texto enviado al móvil")
            )
            worker.signals.failed.connect(
                lambda message: QMessageBox.warning(None, "KDE Connect", message)
            )
            self._start_worker(worker)
            return
        clipboard = QApplication.clipboard()
        previous_clipboard = clipboard.text(QClipboard.Mode.Clipboard)
        clipboard.setText(text, QClipboard.Mode.Clipboard)
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

            bus = QDBusConnection.sessionBus()
            iface = QDBusInterface(
                "org.kde.kdeconnect",
                "/modules/kdeconnect/devices",
                "org.freedesktop.DBus.Introspectable",
                bus,
            )
            reply = iface.call("Introspect")
            if not reply.arguments():
                raise Exception("No se pudo introspectar KDE Connect")
            xml = reply.arguments()[0]
            import re as _re

            devices = _re.findall(r'<node name="([^"]+)"/>', xml)
            if not devices:
                raise Exception("No hay dispositivos emparejados")
            sent = False
            for dev_id in devices:
                cli_iface = QDBusInterface(
                    "org.kde.kdeconnect",
                    f"/modules/kdeconnect/devices/{dev_id}/clipboard",
                    "org.kde.kdeconnect.device.clipboard",
                    bus,
                )
                cli_reply = cli_iface.call("sendClipboard")
                if cli_reply.type() != QDBusMessage.MessageType.ErrorMessage:
                    sent = True
            if sent:
                self._show_toast("Texto enviado al movil")
            else:
                raise Exception("No se pudo enviar a ningun dispositivo")
        except Exception as exc:
            QMessageBox.warning(
                None,
                "KDE Connect",
                f"No se pudo enviar al movil:\n{exc}",
            )
        finally:
            clipboard.setText(previous_clipboard, QClipboard.Mode.Clipboard)

    def _klipper_save(self, text):
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface

            bus = QDBusConnection.sessionBus()
            iface = QDBusInterface(
                "org.kde.klipper",
                "/klipper",
                "org.kde.klipper.klipper",
                bus,
            )
            iface.call("setClipboardContents", text)
            self._show_toast("Guardado en Klipper")
        except Exception as exc:
            QMessageBox.warning(
                None,
                "Klipper",
                f"No se pudo guardar en Klipper:\n{exc}",
            )

    def _klipper_show_menu(self):
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface

            bus = QDBusConnection.sessionBus()
            iface = QDBusInterface(
                "org.kde.klipper",
                "/klipper",
                "org.kde.klipper.klipper",
                bus,
            )
            iface.call("showKlipperManuallyInvokeActionMenu")
        except Exception as exc:
            QMessageBox.warning(
                None,
                "Klipper",
                f"No se pudo mostrar el menu de Klipper:\n{exc}",
            )

    def _detect_text_type(self, text):
        return classify_text(text)

    def open_config_folder(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    def edit_actions_file(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not ACTIONS_FILE.exists():
            self.save_actions()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ACTIONS_FILE)))

    def edit_settings_file(self):
        load_settings()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SETTINGS_FILE)))

    def open_log_file(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.write_text("", encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))

    def open_log_viewer(self):
        dialog = QDialog(self.popup)
        dialog.setWindowTitle("Log de textpik")
        dialog.setMinimumSize(600, 400)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit(dialog)
        text_edit.setReadOnly(True)

        log_path = LOG_FILE
        if log_path.exists():
            try:
                lines = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                text_edit.setPlainText("\n".join(lines[-1000:]))
            except Exception as exc:
                text_edit.setPlainText(f"Error leyendo log: {exc}")
        else:
            text_edit.setPlainText("No hay archivo de log.")

        layout.addWidget(text_edit)
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refrescar", dialog)
        refresh_btn.clicked.connect(lambda: self._refresh_log_view(text_edit))
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        close_btn = QPushButton("Cerrar", dialog)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dialog.show()

    def _refresh_log_view(self, text_edit):
        log_path = LOG_FILE
        if log_path.exists():
            try:
                lines = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                text_edit.setPlainText("\n".join(lines[-1000:]))
            except Exception as exc:
                text_edit.setPlainText(f"Error: {exc}")
        else:
            text_edit.setPlainText("No hay archivo de log.")

    def copy_text_to_clipboard(self, text):
        clipboard = QApplication.clipboard()
        clipboard.setText(text, QClipboard.Mode.Clipboard)
        if clipboard.supportsSelection():
            clipboard.setText(text, QClipboard.Mode.Selection)
        return clipboard.text(QClipboard.Mode.Clipboard) == text

    def open_terminal_with_command(self, text):
        self.copy_text_to_clipboard(text)
        command_line = " ".join(text.splitlines()).strip()

        script = r"""
cmd=${TEXTPIK_TEXT:-}
if [ -n "$cmd" ]; then
    history -s "$cmd" 2>/dev/null || true
    read -e -i "$cmd" -p "$ " textpik_cmd
else
    read -e -p "$ " textpik_cmd
fi
if [ -n "$textpik_cmd" ]; then
    history -s "$textpik_cmd" 2>/dev/null || true
    eval "$textpik_cmd"
fi
exec bash -i
""".strip()

        terminal_argv = None
        for name, argv in (
            ("konsole", ["konsole", "-e", "bash", "-lc", script]),
            ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", script]),
            ("kgx", ["kgx", "--", "bash", "-lc", script]),
            ("mate-terminal", ["mate-terminal", "--", "bash", "-lc", script]),
            (
                "xfce4-terminal",
                ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(script)}"],
            ),
            ("kitty", ["kitty", "bash", "-lc", script]),
            ("alacritty", ["alacritty", "-e", "bash", "-lc", script]),
            ("xterm", ["xterm", "-e", "bash", "-lc", script]),
            (
                "x-terminal-emulator",
                ["x-terminal-emulator", "-e", "bash", "-lc", script],
            ),
        ):
            if check_command(name):
                terminal_argv = argv
                break

        if terminal_argv is None:
            QMessageBox.warning(
                None, "Terminal no disponible", "No se encontro una terminal instalada."
            )
            return

        env = os.environ.copy()
        env["TEXTPIK_TEXT"] = command_line
        try:
            subprocess.Popen(terminal_argv, env=env)
            logger.info(
                "Terminal abierta con comando precargado de %d caracteres",
                len(command_line),
            )
        except Exception as exc:
            QMessageBox.warning(None, "Error", f"No se pudo abrir la terminal:\n{exc}")

    def paste_clipboard(self):
        clipboard = QApplication.clipboard()
        if not clipboard_has_text(clipboard):
            self._show_toast("El portapapeles no contiene texto")
            return

        def run_paste():
            try:
                if is_qt_wayland() and check_command("wtype"):
                    subprocess.Popen(["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
                elif is_qt_wayland() and check_command("ydotool"):
                    # KEY_LEFTCTRL=29, KEY_V=47. Pegar evita problemas de
                    # Unicode y distribución de teclado de `ydotool type`.
                    subprocess.Popen(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
                elif check_command("xdotool"):
                    subprocess.Popen(["xdotool", "key", "ctrl+v"])
                else:
                    self._show_toast(
                        "Texto copiado; no hay herramienta de pegado automático"
                    )
            except Exception as exc:
                QMessageBox.warning(
                    None,
                    "Pegado automatico no disponible",
                    "El texto fue copiado, pero no se pudo pegar automaticamente:\n"
                    f"{exc}",
                )

        QTimer.singleShot(180 if is_qt_wayland() else 100, run_paste)

    def diagnostic_report(self):
        """Return a privacy-safe capability snapshot for support requests."""
        services = self._desktop_dbus_services()
        monitor_name = type(self.monitor).__name__
        payload = {
            "application": APP_NAME,
            "application_version": APP_VERSION,
            "qt_platform": self.app.platformName(),
            "desktop": desktop_environment() or "unknown",
            "selection_backend": monitor_name,
            "atspi": self.atspi.available,
            "atspi_events": bool(self.atspi_events_active),
            "wl_clipboard": check_command("wl-paste"),
            "paste_backend": next(
                (
                    name
                    for name in ("wtype", "ydotool", "xdotool")
                    if check_command(name)
                ),
                "clipboard-only",
            ),
            "klipper": "org.kde.klipper" in services,
            "kdeconnect": (
                check_command("kdeconnect-cli")
                or "org.kde.kdeconnect" in services
            ),
            "selection_session": self._selection_session,
            "popup_phase": self.popup_state.phase.value,
            "popup_suppression_reason": self.popup_state.reason,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def copy_diagnostic_report(self):
        QApplication.clipboard().setText(self.diagnostic_report())
        self._show_toast("Diagnóstico copiado sin contenido seleccionado")

    def create_tray_icon(self):
        self.tray = QSystemTrayIcon(self)
        icon = load_icon(TRAY_ICON_FILE, "edit-select-all")
        if icon.isNull():
            icon = self.app.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self.tray.setIcon(icon)
        self.tray.setToolTip("TextPik — activo\nSelecciona texto para ver acciones")

        menu = QMenu()
        available_count = sum(
            1
            for action in self.actions
            if action.get("enabled", True) and self._action_available(action)
        )
        status_action = QAction(
            f"TextPik · Activo · {available_count} acciones", self
        )
        status_action.setEnabled(False)
        menu.addAction(status_action)
        menu.addSeparator()
        self.tray_status_action = status_action
        self.toggle_action = QAction("Pausar", self)
        self.toggle_action.setIcon(QIcon.fromTheme("media-playback-pause"))
        self.toggle_action.triggered.connect(self.toggle_monitor)
        menu.addAction(self.toggle_action)

        show_now_action = QAction("Mostrar menu ahora", self)
        show_now_action.setIcon(QIcon.fromTheme("view-more-symbolic"))
        show_now_action.triggered.connect(lambda: self.show_popup(force=True))
        menu.addAction(show_now_action)

        menu.addSeparator()

        settings_action = QAction("Configuracion...", self)
        settings_action.setIcon(QIcon.fromTheme("settings-configure"))
        settings_action.triggered.connect(self.open_settings_dialog)
        menu.addAction(settings_action)

        config_menu = QMenu("Archivos y diagnostico", menu)

        reload_actions_action = QAction("Recargar acciones", self)
        reload_actions_action.triggered.connect(self.reload_actions)
        config_menu.addAction(reload_actions_action)

        edit_actions_action = QAction("Editar actions.json", self)
        edit_actions_action.triggered.connect(self.edit_actions_file)
        config_menu.addAction(edit_actions_action)

        edit_settings_action = QAction("Editar settings.json", self)
        edit_settings_action.triggered.connect(self.edit_settings_file)
        config_menu.addAction(edit_settings_action)

        reload_settings_action = QAction("Recargar ajustes", self)
        reload_settings_action.triggered.connect(self.reload_settings)
        config_menu.addAction(reload_settings_action)

        open_config_action = QAction("Abrir carpeta de configuracion", self)
        open_config_action.triggered.connect(self.open_config_folder)
        config_menu.addAction(open_config_action)

        view_log_action = QAction("Ver log...", self)
        view_log_action.triggered.connect(self.open_log_viewer)
        config_menu.addAction(view_log_action)

        copy_diagnostics_action = QAction("Copiar diagnóstico", self)
        copy_diagnostics_action.triggered.connect(self.copy_diagnostic_report)
        config_menu.addAction(copy_diagnostics_action)

        open_log_action = QAction("Abrir archivo de log", self)
        open_log_action.triggered.connect(self.open_log_file)
        config_menu.addAction(open_log_action)

        menu.addMenu(config_menu)
        menu.addSeparator()

        quit_action = QAction("Salir", self)
        quit_action.setIcon(QIcon.fromTheme("application-exit"))
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning(
                "El escritorio no expone bandeja; TextPik seguirá activo en segundo plano"
            )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings_dialog()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_monitor()

    def toggle_monitor(self):
        if self.monitor._active:
            self.monitor.pause()
            self.toggle_action.setText("Reanudar")
            self.toggle_action.setIcon(QIcon.fromTheme("media-playback-start"))
            self.tray_status_action.setText("TextPik · En pausa")
            self.tray.setToolTip("TextPik — en pausa")
            self.hide_popup()
        else:
            self.monitor.resume()
            self.toggle_action.setText("Pausar")
            self.toggle_action.setIcon(QIcon.fromTheme("media-playback-pause"))
            available_count = sum(
                1
                for action in self.actions
                if action.get("enabled", True) and self._action_available(action)
            )
            self.tray_status_action.setText(
                f"TextPik · Activo · {available_count} acciones"
            )
            self.tray.setToolTip("TextPik — activo\nSelecciona texto para ver acciones")

    def quit(self):
        self.app.quit()

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        for timer_name in (
            "atspi_timer",
            "atspi_event_timer",
            "runtime_probe_timer",
            "activity_probe_timer",
            "service_probe_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        if hasattr(self, "atspi"):
            self.atspi.close()
        if hasattr(self, "monitor"):
            self.monitor.pause()
        if hasattr(self, "thread_pool"):
            self.thread_pool.clear()
            workers_done = self.thread_pool.waitForDone(3000)
            if workers_done:
                self._active_workers.clear()
            else:
                # Keep the controller and signal objects alive until process
                # teardown; deleting them under a running PySide worker can
                # crash Shiboken. All tasks have their own finite timeouts.
                _SHUTDOWN_GUARDS.append(self)
                logger.warning(
                    "Hay %d trabajo(s) en segundo plano al cerrar",
                    len(self._active_workers),
                )
        if getattr(self, "cursor_bridge_bus", None) is not None:
            try:
                self.cursor_bridge_bus.unregisterObject(CURSOR_BRIDGE_PATH)
                self.cursor_bridge_bus.unregisterService(CURSOR_BRIDGE_SERVICE)
            except Exception as exc:
                logger.debug("Error al desregistrar D-Bus: %s", exc)
        self.teardown_hotkey()

    def run(self):
        sys.exit(self.app.exec())


def main(argv):
    if len(argv) >= 2 and argv[1] == "run":
        settings = load_settings()
        setup_logging(settings)
        logger.info("Ejecutando modo CLI run")
        return run_cli_action(argv[2:])

    TextPikApp().run()
    return 0


def cli_entry():
    """Entry point used by wheel, DEB/RPM and development installs."""
    return main(sys.argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
