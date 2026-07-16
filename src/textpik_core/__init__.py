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
from .performance import (
    MetricSnapshot,
    PerformanceTracker,
    ProcessResources,
    read_process_resources,
)
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
from .automation import (
    AUTOMATION_TEMPLATES,
    AutomationPreview,
    automation_matches,
    automation_template,
    preview_automation,
)
from .grammar import GrammarSuggestion, LanguageToolService, apply_suggestions
from .history import HistoryEntry, HistoryStore
from .insights import InlineInsight, local_insight, safe_calculate, text_statistics
from .ranking import LocalActionRanker
from .undo import UndoManager, UndoRecord
from .providers import OllamaProvider, ProviderResponse, TesseractProvider
from .wasi import run_wasi
from .health import CrashSentinel, PreviousRun
from .portal import (
    capture_xdg_screenshot,
    portal_file_path,
    portal_request_path,
    portal_supports_area,
)
from .interaction import PopupComposition, plan_popup_composition, resolve_action_command
from .utilities import (
    clean_terminal_text,
    color_details,
    compare_text,
    extract_entities,
    format_json,
    slugify,
)
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
    "ProcessResources",
    "read_process_resources",
    "PopupAnchor",
    "SelectionContext",
    "SpellingResult",
    "SpellingService",
    "AutomationPreview",
    "AUTOMATION_TEMPLATES",
    "automation_matches",
    "automation_template",
    "preview_automation",
    "GrammarSuggestion",
    "LanguageToolService",
    "apply_suggestions",
    "HistoryEntry",
    "HistoryStore",
    "InlineInsight",
    "local_insight",
    "safe_calculate",
    "text_statistics",
    "LocalActionRanker",
    "UndoManager",
    "UndoRecord",
    "OllamaProvider",
    "ProviderResponse",
    "TesseractProvider",
    "run_wasi",
    "CrashSentinel",
    "PreviousRun",
    "capture_xdg_screenshot",
    "portal_file_path",
    "portal_request_path",
    "portal_supports_area",
    "PopupComposition",
    "plan_popup_composition",
    "resolve_action_command",
    "clean_terminal_text",
    "color_details",
    "compare_text",
    "extract_entities",
    "format_json",
    "slugify",
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
