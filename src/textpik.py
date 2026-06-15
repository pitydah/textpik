#!/usr/bin/env python3
"""
textpik - Barra emergente de acciones al seleccionar texto.

Soporta X11 mediante QClipboard.Selection y KDE Plasma Wayland mediante
Klipper por D-Bus. Evita shell=True para acciones configurables.
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import ctypes
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote_plus


def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def is_qt_wayland():
    app = QApplication.instance() if "QApplication" in globals() else None
    if app is None:
        return is_wayland() and os.environ.get("QT_QPA_PLATFORM", "") != "xcb"
    return app.platformName().lower().startswith("wayland")


def check_command(cmd):
    return shutil.which(cmd) is not None


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
        return False

    answer = input(f"Deseas instalar {pacman_package} ahora? [s/N]: ").strip().lower()
    if answer not in ("s", "si", "y", "yes"):
        return False

    # Detectar gestor de paquetes
    if check_command("pacman"):
        cmd = ["sudo", "pacman", "-S", "--needed", pacman_package]
    elif check_command("apt"):
        cmd = ["sudo", "apt", "install", "-y", f"python3-{pip_package.lower()}"]
    elif check_command("dnf"):
        cmd = ["sudo", "dnf", "install", "-y", f"python3-{pip_package.lower()}"]
    elif check_command("zypper"):
        cmd = ["sudo", "zypper", "install", "-y", f"python3-{pip_package.lower()}"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--user", pip_package]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        return False

    return check_python_module(python_module)


if not install_python_or_system_package("PySide6", "pyside6", "PySide6"):
    sys.exit(1)


from PySide6.QtCore import ClassInfo, QLockFile, QObject, QPoint, QProcess, QRectF, QSize, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QClipboard, QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "textpik"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
LOG_FILE = CACHE_DIR / "textpik.log"

DEFAULT_SETTINGS = {
    "show_on_selection": True,
    "popup_delay_ms": 0,
    "max_selection_length": 5000,
    "confirm_terminal_execution": True,
    "enable_wayland_polling": True,
    "log_enabled": True,
    "popup_background_color": "#f7f7f7",
    "popup_button_color": "#ffffff",
    "popup_hover_color": "#eeeeee",
    "popup_border_color": "#d0d0d0",
    "popup_button_border_color": "#c8c8c8",
    "popup_icon_size": 24,
    "popup_border_radius": 16,
    "popup_opacity": 0.96,
    "popup_wayland_fallback_top": 96,
    "popup_wayland_fallback_horizontal": "center",
    "disable_in_games": False,
    "game_filter_keywords": [
        "steam",
        "lutris",
        "wine",
        "proton",
        "heroic",
        "csgo",
        "dota",
        "minecraft",
        "retroarch",
            "factorio",
    ],
    "blocked_apps_enabled": False,
    "blocked_apps": [],
    "theme_preset": "custom",
}

DEFAULT_ACTIONS = [
    {"name": "Copiar", "icon": "copy.svg", "cmd": "copy", "enabled": True},
    {"name": "Pegar", "icon": "paste.svg", "cmd": "paste", "enabled": True},
    {
        "name": "Abrir link en una pestaña nueva",
        "icon": "open-link.svg",
        "cmd": "open-url",
        "enabled": True,
    },
    {
        "name": "Buscar en Google",
        "icon": "search-google.svg",
        "cmd": "xdg-open 'https://www.google.com/search?q={url}'",
        "enabled": True,
    },
    {
        "name": "Buscar en YouTube",
        "icon": "search-youtube.svg",
        "cmd": "xdg-open 'https://www.youtube.com/results?search_query={url}'",
        "enabled": True,
    },
    {
        "name": "Buscar en Google Maps",
        "icon": "search-maps.svg",
        "cmd": "xdg-open 'https://www.google.com/maps?q={url}'",
        "enabled": True,
    },
    {
        "name": "Preguntar a ChatGPT",
        "icon": "chatgpt.svg",
        "cmd": "xdg-open 'https://chatgpt.com/?q={url}'",
        "enabled": True,
    },
    {
        "name": "Preguntar a DeepSeek",
        "icon": "deepseek.svg",
        "cmd": "xdg-open 'https://chat.deepseek.com/?q={url}'",
        "enabled": True,
    },
    {
        "name": "Buscar en DuckDuckGo",
        "icon": "duckduckgo.svg",
        "cmd": "xdg-open 'https://duckduckgo.com/?q={url}'",
        "enabled": True,
    },
    {
        "name": "Ejecutar en terminal",
        "icon": "terminal.svg",
        "cmd": "terminal",
        "enabled": True,
    },
    {
        "name": "Imprimir",
        "icon": "print.svg",
        "cmd": "print",
        "enabled": True,
    },
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


def normalize_color(value, fallback):
    color = QColor(str(value))
    return color.name() if color.isValid() else fallback


def normalize_settings(settings):
    if not isinstance(settings, dict):
        settings = {}
    normalized = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in settings:
            normalized[key] = settings[key]

    try:
        normalized["popup_delay_ms"] = max(0, int(normalized["popup_delay_ms"]))
    except (TypeError, ValueError):
        normalized["popup_delay_ms"] = DEFAULT_SETTINGS["popup_delay_ms"]

    try:
        normalized["max_selection_length"] = max(
            1, int(normalized["max_selection_length"])
        )
    except (TypeError, ValueError):
        normalized["max_selection_length"] = DEFAULT_SETTINGS["max_selection_length"]

    try:
        normalized["popup_icon_size"] = min(
            64, max(12, int(normalized["popup_icon_size"]))
        )
    except (TypeError, ValueError):
        normalized["popup_icon_size"] = DEFAULT_SETTINGS["popup_icon_size"]

    try:
        normalized["popup_border_radius"] = min(
            64, max(0, int(normalized["popup_border_radius"]))
        )
    except (TypeError, ValueError):
        normalized["popup_border_radius"] = DEFAULT_SETTINGS["popup_border_radius"]

    try:
        normalized["popup_opacity"] = min(
            1.0, max(0.25, float(normalized["popup_opacity"]))
        )
    except (TypeError, ValueError):
        normalized["popup_opacity"] = DEFAULT_SETTINGS["popup_opacity"]

    try:
        normalized["popup_wayland_fallback_top"] = max(
            0, int(normalized["popup_wayland_fallback_top"])
        )
    except (TypeError, ValueError):
        normalized["popup_wayland_fallback_top"] = DEFAULT_SETTINGS[
            "popup_wayland_fallback_top"
        ]

    if normalized.get("popup_wayland_fallback_horizontal") not in ("center", "cursor"):
        normalized["popup_wayland_fallback_horizontal"] = DEFAULT_SETTINGS[
            "popup_wayland_fallback_horizontal"
        ]

    for key in (
        "show_on_selection",
        "confirm_terminal_execution",
        "enable_wayland_polling",
        "log_enabled",
        "disable_in_games",
        "blocked_apps_enabled",
    ):
        normalized[key] = bool(normalized[key])

    keywords = normalized.get("game_filter_keywords")
    if not isinstance(keywords, list):
        keywords = DEFAULT_SETTINGS["game_filter_keywords"]
    normalized["game_filter_keywords"] = [
        str(keyword).strip().lower()
        for keyword in keywords
        if str(keyword).strip()
    ]

    blocked = normalized.get("blocked_apps", [])
    normalized["blocked_apps"] = (
        [str(x).strip().lower() for x in blocked if str(x).strip()]
        if isinstance(blocked, list) else []
    )

    if normalized.get("theme_preset") not in ("custom", "dark", "light", "oled"):
        normalized["theme_preset"] = "custom"
    theme_presets = {
        "light": {
            "popup_background_color": "#f7f7f7",
            "popup_border_color": "#d0d0d0",
        },
        "dark": {
            "popup_background_color": "#2d2d2d",
            "popup_border_color": "#555555",
        },
        "oled": {
            "popup_background_color": "#000000",
            "popup_border_color": "#333333",
        },
    }
    preset = normalized.get("theme_preset")
    if preset in theme_presets:
        for key, value in theme_presets[preset].items():
            normalized[key] = value

    for key in (
        "popup_background_color",
        "popup_button_color",
        "popup_hover_color",
        "popup_border_color",
        "popup_button_border_color",
    ):
        normalized[key] = normalize_color(normalized[key], DEFAULT_SETTINGS[key])

    return normalized


def load_settings():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as file:
                settings = normalize_settings(json.load(file))
        except Exception:
            settings = dict(DEFAULT_SETTINGS)
    else:
        settings = dict(DEFAULT_SETTINGS)

    with SETTINGS_FILE.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, ensure_ascii=False)
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
            content = Path(f"/proc/{pid}/cmdline").read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            return False
        return any(keyword in content for keyword in keywords)

    def _maps_look_like_game(self, pid):
        try:
            lines = Path(f"/proc/{pid}/maps").read_text(
                encoding="utf-8", errors="ignore"
            ).lower().splitlines()
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
                capture_output=True, text=True, timeout=0.4,
            )
            return result.stdout.strip().lower() if result.returncode == 0 else ""
        except Exception:
            return ""

    def is_foreground_process_blocked(self):
        if not self.settings.get("blocked_apps_enabled", False):
            return False
        blocked = self.settings.get("blocked_apps", [])
        if not blocked:
            return False
        wm_class = self._active_window_class()
        return bool(wm_class and any(b in wm_class for b in blocked))


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
    if variant and base_path.suffix.lower() == ".svg":
        variant_path = base_path.with_stem(f"{base_path.stem}-{variant}")
        icon = load_icon(variant_path, base_path.stem)
        if not icon.isNull():
            return icon, False

    icon = load_icon(base_path, icon_name)
    return icon, True


def color_luminance(color_name):
    color = QColor(color_name)
    if not color.isValid():
        color = QColor("#f7f7f7")
    return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255


def icon_color_for_background(color_name):
    return QColor("#000000") if color_luminance(color_name) >= 0.5 else QColor("#ffffff")


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

    if not qt_dbus_available():
        logger.info("Diagnostico cursor: QtDBus no disponible; se usara fallback Wayland")
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
                logger.info("Diagnostico cursor: cursorPos fallo en %s %s", service, path)
            else:
                logger.info("Diagnostico cursor: cursorPos disponible en %s %s", service, path)
                return

        if not any_valid:
            logger.info("Diagnostico cursor: KWin no expone rutas D-Bus de cursor conocidas")
        else:
            logger.info("Diagnostico cursor: rutas D-Bus existen pero cursorPos no respondio")
    except Exception as exc:
        logger.warning("Diagnostico cursor: error consultando KWin D-Bus: %s", exc)


def offer_install_system_packages(packages, parent=None):
    packages = sorted(set(packages))
    if not packages:
        return True

    package_list = "\n".join(f" - {package}" for package in packages)
    message = (
        "Faltan herramientas opcionales:\n\n"
        f"{package_list}\n\n"
        "Sin ellas, algunas funciones como pegar automaticamente pueden no funcionar."
    )

    if check_command("pkexec"):
        # Detectar gestor de paquetes para instalar
        if check_command("pacman"):
            cmd = ["pkexec", "pacman", "-S", "--noconfirm", "--needed", *packages]
        elif check_command("apt"):
            cmd = ["pkexec", "apt", "install", "-y", *packages]
        elif check_command("dnf"):
            cmd = ["pkexec", "dnf", "install", "-y", *packages]
        elif check_command("zypper"):
            cmd = ["pkexec", "zypper", "install", "-y", *packages]
        else:
            cmd = None

        if cmd:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
            except Exception as exc:
                QMessageBox.warning(parent, "Aviso", f"No se pudo ejecutar pkexec: {exc}")
                return False
            if result.returncode == 0:
                return True

    message += "\n\nInstalacion manual sugerida:\n"
    if check_command("pacman"):
        message += "sudo pacman -S --needed " + " ".join(packages)
    elif check_command("apt"):
        message += "sudo apt install " + " ".join(packages)
    elif check_command("dnf"):
        message += "sudo dnf install " + " ".join(packages)
    elif check_command("zypper"):
        message += "sudo zypper install " + " ".join(packages)
    else:
        message += "Instala los paquetes: " + " ".join(packages)
    QMessageBox.warning(parent, "Dependencias opcionales", message)
    return False


def check_runtime_dependencies(parent=None):
    optional_packages = []

    if is_wayland():
        if not qt_dbus_available():
            QMessageBox.critical(
                parent,
                "D-Bus no disponible",
                "PySide6.QtDBus no esta disponible. En KDE Wayland no se podra "
                "leer la seleccion desde Klipper.",
            )
        if not check_command("ydotool"):
            optional_packages.append("ydotool")
        if not check_command("wl-paste"):
            optional_packages.append("wl-clipboard")
    elif not check_command("xdotool"):
        optional_packages.append("xdotool")

    if not check_command("konsole"):
        optional_packages.append("konsole")

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
        self.timer_debounce = QTimer(self)
        self.timer_debounce.setSingleShot(True)
        self.timer_debounce.timeout.connect(self._debounce_expired)

    def _schedule_read(self, force_emit=True):
        if self._active:
            self._force_emit = self._force_emit or force_emit
            delay = max(60, int(self.settings.get("popup_delay_ms", 0)))
            self.timer_debounce.start(delay)

    def _selection_event(self, *args):
        self._schedule_read(force_emit=True)

    def _read_selection_text(self):
        return ""

    def _debounce_expired(self):
        text = self._read_selection_text().strip()
        now = time.monotonic()
        should_emit = self._force_emit or text != self._last_text
        self._force_emit = False
        if not text:
            if self._last_text:
                logger.info("Seleccion primaria vacia; ocultando popup")
            self._last_text = ""
            self.selection_cleared.emit()
            return

        max_length = self.settings.get("max_selection_length", 5000)
        if len(text) > max_length:
            logger.info(
                "Seleccion ignorada por tamano: %d caracteres (max %d)",
                len(text),
                max_length,
            )
            return

        if text and should_emit:
            if text == self._last_emit_text and now - self._last_emit_at < 0.45:
                logger.debug("Seleccion duplicada ignorada")
                return
            logger.info("Seleccion detectada: %d caracteres", len(text))
            self._last_text = text
            self._last_emit_text = text
            self._last_emit_at = now
            self.selection_changed.emit()

    def get_last_text(self):
        return self._last_text

    def pause(self):
        self._active = False
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
        self._ignore_next_wl_paste_event = True
        self._last_wl_paste_event_at = 0.0
        self.clipboard = QApplication.clipboard()
        self._use_wl_paste = check_command("wl-paste")
        if not self._use_wl_paste and self.clipboard.supportsSelection():
            self.clipboard.selectionChanged.connect(self._selection_event)

        self._start_wl_paste_primary_monitor()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(lambda: self._schedule_read(force_emit=False))
        if (
            self.settings.get("enable_wayland_polling", True)
            and not self._use_wl_paste
        ):
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
        self._wl_paste_monitor.start(
            "wl-paste",
            [
                "--primary",
                "--watch",
                "/usr/bin/printf",
                "textpik-selection-changed\n",
            ],
        )
        logger.info("Monitor wl-paste PRIMARY iniciado")

    def _stop_process(self, process):
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        process.terminate()
        if not process.waitForFinished(500):
            process.kill()
            process.waitForFinished(500)

    def pause(self):
        super().pause()
        self._poll_timer.stop()
        self._stop_process(self._wl_paste_monitor)
        self._stop_process(self._dbus_monitor)

    def resume(self):
        super().resume()
        self._ignore_next_wl_paste_event = True
        if self._use_wl_paste:
            self._start_wl_paste_primary_monitor()
        elif self.settings.get("enable_wayland_polling", True):
            self._poll_timer.start(500)

    def _on_wl_paste_monitor_output(self):
        if self._wl_paste_monitor is None:
            return
        output = bytes(self._wl_paste_monitor.readAllStandardOutput())
        if output:
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
        self._dbus_monitor.readyReadStandardOutput.connect(
            self._on_dbus_monitor_output
        )
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

    def _call_klipper(self, method, *args):
        if self.iface is None or not self.iface.isValid():
            return ""
        try:
            from PySide6.QtDBus import QDBusMessage

            reply = self.iface.call(method, *args)
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                return ""
            values = reply.arguments()
        except Exception:
            return ""
        if not values:
            return ""
        if values[0] is None:
            return ""
        return str(values[0])

    def _read_selection_text(self):
        if self._use_wl_paste:
            try:
                result = subprocess.run(
                    ["wl-paste", "--primary", "--no-newline"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
                return ""
            except Exception as exc:
                logger.warning("No se pudo leer PRIMARY con wl-paste: %s", exc)
                return ""

        if self.clipboard.supportsSelection():
            text = self.clipboard.text(QClipboard.Mode.Selection).strip()
            if text:
                return text

        return ""


def get_cursor_pos_wayland():
    global kwin_bridge_cursor

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
                logger.debug("cursorPos D-Bus interfaz invalida en %s %s", service, path)
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
                logger.debug("cursorPos D-Bus obtenido via %s %s: %s,%s", service, path, x, y)
                return x, y
    except Exception as exc:
        logger.warning("cursorPos D-Bus error: %s", exc)
        return None

    if not getattr(get_cursor_pos_wayland, "_fallback_logged", False):
        logger.info("No se pudo obtener la posicion del cursor via KWin D-Bus; usando fallback")
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
    except Exception:
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
    if is_wayland():
        pos = get_cursor_pos_wayland()
        if pos is not None:
            return pos[0], pos[1], True

    pos = get_cursor_pos_xdotool()
    if pos is not None:
        return pos[0], pos[1], True

    pointer_state = X11Pointer().state()
    if pointer_state is not None:
        return pointer_state[0], pointer_state[1], not is_wayland()

    pos = QCursor.pos()
    return pos.x(), pos.y(), not is_wayland()


class PopupWindow(QWidget):
    action_triggered = Signal(str, str)

    def __init__(self, actions, monitor, settings=None):
        super().__init__()
        self.actions = actions
        self.monitor = monitor
        self.settings = settings or dict(DEFAULT_SETTINGS)
        self.setWindowTitle(APP_NAME)
        if is_qt_wayland():
            # Qt.Popup/Qt.ToolTip pueden ser rechazados por Wayland si no hay
            # un parent con input reciente. Una ventana top-level frameless se
            # mapea de forma mas fiable en KWin Wayland.
            self.setWindowFlags(
                Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            )
        else:
            self.setWindowFlags(
                Qt.Popup | Qt.FramelessWindowHint
            )
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self._actions_key = None

        self.buttons_layout = QHBoxLayout(self)
        self.apply_settings(self.settings)
        self.set_actions(self.actions)

    def apply_settings(self, settings):
        self.settings = normalize_settings(settings)
        icon_size = self.settings["popup_icon_size"]
        button_size = icon_size + 10
        radius = self.settings["popup_border_radius"]
        button_radius = max(4, min(radius // 2, 10))
        self.icon_color = icon_color_for_background(self.settings["popup_background_color"])
        self.icon_variant = icon_variant_for_background(self.settings["popup_background_color"])

        margin = max(6, icon_size // 3)
        spacing = max(3, icon_size // 6)
        self.buttons_layout.setContentsMargins(margin, margin, margin, margin)
        self.buttons_layout.setSpacing(spacing)

        self.setWindowOpacity(self.settings["popup_opacity"])
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {button_radius}px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 28);
                border: none;
                border-radius: {button_radius}px;
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 0, 0, 45);
                border: none;
            }}
            """
        )
        self.update()

        variant = getattr(self, "icon_variant", None)
        for button in self.findChildren(QPushButton):
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
        self.adjustSize()

    def set_actions(self, actions):
        actions_key = tuple((action["name"], action["icon"], action["cmd"]) for action in actions)
        if actions_key == self._actions_key:
            return

        self._actions_key = actions_key
        self.actions = actions
        while self.buttons_layout.count():
            item = self.buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        variant = getattr(self, "icon_variant", None)
        for i, action in enumerate(self.actions):
            button = QPushButton()
            icon, needs_recolor = resolve_action_icon(action["icon"], variant)
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
                needs_recolor = False
            button.source_icon = icon
            button.source_icon_name = action["icon"]
            if needs_recolor:
                button.setIcon(recolor_icon(icon, self.icon_color, self.settings["popup_icon_size"]))
            else:
                button.setIcon(icon)
            button.setToolTip(f"{i+1}: {action['name']}")
            icon_size = self.settings["popup_icon_size"]
            button_size = icon_size + 10
            button.setFixedSize(button_size, button_size)
            button.setIconSize(QSize(icon_size, icon_size))
            button.setFlat(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            command = action["cmd"]
            button.clicked.connect(lambda checked=False, cmd=command: self._on_click(cmd))
            self.buttons_layout.addWidget(button)

        self.buttons_layout.activate()
        self.adjustSize()

    def paintEvent(self, event):
        radius = self.settings.get("popup_border_radius", 16)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(path, QColor(self.settings["popup_background_color"]))
        painter.setPen(QPen(QColor(self.settings["popup_border_color"]), 1))
        painter.drawPath(path)
        super().paintEvent(event)

    def _on_click(self, cmd):
        text = self.monitor.get_last_text() if self.monitor else ""
        self.hide()
        self.action_triggered.emit(cmd, text)

    def focusOutEvent(self, event):
        QTimer.singleShot(0, self.hide_if_focus_outside)
        super().focusOutEvent(event)

    def hide_if_focus_outside(self):
        focus_widget = QApplication.focusWidget()
        if focus_widget is self or (focus_widget is not None and self.isAncestorOf(focus_widget)):
            return
        logger.info("Popup perdio foco hacia fuera; ocultando")
        self.hide()

    def keyPressEvent(self, event):
        key = event.key()
        if Qt.Key_1 <= key <= Qt.Key_9:
            idx = key - Qt.Key_1
            if idx < len(self.actions):
                self._on_click(self.actions[idx]["cmd"])
                return
        super().keyPressEvent(event)

    def show_at_cursor(self):
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
                x = cx + 14
                y = cy - (height // 2)
            else:
                if self.settings.get("popup_wayland_fallback_horizontal") == "cursor":
                    x = cx + 14
                else:
                    x = geo.left() + ((geo.width() - width) // 2)
                y = geo.top() + self.settings.get("popup_wayland_fallback_top", 112)
                logger.info("Usando posicion fallback para popup: x=%s y=%s", x, y)

            if x + width > geo.right():
                x = cx - width - 14
                if not cursor_reliable and self.settings.get(
                    "popup_wayland_fallback_horizontal"
                ) == "center":
                    x = geo.right() - width + 1
            if y + height > geo.bottom():
                y = geo.bottom() - height + 1

            x = max(geo.left(), x)
            y = max(geo.top(), y)
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
        handle = self.windowHandle()
        if handle is not None and hasattr(handle, "requestActivate"):
            handle.requestActivate()
        else:
            self.activateWindow()
        self.setFocus(Qt.PopupFocusReason)
        logger.info("Popup visible=%s geometry=%s", self.isVisible(), self.geometry())


def validate_actions(actions):
    if not isinstance(actions, list):
        return DEFAULT_ACTIONS


    valid = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        name = action.get("name")
        icon = action.get("icon")
        cmd = action.get("cmd")
        if not all(isinstance(value, str) and value for value in (name, icon, cmd)):
            continue
        valid.append({
            "name": name,
            "icon": icon,
            "cmd": cmd,
            "enabled": bool(action.get("enabled", True)),
        })

    return valid or DEFAULT_ACTIONS


def load_actions_file():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIONS_FILE.exists():
        try:
            with ACTIONS_FILE.open("r", encoding="utf-8") as file:
                return validate_actions(json.load(file))
        except Exception as exc:
            logger.warning("No se pudo cargar actions.json: %s", exc)

    with ACTIONS_FILE.open("w", encoding="utf-8") as file:
        json.dump(DEFAULT_ACTIONS, file, indent=2, ensure_ascii=False)
    return DEFAULT_ACTIONS


def build_command_argv(template, text):
    raw_marker = "__TEXTPIK_SELECTED_TEXT__"
    url_marker = "__TEXTPIK_SELECTED_TEXT_URL__"
    template = (
        template.replace("{url}", url_marker)
        .replace("{}", raw_marker)
        .replace("***", raw_marker)
    )
    argv = shlex.split(template)

    result = []
    for arg in argv:
        if raw_marker in arg and arg.startswith(("http://", "https://")):
            arg = arg.replace(raw_marker, quote_plus(text))
        else:
            arg = arg.replace(raw_marker, text)
        arg = arg.replace(url_marker, quote_plus(text))
        result.append(arg)
    return result


def normalize_url(text):
    url = text.strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def is_terminal_execution(cmd):
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if not argv:
        return False
    executable = Path(argv[0]).name
    return executable in {"konsole", "gnome-terminal", "xterm", "alacritty", "kitty"}


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

    if command in {"copy", "paste", "terminal"}:
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

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(action.get("name", ""), self)
        self.name_edit.setPlaceholderText("Ej: Buscar en Wikipedia")
        form.addRow("Nombre", self.name_edit)

        self.icon_edit = QLineEdit(action.get("icon", ""), self)
        self.icon_edit.setPlaceholderText("Ej: search-google.svg")
        form.addRow("Icono", self.icon_edit)

        self.cmd_edit = QLineEdit(action.get("cmd", ""), self)
        self.cmd_edit.setPlaceholderText("Ej: xdg-open 'https://example.com?q={url}'")
        form.addRow("Comando", self.cmd_edit)

        self.enabled_check = QCheckBox("Mostrar esta accion", self)
        self.enabled_check.setChecked(bool(action.get("enabled", True)))
        form.addRow("Activa", self.enabled_check)

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
            "name": self.name_edit.text().strip(),
            "icon": self.icon_edit.text().strip(),
            "cmd": self.cmd_edit.text().strip(),
            "enabled": self.enabled_check.isChecked(),
        }
        if validate and not all(action[key] for key in ("name", "icon", "cmd")):
            return None
        if not validate and not all(action[key] for key in ("name", "icon", "cmd")):
            return None
        return action


class SettingsDialog(QDialog):
    def __init__(self, settings, actions, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuracion de textpik")
        self.setMinimumSize(560, 520)
        self.resize(640, 720)
        self.controller = controller
        self.settings = normalize_settings(settings)
        self.actions = list(actions)

        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(360)
        scroll.setMaximumHeight(620)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)

        # --- Apariencia ---
        ap_group = QGroupBox("Apariencia", self)
        ap_form = QFormLayout(ap_group)
        self._color_widgets = {}

        def _make_color_row(key, label):
            container = QWidget(self)
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            btn = QPushButton(container)
            btn.setFixedSize(32, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, k=key, b=btn: self.choose_color(k, b)
            )
            lbl = QLabel(self.settings[key], container)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(btn)
            h.addWidget(lbl)
            self._update_swatch(btn, self.settings[key])
            self._color_widgets[key] = (btn, lbl)
            ap_form.addRow(label, container)

        _make_color_row("popup_background_color", "Fondo de barra")
        _make_color_row("popup_border_color", "Borde de barra")

        self.icon_size = QSpinBox(self)
        self.icon_size.setRange(12, 64)
        self.icon_size.setValue(int(self.settings["popup_icon_size"]))
        ap_form.addRow("Tamano iconos/barra", self.icon_size)

        self.radius = QSpinBox(self)
        self.radius.setRange(0, 48)
        self.radius.setValue(int(self.settings["popup_border_radius"]))
        ap_form.addRow("Bordes redondeados", self.radius)

        self.opacity = QSpinBox(self)
        self.opacity.setRange(25, 100)
        self.opacity.setValue(int(float(self.settings["popup_opacity"]) * 100))
        ap_form.addRow("Opacidad (%)", self.opacity)

        self.theme_combo = QComboBox(self)
        self.theme_combo.addItem("Personalizado", "custom")
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Oscuro", "dark")
        self.theme_combo.addItem("OLED", "oled")
        current_theme = self.settings.get("theme_preset", "custom")
        idx = self.theme_combo.findData(current_theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._apply_theme_preset)
        ap_form.addRow("Tema predefinido", self.theme_combo)

        content_layout.addWidget(ap_group)

        # --- Comportamiento ---
        comp_group = QGroupBox("Comportamiento", self)
        comp_form = QFormLayout(comp_group)

        self.show_on_selection = QCheckBox("Mostrar al seleccionar texto", self)
        self.show_on_selection.setChecked(bool(self.settings["show_on_selection"]))
        comp_form.addRow("Activacion", self.show_on_selection)

        self.popup_delay = QSpinBox(self)
        self.popup_delay.setRange(0, 5000)
        self.popup_delay.setSuffix(" ms")
        self.popup_delay.setValue(int(self.settings.get("popup_delay_ms", 0)))
        comp_form.addRow("Retardo", self.popup_delay)

        self.confirm_terminal = QCheckBox(
            "Preguntar antes de ejecutar en terminal", self
        )
        self.confirm_terminal.setChecked(
            bool(self.settings.get("confirm_terminal_execution", True))
        )
        comp_form.addRow("Confirmacion terminal", self.confirm_terminal)

        self.max_selection = QSpinBox(self)
        self.max_selection.setRange(1, 50000)
        self.max_selection.setValue(int(self.settings["max_selection_length"]))
        comp_form.addRow("Maximo texto", self.max_selection)

        self.disable_in_games = QCheckBox("No mostrar en juegos detectados", self)
        self.disable_in_games.setChecked(bool(self.settings["disable_in_games"]))
        comp_form.addRow("Filtro anti-juegos", self.disable_in_games)

        content_layout.addWidget(comp_group)

        # --- Filtro de aplicaciones ---
        filtros_group = QGroupBox("Filtro de aplicaciones", self)
        filtros_layout = QVBoxLayout(filtros_group)

        self.blocked_apps_enabled = QCheckBox(
            "No mostrar en estas aplicaciones", self
        )
        self.blocked_apps_enabled.setChecked(
            bool(self.settings.get("blocked_apps_enabled", False))
        )
        filtros_layout.addWidget(self.blocked_apps_enabled)

        self.blocked_list = QListWidget(self)
        self.blocked_list.setMinimumHeight(80)
        self._populate_blocked_list()
        filtros_layout.addWidget(self.blocked_list)

        btn_layout_f = QHBoxLayout()
        add_btn = QPushButton("Anadir", self)
        add_btn.clicked.connect(self._add_blocked_app)
        remove_btn = QPushButton("Eliminar", self)
        remove_btn.clicked.connect(self._remove_blocked_app)
        btn_layout_f.addWidget(add_btn)
        btn_layout_f.addWidget(remove_btn)
        btn_layout_f.addStretch()
        filtros_layout.addLayout(btn_layout_f)

        content_layout.addWidget(filtros_group)

        # --- Wayland ---
        wl_group = QGroupBox("Wayland", self)
        wl_form = QFormLayout(wl_group)

        self.fallback_top = QSpinBox(self)
        self.fallback_top.setRange(0, 600)
        self.fallback_top.setSuffix(" px")
        self.fallback_top.setValue(
            int(self.settings["popup_wayland_fallback_top"])
        )
        wl_form.addRow("Posicion superior fallback", self.fallback_top)

        self.fallback_horizontal = QComboBox(self)
        self.fallback_horizontal.addItem("Centrada", "center")
        self.fallback_horizontal.addItem("Usar cursor si es posible", "cursor")
        index = self.fallback_horizontal.findData(
            self.settings["popup_wayland_fallback_horizontal"]
        )
        self.fallback_horizontal.setCurrentIndex(max(0, index))
        wl_form.addRow("Anclaje horizontal", self.fallback_horizontal)

        self.enable_wl_polling = QCheckBox("Habilitar polling en Wayland", self)
        self.enable_wl_polling.setChecked(
            bool(self.settings.get("enable_wayland_polling", True))
        )
        wl_form.addRow("Polling", self.enable_wl_polling)

        content_layout.addWidget(wl_group)

        # --- Diagnostico ---
        diag_group = QGroupBox("Diagnostico", self)
        diag_form = QFormLayout(diag_group)

        self.log_enabled = QCheckBox("Guardar archivo de log", self)
        self.log_enabled.setChecked(bool(self.settings["log_enabled"]))
        diag_form.addRow("Log", self.log_enabled)

        self.diagnostics_text = QTextEdit(self)
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setMinimumHeight(140)
        self.diagnostics_text.setPlainText(self.controller.build_diagnostics())
        diag_form.addRow("Estado", self.diagnostics_text)

        diag_buttons = QHBoxLayout()
        refresh_diag_btn = QPushButton("Actualizar diagnostico", self)
        refresh_diag_btn.clicked.connect(self._refresh_diagnostics)
        test_popup_btn = QPushButton("Probar popup", self)
        test_popup_btn.clicked.connect(self._test_popup)
        diag_buttons.addWidget(refresh_diag_btn)
        diag_buttons.addWidget(test_popup_btn)
        diag_buttons.addStretch()
        diag_form.addRow("Pruebas", diag_buttons)

        content_layout.addWidget(diag_group)

        # --- Disposicion de acciones ---
        disp_group = QGroupBox("Disposicion de acciones", self)
        disp_layout = QVBoxLayout(disp_group)

        self.action_list = QListWidget(self)
        self.action_list.setAlternatingRowColors(True)
        self.action_list.setMinimumHeight(120)
        self._populate_action_list()
        disp_layout.addWidget(self.action_list)

        btn_layout = QHBoxLayout()
        add_action_btn = QPushButton("Anadir", self)
        add_action_btn.clicked.connect(self._add_action)
        edit_action_btn = QPushButton("Editar", self)
        edit_action_btn.clicked.connect(self._edit_action)
        delete_action_btn = QPushButton("Eliminar", self)
        delete_action_btn.clicked.connect(self._delete_action)
        up_btn = QPushButton("Subir", self)
        up_btn.clicked.connect(self._move_up)
        down_btn = QPushButton("Bajar", self)
        down_btn.clicked.connect(self._move_down)
        btn_layout.addWidget(add_action_btn)
        btn_layout.addWidget(edit_action_btn)
        btn_layout.addWidget(delete_action_btn)
        btn_layout.addWidget(up_btn)
        btn_layout.addWidget(down_btn)
        btn_layout.addStretch()
        disp_layout.addLayout(btn_layout)

        note = QLabel(
            "Los iconos se adaptan automaticamente al color de la barra "
            "usando variantes blanco/negro.",
            self,
        )
        note.setWordWrap(True)
        disp_layout.addWidget(note)
        content_layout.addWidget(disp_group)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # --- Botones ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_clicked)
        layout.addWidget(buttons)

    def _apply_theme_preset(self):
        preset = self.theme_combo.currentData()
        if preset == "custom":
            return
        presets = {
            "light": {"popup_background_color": "#f7f7f7", "popup_border_color": "#d0d0d0"},
            "dark": {"popup_background_color": "#2d2d2d", "popup_border_color": "#555555"},
            "oled": {"popup_background_color": "#000000", "popup_border_color": "#333333"},
        }
        colors = presets.get(preset, {})
        for key, value in colors.items():
            self.settings[key] = value
            pair = self._color_widgets.get(key)
            if pair:
                pair[0].setStyleSheet(
                    "background-color: %s; border: 1px solid #888; border-radius: 3px;" % value
                )
                pair[1].setText(value)

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

    def _add_blocked_app(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Anadir aplicacion",
            "Nombre de la clase de ventana (ej: firefox, konsole, code):"
        )
        if ok and text.strip():
            self.blocked_list.addItem(text.strip().lower())

    def _remove_blocked_app(self):
        row = self.blocked_list.currentRow()
        if row >= 0:
            self.blocked_list.takeItem(row)

    def _update_swatch(self, button, color_name):
        button.setStyleSheet(
            "background-color: %s; border: 1px solid #888; border-radius: 3px;" % color_name
        )
        button.setToolTip(color_name)

    def choose_color(self, key, button):
        color = QColorDialog.getColor(QColor(self.settings[key]), self, "Seleccionar color")
        if color.isValid():
            self.settings[key] = color.name()
            self._update_swatch(button, color.name())
            pair = self._color_widgets.get(key)
            if pair:
                pair[1].setText(color.name())

    def _populate_action_list(self):
        self.action_list.clear()
        for action in self.actions:
            item = QListWidgetItem(f"{action['name']}  ({action['cmd'][:48]})")
            item.setData(Qt.UserRole, action)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if action.get("enabled", True) else Qt.Unchecked)
            self.action_list.addItem(item)

    def _move_up(self):
        row = self.action_list.currentRow()
        if row <= 0:
            return
        item = self.action_list.takeItem(row)
        self.action_list.insertItem(row - 1, item)
        self.action_list.setCurrentRow(row - 1)
        self.actions.insert(row - 1, self.actions.pop(row))

    def _move_down(self):
        row = self.action_list.currentRow()
        if row < 0 or row >= self.action_list.count() - 1:
            return
        item = self.action_list.takeItem(row)
        self.action_list.insertItem(row + 1, item)
        self.action_list.setCurrentRow(row + 1)
        self.actions.insert(row + 1, self.actions.pop(row))

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
        row = self.action_list.currentRow()
        if row < 0 or row >= len(self.actions):
            QMessageBox.information(self, "Editar accion", "Selecciona una accion primero.")
            return
        self._sync_enabled_from_list()
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
        row = self.action_list.currentRow()
        if row < 0 or row >= len(self.actions):
            QMessageBox.information(self, "Eliminar accion", "Selecciona una accion primero.")
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
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            if i < len(self.actions):
                self.actions[i]["enabled"] = item.checkState() == Qt.Checked

    def collect_settings(self):
        self._sync_enabled_from_list()
        self.settings["popup_icon_size"] = self.icon_size.value()
        self.settings["popup_border_radius"] = self.radius.value()
        self.settings["popup_opacity"] = self.opacity.value() / 100
        self.settings["popup_delay_ms"] = self.popup_delay.value()
        self.settings["confirm_terminal_execution"] = self.confirm_terminal.isChecked()
        self.settings["enable_wayland_polling"] = self.enable_wl_polling.isChecked()
        self.settings["popup_wayland_fallback_top"] = self.fallback_top.value()
        self.settings["popup_wayland_fallback_horizontal"] = self.fallback_horizontal.currentData()
        self.settings["max_selection_length"] = self.max_selection.value()
        self.settings["show_on_selection"] = self.show_on_selection.isChecked()
        self.settings["disable_in_games"] = self.disable_in_games.isChecked()
        self.settings["theme_preset"] = self.theme_combo.currentData()
        self.settings["blocked_apps_enabled"] = self.blocked_apps_enabled.isChecked()
        self.settings["blocked_apps"] = [
            self.blocked_list.item(i).text()
            for i in range(self.blocked_list.count())
        ]
        self.settings["log_enabled"] = self.log_enabled.isChecked()
        return normalize_settings(self.settings), list(self.actions)

    def apply_clicked(self):
        settings, actions = self.collect_settings()
        if actions != self.controller.actions:
            self.controller.actions = actions
            self.controller.save_actions()
            self.controller.popup.set_actions(actions)
        self.controller.update_settings(settings)


class TextPikApp(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setDesktopFileName(APP_NAME)
        self.app.setWindowIcon(load_icon(APP_ICON_FILE, "edit-select-all"))
        self.app.setQuitOnLastWindowClosed(False)
        self.app.aboutToQuit.connect(self.cleanup)

        self.settings = load_settings()
        setup_logging(self.settings)
        logger.info("Iniciando textpik con plataforma Qt: %s", self.app.platformName())
        log_cursor_position_diagnostics(self.app.platformName())

        self.lock_file = QLockFile(str(CONFIG_DIR / "textpik.lock"))
        self.lock_file.setStaleLockTime(0)
        if not self.lock_file.tryLock(100):
            logger.warning("textpik ya esta ejecutandose; saliendo")
            if check_command("notify-send"):
                subprocess.Popen(["notify-send", APP_NAME, "textpik ya esta ejecutandose"])
            sys.exit(0)

        check_runtime_dependencies()
        self.cursor_bridge = None
        self.cursor_bridge_adaptor = None
        self.cursor_bridge_bus = None
        self.setup_cursor_bridge()

        self.actions = self.load_actions()
        self.monitor = (
            WaylandSelectionMonitor(self.settings)
            if is_wayland()
            else X11SelectionMonitor(self.settings)
        )
        self.monitor.selection_changed.connect(self.show_popup)
        self.monitor.selection_cleared.connect(self.hide_popup)

        self.popup = PopupWindow(self.actions, self.monitor, self.settings)
        self.popup.action_triggered.connect(self.execute_action)
        self.pointer = X11Pointer()
        self.process_filter = ProcessFilter(self.settings)
        self._animating = False
        self._popup_animation = None
        self._popup_immunity_until = 0.0
        self._outside_count = 0
        self._selection_released = False
        self._last_popup_text = ""
        self._last_popup_at = 0.0

        self.hide_check_timer = QTimer(self)
        self.hide_check_timer.timeout.connect(self.hide_popup_on_external_click)
        self.app.applicationStateChanged.connect(self.on_application_state_changed)
        self.app.focusWindowChanged.connect(self.on_focus_window_changed)

        self.hotkey_active = False
        self.keyboard = None
        self.setup_hotkey()

        self.create_tray_icon()

    def setup_cursor_bridge(self):
        if not is_wayland() or not qt_dbus_available():
            return

        try:
            from PySide6.QtDBus import QDBusConnection

            bus = QDBusConnection.sessionBus()
            if not bus.registerService(CURSOR_BRIDGE_SERVICE):
                logger.warning("No se pudo registrar servicio D-Bus %s", CURSOR_BRIDGE_SERVICE)
                return

            bridge = CursorBridge()
            bridge._on_click_outside = lambda: self.hide_popup()
            adaptor = create_cursor_bridge_adaptor(bridge)
            if not bus.registerObject(
                CURSOR_BRIDGE_PATH,
                bridge,
                QDBusConnection.ExportAdaptors,
            ):
                bus.unregisterService(CURSOR_BRIDGE_SERVICE)
                logger.warning("No se pudo registrar objeto D-Bus %s", CURSOR_BRIDGE_PATH)
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
        try:
            import keyboard

            self.keyboard = keyboard
            self.keyboard.add_hotkey("ctrl+shift+p", self.hotkey_triggered)
            self.hotkey_active = True
        except ImportError:
            print("Libreria 'keyboard' no encontrada. Atajo global deshabilitado.")
        except Exception as exc:
            print("Error registrando atajo global:", exc)

    def hotkey_triggered(self):
        if self.popup.isVisible():
            self.hide_popup()
        else:
            self.show_popup(force=True)

    def on_application_state_changed(self, state):
        if state != Qt.ApplicationActive:
            self.hide_popup()

    def on_focus_window_changed(self, focus_window):
        if not self.popup.isVisible():
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
            logger.info("Click externo detectado; ocultando popup")
            self.hide_popup()

    def load_actions(self):
        return load_actions_file()

    def save_actions(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with ACTIONS_FILE.open("w", encoding="utf-8") as file:
            json.dump(self.actions, file, indent=2, ensure_ascii=False)

    def save_settings(self):
        self.settings = normalize_settings(self.settings)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with SETTINGS_FILE.open("w", encoding="utf-8") as file:
            json.dump(self.settings, file, indent=2, ensure_ascii=False)

    def reload_actions(self):
        self.actions = self.load_actions()
        self.popup.set_actions(self.actions)
        QMessageBox.information(None, "Configuracion", "Acciones recargadas.")

    def reload_settings(self):
        self.settings = load_settings()
        setup_logging(self.settings)
        self.monitor.settings = self.settings
        self.process_filter.settings = self.settings
        self.popup.apply_settings(self.settings)
        if hasattr(self.monitor, "_poll_timer"):
            if (
                self.settings.get("enable_wayland_polling", True)
                and not getattr(self.monitor, "_use_wl_paste", False)
            ):
                self.monitor._poll_timer.start(500)
            else:
                self.monitor._poll_timer.stop()
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
            self._popup_animation = QPropertyAnimation(self.popup, b"windowOpacity", self)
            self._popup_animation.setDuration(120)
            self._popup_animation.setStartValue(0.0)
            self._popup_animation.setEndValue(target)
            self._popup_animation.finished.connect(lambda: setattr(self, "_animating", False))
            self._popup_animation.start()
        except Exception:
            self.popup.setWindowOpacity(target)
            self._animating = False

    def hide_popup(self):
        self.hide_check_timer.stop()
        self._popup_immunity_until = 0.0
        self._outside_count = 0
        self._selection_released = False
        if self.popup.isVisible():
            if not self._animating:
                self.popup.hide()
            else:
                self._animating = False
                self.popup.hide()

    def update_settings(self, settings):
        self.settings = normalize_settings(settings)
        self.save_settings()
        setup_logging(self.settings)
        self.monitor.settings = self.settings
        self.process_filter.settings = self.settings
        self.popup.apply_settings(self.settings)
        self.popup.set_actions(self.popup.actions)

        if hasattr(self.monitor, "_poll_timer"):
            if (
                self.settings.get("enable_wayland_polling", True)
                and not getattr(self.monitor, "_use_wl_paste", False)
            ):
                self.monitor._poll_timer.start(500)
            else:
                self.monitor._poll_timer.stop()

    def build_diagnostics(self):
        bridge_status = "inactivo"
        if kwin_bridge_cursor is not None:
            x, y, timestamp = kwin_bridge_cursor
            age = time.monotonic() - timestamp
            bridge_status = f"activo ({x},{y}, hace {age:.1f}s)"

        enabled_actions = len([a for a in self.actions if a.get("enabled", True)])
        popup_geo = self.popup.geometry() if hasattr(self, "popup") else "sin popup"
        lines = [
            f"Sesion: {os.environ.get('XDG_SESSION_TYPE', '') or 'desconocida'}",
            f"Qt platform: {self.app.platformName()}",
            f"DISPLAY: {'si' if os.environ.get('DISPLAY') else 'no'}",
            f"WAYLAND_DISPLAY: {'si' if os.environ.get('WAYLAND_DISPLAY') else 'no'}",
            f"Backend seleccion: {'Wayland/wl-paste' if is_wayland() else 'X11/PRIMARY'}",
            f"Monitor activo: {'si' if self.monitor._active else 'no'}",
            f"Mostrar al seleccionar: {'si' if self.settings.get('show_on_selection', True) else 'no'}",
            f"wl-paste: {'ok' if check_command('wl-paste') else 'falta'}",
            f"wl-copy: {'ok' if check_command('wl-copy') else 'falta'}",
            f"xdotool: {'ok' if check_command('xdotool') else 'falta'}",
            f"ydotool: {'ok' if check_command('ydotool') else 'falta'}",
            f"xdg-open: {'ok' if check_command('xdg-open') else 'falta'}",
            f"QtDBus: {'ok' if qt_dbus_available() else 'falta'}",
            f"Puente KWin: {bridge_status}",
            f"Popup visible: {'si' if self.popup.isVisible() else 'no'}",
            f"Popup geometry: {popup_geo}",
            f"Acciones habilitadas: {enabled_actions}/{len(self.actions)}",
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
        if not is_wayland() or not qt_dbus_available():
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
                        if isinstance(pos, QtPoint):
                            self.cursor_bridge.update_cursor(pos.x(), pos.y())
                        elif isinstance(pos, (tuple, list)) and len(pos) >= 2:
                            self.cursor_bridge.update_cursor(int(pos[0]), int(pos[1]))
                        return
        except Exception:
            pass

    def show_popup(self, force=False):
        if not force and not self.monitor._active:
            return
        if not force and not self.settings.get("show_on_selection", True):
            return
        if not force and self.process_filter.is_foreground_process_game():
            logger.info("Popup omitido por filtro anti-juegos")
            return
        if not force and self.process_filter.is_foreground_process_blocked():
            logger.info("Popup omitido por filtro de aplicaciones")
            return
        text = self.monitor.get_last_text().strip()
        if text:
            now = time.monotonic()
            if (
                not force
                and self.popup.isVisible()
                and text == self._last_popup_text
                and now - self._last_popup_at < 0.7
            ):
                logger.debug("Popup duplicado ignorado")
                return
            logger.info("Mostrando popup para seleccion de %d caracteres", len(text))
            visible = [a for a in self.actions if a.get("enabled", True)]
            if not visible:
                logger.info("Popup omitido: no hay acciones habilitadas")
                return
            self.popup.set_actions(visible)
            self.request_cursor_update()
            self.popup.show_at_cursor()
            self._animate_popup_fade_in()
            self._last_popup_text = text
            self._last_popup_at = now
            self._popup_immunity_until = time.monotonic() + 0.3
            self._outside_count = 0
            self._selection_released = False
            self.hide_check_timer.start(20)

    def execute_action(self, cmd, text):
        text = text or ""
        if cmd == "copy":
            QApplication.clipboard().setText(text)
            return

        if cmd == "paste":
            self.paste_text(text)
            return

        if cmd == "terminal":
            self.open_terminal_with_command(text)
            return

        if cmd == "print":
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="textpik-print-", delete=False
                ) as f:
                    f.write(text)
                    tmpfile = f.name
                subprocess.run(["lp", tmpfile], check=True)
                QMessageBox.information(
                    None, "Imprimir", "Texto enviado a la impresora."
                )
            except Exception as exc:
                QMessageBox.warning(
                    None, "Error de impresion", f"No se pudo imprimir:\n{exc}"
                )
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
                subprocess.Popen(["xdg-open", url])
            except Exception as exc:
                QMessageBox.warning(None, "Error", f"No se pudo abrir la URL:\n{exc}")
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
                subprocess.Popen(argv)
            except Exception as exc:
                QMessageBox.warning(None, "Error", f"No se pudo ejecutar el comando:\n{exc}")

    def query_ollama(self, text):
        import shutil

        if not shutil.which("ollama"):
            QMessageBox.information(
                None,
                "Ollama no instalado",
                "Ollama no está instalado en el sistema.\n\n"
                "Instalalo desde: https://ollama.com/download\n"
                "O con: curl -fsSL https://ollama.com/install.sh | sh",
            )
            return

        model = "llama3"
        import urllib.request

        payload = json.dumps({
            "model": model,
            "prompt": text,
            "stream": False,
        }).encode()

        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            response_text = result.get("response", json.dumps(result, indent=2))
        except Exception as exc:
            QMessageBox.warning(None, "Error de Ollama", str(exc))
            return

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
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(response_text),
            QMessageBox.information(dialog, "Copiado", "Respuesta copiada al portapapeles."),
        ))
        btn_layout.addWidget(copy_btn)
        close_btn = QPushButton("Cerrar", dialog)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.show()

    def open_config_folder(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(CONFIG_DIR)])

    def edit_actions_file(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not ACTIONS_FILE.exists():
            self.save_actions()
        subprocess.Popen(["xdg-open", str(ACTIONS_FILE)])

    def edit_settings_file(self):
        load_settings()
        subprocess.Popen(["xdg-open", str(SETTINGS_FILE)])

    def open_log_file(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.write_text("", encoding="utf-8")
        subprocess.Popen(["xdg-open", str(LOG_FILE)])

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
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                text_edit.setPlainText("\n".join(lines[-1000:]))
            except Exception as exc:
                text_edit.setPlainText(f"Error leyendo log: {exc}")
        else:
            text_edit.setPlainText("No hay archivo de log.")

        layout.addWidget(text_edit)
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refrescar", dialog)
        refresh_btn.clicked.connect(
            lambda: self._refresh_log_view(text_edit)
        )
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
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
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

        clipboard_commands = []
        if is_wayland() and check_command("wl-copy"):
            clipboard_commands.append(["wl-copy"])
        if check_command("xclip"):
            clipboard_commands.append(["xclip", "-selection", "clipboard"])
        if check_command("xsel"):
            clipboard_commands.append(["xsel", "--clipboard", "--input"])

        for command in clipboard_commands:
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True)
                process.communicate(text, timeout=1)
                if process.returncode == 0:
                    return True
            except subprocess.TimeoutExpired:
                process.kill()
                logger.warning("Timeout copiando con %s", command[0])
            except Exception as exc:
                logger.warning("No se pudo copiar con %s: %s", command[0], exc)

        return True

    def open_terminal_with_command(self, text):
        self.copy_text_to_clipboard(text)
        command_line = " ".join(text.splitlines()).strip()

        script = r'''
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
'''.strip()

        terminal_argv = None
        for name, argv in (
            ("konsole", ["konsole", "-e", "bash", "-lc", script]),
            ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", script]),
            ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(script)}"]),
            ("xterm", ["xterm", "-e", "bash", "-lc", script]),
            ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-lc", script]),
        ):
            if check_command(name):
                terminal_argv = argv
                break

        if terminal_argv is None:
            QMessageBox.warning(None, "Terminal no disponible", "No se encontro una terminal instalada.")
            return

        env = os.environ.copy()
        env["TEXTPIK_TEXT"] = command_line
        try:
            subprocess.Popen(terminal_argv, env=env)
            logger.info("Terminal abierta con comando precargado de %d caracteres", len(command_line))
        except Exception as exc:
            QMessageBox.warning(None, "Error", f"No se pudo abrir la terminal:\n{exc}")

    def paste_text(self, text):
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        def run_paste():
            try:
                if is_wayland() and check_command("ydotool"):
                    subprocess.Popen(["ydotool", "type", "--", text])
                elif check_command("xdotool"):
                    subprocess.Popen(["xdotool", "key", "ctrl+v"])
                else:
                    print("No se encontro herramienta para pegar automaticamente. Texto copiado.")
            except Exception as exc:
                QMessageBox.warning(
                    None,
                    "Pegado automatico no disponible",
                    "El texto fue copiado, pero no se pudo pegar automaticamente:\n"
                    f"{exc}",
                )

        QTimer.singleShot(120, run_paste)

    def create_tray_icon(self):
        self.tray = QSystemTrayIcon(self)
        icon = load_icon(TRAY_ICON_FILE, "edit-select-all")
        if icon.isNull():
            icon = self.app.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self.tray.setIcon(icon)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        self.toggle_action = QAction("Pausar", self)
        self.toggle_action.triggered.connect(self.toggle_monitor)
        menu.addAction(self.toggle_action)

        show_now_action = QAction("Mostrar menu ahora", self)
        show_now_action.triggered.connect(lambda: self.show_popup(force=True))
        menu.addAction(show_now_action)

        menu.addSeparator()

        settings_action = QAction("Configuracion...", self)
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
        open_log_action = QAction("Abrir archivo de log", self)
        open_log_action.triggered.connect(self.open_log_file)
        config_menu.addAction(open_log_action)

        menu.addMenu(config_menu)
        menu.addSeparator()

        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def toggle_monitor(self):
        if self.monitor._active:
            self.monitor.pause()
            self.toggle_action.setText("Reanudar")
            self.popup.hide()
        else:
            self.monitor.resume()
            self.toggle_action.setText("Pausar")

    def quit(self):
        self.cleanup()
        self.app.quit()

    def cleanup(self):
        if hasattr(self, "monitor"):
            self.monitor.pause()
        if getattr(self, "cursor_bridge_bus", None) is not None:
            try:
                self.cursor_bridge_bus.unregisterObject(CURSOR_BRIDGE_PATH)
                self.cursor_bridge_bus.unregisterService(CURSOR_BRIDGE_SERVICE)
            except Exception:
                pass
        if getattr(self, "hotkey_active", False) and getattr(self, "keyboard", None):
            try:
                self.keyboard.unhook_all_hotkeys()
            except Exception:
                pass

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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
