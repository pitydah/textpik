"""Versioned settings schema and migrations independent from the UI toolkit."""

from __future__ import annotations

from collections.abc import Callable

from .profiles import normalize_profiles


DEFAULT_SETTINGS = {
    "ui_version": 3,
    "show_on_selection": True,
    "start_at_login": True,
    "popup_delay_ms": 0,
    "popup_auto_hide_ms": 5000,
    "max_selection_length": 5000,
    "max_popup_actions": 8,
    "show_all_popup_actions": False,
    "confirm_terminal_execution": True,
    "context_aware": True,
    "context_profiles_enabled": False,
    "context_profiles": [],
    "spelling_action_migrated": False,
    "adaptive_popup": True,
    "popup_min_confidence": 45,
    "popup_full_confidence": 78,
    "popup_compact_actions": 4,
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
    "popup_cursor_gap": 6,
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
        normalized["ui_version"] = 3
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

    _normalize_int(normalized, "popup_delay_ms", minimum=0)
    _normalize_int(normalized, "popup_auto_hide_ms", minimum=0, maximum=30000)
    _normalize_int(normalized, "max_selection_length", minimum=1)
    _normalize_int(normalized, "max_popup_actions", minimum=3, maximum=40)
    _normalize_int(normalized, "popup_min_confidence", minimum=0, maximum=90)
    _normalize_int(normalized, "popup_full_confidence", minimum=50, maximum=100)
    _normalize_int(normalized, "popup_compact_actions", minimum=3, maximum=8)
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

    for key in (
        "show_on_selection",
        "confirm_terminal_execution",
        "enable_wayland_polling",
        "log_enabled",
        "disable_in_games",
        "blocked_apps_enabled",
        "blocked_activities_enabled",
        "context_aware",
        "context_profiles_enabled",
        "spelling_action_migrated",
        "adaptive_popup",
        "sticky_popup",
        "show_numeric_badges",
        "show_all_popup_actions",
        "enable_global_hotkey",
        "disable_in_sensitive_fields",
        "ignore_file_selections",
        "start_at_login",
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
