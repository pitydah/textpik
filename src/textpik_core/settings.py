"""Versioned settings schema and migrations independent from the UI toolkit."""

from __future__ import annotations

from collections.abc import Callable
import re
from urllib.parse import urlsplit

from .profiles import normalize_profiles
from .media import normalize_torrent_servers


DEFAULT_SETTINGS = {
    "ui_version": 13,
    "show_on_selection": True,
    "start_at_login": True,
    "popup_delay_ms": 0,
    "adaptive_delay_enabled": True,
    "adaptive_delay_min_ms": 55,
    "adaptive_delay_max_ms": 180,
    "popup_auto_hide_ms": 8000,
    "max_selection_length": 5000,
    "max_popup_actions": 8,
    "show_all_popup_actions": False,
    "popup_allow_two_rows": True,
    "popup_position_preference": "auto",
    "confirm_terminal_execution": True,
    "context_aware": True,
    "history_enabled": False,
    "history_max_items": 100,
    "history_max_age_days": 30,
    "spelling_ignored_words": [],
    "spelling_personal_words": [],
    "context_profiles_enabled": False,
    "context_profiles": [],
    "spelling_action_migrated": False,
    "adaptive_popup": False,
    "developer_mode": False,
    "popup_min_confidence": 62,
    "popup_full_confidence": 84,
    "popup_compact_actions": 8,
    "sticky_popup": False,
    "show_numeric_badges": False,
    "enable_global_hotkey": False,
    "enable_wayland_polling": True,
    "log_enabled": True,
    "popup_background_color": "#18181b",
    "popup_button_color": "#18181b",
    "popup_hover_color": "#2a2a2f",
    "popup_border_color": "#3f3f46",
    "popup_button_border_color": "#18181b",
    "popup_icon_size": 17,
    "popup_button_padding": 4,
    "popup_spacing": 2,
    "popup_cursor_gap": 3,
    "popup_border_radius": 12,
    "popup_opacity": 0.99,
    "popup_wayland_fallback_top": 96,
    "popup_wayland_fallback_horizontal": "center",
    "disable_in_games": False,
    "disable_in_sensitive_fields": True,
    "ignore_file_selections": True,
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
    "blocked_activities_enabled": False,
    "blocked_activities": [],
    "theme_preset": "custom",
    "torrent_servers": [],
    "torrent_dispatch_mode": "ask",
    "ollama_endpoint": "http://127.0.0.1:11434/api/generate",
    "ollama_model": "",
    "languagetool_endpoint": "http://127.0.0.1:8010/v2/check",
    # Fail-closed opt-in for a non-loopback LanguageTool server. Never inferred
    # from a pre-existing remote endpoint: upgrading must not silently start
    # shipping the user's text off-box, so only an explicit setting can open it.
    "grammar_allow_remote": False,
    "grammar_language": "auto",
    "ocr_languages": "auto",
    "media_player": "auto",
    "terminal_app": "auto",
    "kdeconnect_device": "auto",
    "speech_engine": "auto",
    "spelling_language": "auto",
    "screenshot_backend": "auto",
    "printer": "auto",
    "browser_app": "auto",
    "translation_target": "es",
    "clipboard_backend": "auto",
}


def normalize_bool(value, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "si", "sí"}:
            return True
        if lowered in {"false", "0", "no", "off", ""}:
            return False
    return fallback


def normalize_settings(
    settings,
    *,
    color_normalizer: Callable[[object, str], str] | None = None,
) -> dict:
    """Migrate and bound persisted settings without retaining unknown keys."""
    if not isinstance(settings, dict):
        settings = {}
    try:
        ui_version = int(settings.get("ui_version", 0))
    except (TypeError, ValueError):
        ui_version = 0
    normalized = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in settings:
            normalized[key] = settings[key]

    if ui_version < 3:
        if normalized.get("popup_icon_size") == 18:
            normalized["popup_icon_size"] = 17
        if normalized.get("popup_border_radius") == 13:
            normalized["popup_border_radius"] = 12
        if normalized.get("popup_spacing") == 1:
            normalized["popup_spacing"] = 2
        if normalized.get("popup_background_color") == "#202124":
            normalized["popup_background_color"] = "#18181b"
        if normalized.get("popup_border_color") == "#45474c":
            normalized["popup_border_color"] = "#3f3f46"
    if ui_version < 4:
        normalized["ui_version"] = 4
    if ui_version < 5:
        if normalized.get("max_popup_actions") == 8:
            normalized["max_popup_actions"] = 6
        if normalized.get("popup_min_confidence") == 45:
            normalized["popup_min_confidence"] = 62
        if normalized.get("popup_full_confidence") == 78:
            normalized["popup_full_confidence"] = 84
        normalized["ui_version"] = 5
    if ui_version < 6:
        try:
            normalized["max_popup_actions"] = max(
                8, int(normalized.get("max_popup_actions", 8))
            )
        except (TypeError, ValueError):
            normalized["max_popup_actions"] = 8
        try:
            normalized["popup_compact_actions"] = max(
                8, int(normalized.get("popup_compact_actions", 8))
            )
        except (TypeError, ValueError):
            normalized["popup_compact_actions"] = 8
        normalized["ui_version"] = 6
    if ui_version < 7:
        # Upgrade only the former stock behavior. Deliberate user values are
        # preserved while existing installs gain a calmer, closer popup.
        if normalized.get("popup_auto_hide_ms") == 5000:
            normalized["popup_auto_hide_ms"] = 12000
        if normalized.get("popup_cursor_gap") == 6:
            normalized["popup_cursor_gap"] = 3
        normalized["ui_version"] = 7
    if ui_version < 8:
        if normalized.get("popup_auto_hide_ms") == 12000:
            normalized["popup_auto_hide_ms"] = 8000
        normalized["ui_version"] = 8
    if ui_version < 9:
        normalized["ui_version"] = 9
    if ui_version < 10:
        normalized["ui_version"] = 10
    if ui_version < 11:
        normalized["ui_version"] = 11
    if ui_version < 12:
        normalized["ui_version"] = 12
    if ui_version < 13:
        if ui_version > 0:
            normalized["adaptive_popup"] = False
        normalized["ui_version"] = 13

    _normalize_int(normalized, "popup_delay_ms", minimum=0)
    _normalize_int(normalized, "adaptive_delay_min_ms", minimum=30, maximum=200)
    _normalize_int(normalized, "adaptive_delay_max_ms", minimum=60, maximum=250)
    if normalized["adaptive_delay_max_ms"] < normalized["adaptive_delay_min_ms"]:
        normalized["adaptive_delay_max_ms"] = normalized["adaptive_delay_min_ms"]
    _normalize_int(normalized, "popup_auto_hide_ms", minimum=0, maximum=30000)
    _normalize_int(normalized, "max_selection_length", minimum=1)
    _normalize_int(normalized, "max_popup_actions", minimum=8, maximum=40)
    _normalize_int(normalized, "popup_min_confidence", minimum=0, maximum=90)
    _normalize_int(normalized, "popup_full_confidence", minimum=50, maximum=100)
    _normalize_int(normalized, "popup_compact_actions", minimum=8, maximum=40)
    normalized["popup_compact_actions"] = min(
        normalized["popup_compact_actions"], normalized["max_popup_actions"]
    )
    _normalize_int(normalized, "history_max_items", minimum=10, maximum=1000)
    _normalize_int(normalized, "history_max_age_days", minimum=1, maximum=3650)
    _normalize_int(normalized, "popup_icon_size", minimum=12, maximum=64)
    _normalize_int(normalized, "popup_button_padding", minimum=2, maximum=12)
    _normalize_int(normalized, "popup_spacing", minimum=0, maximum=8)
    _normalize_int(normalized, "popup_cursor_gap", minimum=2, maximum=24)
    _normalize_int(normalized, "popup_border_radius", minimum=0, maximum=64)
    _normalize_int(normalized, "popup_wayland_fallback_top", minimum=0)

    try:
        normalized["popup_opacity"] = min(
            1.0, max(0.25, float(normalized["popup_opacity"]))
        )
    except (TypeError, ValueError):
        normalized["popup_opacity"] = DEFAULT_SETTINGS["popup_opacity"]

    if normalized.get("popup_wayland_fallback_horizontal") not in ("center", "cursor"):
        normalized["popup_wayland_fallback_horizontal"] = DEFAULT_SETTINGS[
            "popup_wayland_fallback_horizontal"
        ]
    if normalized.get("popup_position_preference") not in ("auto", "above", "below", "side"):
        normalized["popup_position_preference"] = "auto"

    for key in (
        "show_on_selection",
        "confirm_terminal_execution",
        "enable_wayland_polling",
        "log_enabled",
        "disable_in_games",
        "blocked_apps_enabled",
        "blocked_activities_enabled",
        "context_aware",
        "history_enabled",
        "context_profiles_enabled",
        "spelling_action_migrated",
        "adaptive_popup",
        "developer_mode",
        "sticky_popup",
        "show_numeric_badges",
        "show_all_popup_actions",
        "popup_allow_two_rows",
        "adaptive_delay_enabled",
        "enable_global_hotkey",
        "disable_in_sensitive_fields",
        "ignore_file_selections",
        "start_at_login",
        "grammar_allow_remote",
    ):
        normalized[key] = normalize_bool(normalized[key], DEFAULT_SETTINGS[key])

    keywords = normalized.get("game_filter_keywords")
    if not isinstance(keywords, list):
        keywords = DEFAULT_SETTINGS["game_filter_keywords"]
    normalized["game_filter_keywords"] = [
        str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()
    ]

    blocked = normalized.get("blocked_apps", [])
    normalized["blocked_apps"] = (
        [str(value).strip().lower() for value in blocked if str(value).strip()]
        if isinstance(blocked, list)
        else []
    )
    activities = normalized.get("blocked_activities", [])
    normalized["blocked_activities"] = (
        [str(value).strip() for value in activities if str(value).strip()]
        if isinstance(activities, list)
        else []
    )
    normalized["context_profiles"] = normalize_profiles(
        normalized.get("context_profiles", [])
    )
    normalized["torrent_servers"] = normalize_torrent_servers(
        normalized.get("torrent_servers", [])
    )
    if normalized.get("torrent_dispatch_mode") not in {"ask", "default", "all"}:
        normalized["torrent_dispatch_mode"] = "ask"
    normalized["ollama_endpoint"] = _normalize_endpoint(
        normalized.get("ollama_endpoint"),
        DEFAULT_SETTINGS["ollama_endpoint"],
        local_only=True,
    )
    normalized["languagetool_endpoint"] = _normalize_endpoint(
        normalized.get("languagetool_endpoint"),
        DEFAULT_SETTINGS["languagetool_endpoint"],
    )
    normalized["ollama_model"] = _normalize_token(
        normalized.get("ollama_model"), r"[A-Za-z0-9_.:/-]{1,100}", ""
    )
    normalized["grammar_language"] = _normalize_token(
        normalized.get("grammar_language"), r"(?:auto|[A-Za-z]{2,3}(?:-[A-Za-z]{2})?)", "auto"
    )
    normalized["ocr_languages"] = _normalize_token(
        normalized.get("ocr_languages"), r"(?:auto|[A-Za-z0-9_.+-]{1,100})", "auto"
    )
    for key in ("media_player", "terminal_app", "speech_engine"):
        normalized[key] = _normalize_token(
            normalized.get(key), r"(?:auto|[A-Za-z0-9_.+-]{1,80})", "auto"
        )
    normalized["kdeconnect_device"] = _normalize_token(
        normalized.get("kdeconnect_device"), r"(?:auto|[A-Za-z0-9_.:-]{1,160})", "auto"
    )
    normalized["spelling_language"] = _normalize_token(
        normalized.get("spelling_language"),
        r"(?:auto|[A-Za-z]{2,3}(?:[_-][A-Za-z]{2})?)",
        "auto",
    )
    if normalized.get("screenshot_backend") not in {
        "auto", "spectacle", "gnome-screenshot", "grim-slurp", "portal"
    }:
        normalized["screenshot_backend"] = "auto"
    for key in ("printer", "browser_app"):
        normalized[key] = _normalize_token(
            normalized.get(key), r"(?:auto|[A-Za-z0-9_.:+-]{1,160})", "auto"
        )
    normalized["translation_target"] = _normalize_token(
        normalized.get("translation_target"), r"[A-Za-z]{2,3}(?:-[A-Za-z]{2})?", "es"
    )
    if normalized.get("clipboard_backend") not in {"auto", "klipper", "textpik"}:
        normalized["clipboard_backend"] = "auto"
    for key in ("spelling_ignored_words", "spelling_personal_words"):
        values = normalized.get(key, [])
        normalized[key] = (
            list(
                dict.fromkeys(
                    str(value).strip().casefold()
                    for value in values[:500]
                    if str(value).strip()
                )
            )
            if isinstance(values, list)
            else []
        )

    if normalized.get("theme_preset") not in ("custom", "dark", "light", "oled"):
        normalized["theme_preset"] = "custom"
    theme_presets = {
        "light": {
            "popup_background_color": "#fafafa",
            "popup_border_color": "#d4d4d8",
        },
        "dark": {
            "popup_background_color": "#18181b",
            "popup_border_color": "#3f3f46",
        },
        "oled": {
            "popup_background_color": "#09090b",
            "popup_border_color": "#27272a",
        },
    }
    preset = normalized.get("theme_preset")
    if preset in theme_presets:
        normalized.update(theme_presets[preset])

    if color_normalizer is not None:
        for key in (
            "popup_background_color",
            "popup_button_color",
            "popup_hover_color",
            "popup_border_color",
            "popup_button_border_color",
        ):
            normalized[key] = color_normalizer(normalized[key], DEFAULT_SETTINGS[key])
    return normalized


def _normalize_endpoint(value, fallback: str, *, local_only: bool = False) -> str:
    endpoint = str(value or "").strip()[:2048]
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return fallback
    if local_only and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return fallback
    return endpoint


def _normalize_token(value, pattern: str, fallback: str) -> str:
    token = str(value or "").strip()
    return token if re.fullmatch(pattern, token) else fallback


def _normalize_int(
    settings: dict,
    key: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    try:
        value = max(minimum, int(settings[key]))
        settings[key] = value if maximum is None else min(maximum, value)
    except (TypeError, ValueError):
        settings[key] = DEFAULT_SETTINGS[key]
