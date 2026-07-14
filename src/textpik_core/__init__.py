"""Core, desktop-independent building blocks for TextPik."""

from .models import (
    ActionManifest,
    ActionOperation,
    ActionResult,
    ActionResultType,
    AnchorSource,
    PopupAnchor,
    SelectionContext,
)
from .performance import MetricSnapshot, PerformanceTracker
from .execution import executable_name, is_terminal_execution
from .extensions import ExtensionIssue, inspect_local_extensions
from .platform import (
    TERMINAL_CANDIDATES,
    command_exists,
    detect_desktop_environment,
    find_available_terminal,
    is_kde_desktop,
    is_wayland_session,
)
from .planning import ContextSnapshot, plan_actions
from .profiles import ContextProfile, normalize_profiles, resolve_profile
from .settings import DEFAULT_SETTINGS, normalize_bool, normalize_settings
from .spelling import SpellingResult, SpellingService
from .storage import read_json, write_json_atomic
from .text import build_command_argv, classify_text, normalize_url

__all__ = [
    "ActionManifest",
    "ActionOperation",
    "ActionResult",
    "ActionResultType",
    "AnchorSource",
    "ContextSnapshot",
    "ContextProfile",
    "DEFAULT_SETTINGS",
    "ExtensionIssue",
    "MetricSnapshot",
    "PerformanceTracker",
    "PopupAnchor",
    "SelectionContext",
    "SpellingResult",
    "SpellingService",
    "build_command_argv",
    "classify_text",
    "command_exists",
    "detect_desktop_environment",
    "executable_name",
    "find_available_terminal",
    "is_kde_desktop",
    "is_terminal_execution",
    "is_wayland_session",
    "inspect_local_extensions",
    "normalize_url",
    "normalize_bool",
    "normalize_settings",
    "normalize_profiles",
    "plan_actions",
    "read_json",
    "resolve_profile",
    "TERMINAL_CANDIDATES",
    "write_json_atomic",
]
