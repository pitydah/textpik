"""Selection policy independent from Qt and desktop-specific APIs."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SelectionContext

FILE_MANAGERS = ("dolphin", "nautilus", "nemo", "thunar", "pcmanfm", "caja")
TEXT_ROLES = ("text", "entry", "paragraph", "document", "terminal")
FILE_ROLES = ("icon", "list item", "tree item", "table cell")
NON_TEXT_ROLES = (
    "menu",
    "menu item",
    "push button",
    "check box",
    "radio button",
    "tool bar",
    "status bar",
)


@dataclass(frozen=True, slots=True)
class SelectionIntent:
    allowed: bool
    reason: str = ""
    confidence: float = 0.0


def adaptive_selection_delay(
    context: SelectionContext,
    text: str,
    *,
    base_ms: int = 70,
    recent_changes: int = 1,
) -> int:
    """Return a small stabilization delay using metadata, never selected content."""
    delay = max(30, min(250, int(base_ms)))
    changes = max(1, min(5, int(recent_changes)))
    delay += (changes - 1) * 18
    app = context.application.casefold()
    role = context.role.casefold()
    if any(name in app for name in FILE_MANAGERS):
        delay += 45
    if "terminal" in role or "terminal" in app:
        delay += 20
    if context.editable and any(name in role for name in TEXT_ROLES):
        delay -= 15
    length = len(str(text or ""))
    if length == 1:
        delay += 35
    elif length <= 64 and not any(char.isspace() for char in str(text).strip()):
        # Browsers commonly select the word below a secondary click before
        # exposing their context menu. A short grace lets focus metadata settle.
        delay += 55
    elif length > 2000:
        delay += 25
    return max(30, min(250, delay))


def is_file_workspace_selection(context: SelectionContext, text: str) -> bool:
    """Reject file objects while still allowing text fields in file managers."""
    lowered = text.strip().lower()
    if lowered.startswith("file://") or "\nfile://" in lowered:
        return True
    app = context.application.casefold()
    role = context.role.casefold()
    is_file_manager = any(name in app for name in FILE_MANAGERS)
    explicitly_textual = any(name in role for name in TEXT_ROLES)
    file_object = any(name in role for name in FILE_ROLES)
    return is_file_manager and file_object and not explicitly_textual


def evaluate_selection_intent(
    context: SelectionContext,
    text: str,
    *,
    ignore_files: bool = True,
    reject_sensitive: bool = True,
) -> SelectionIntent:
    """Decide whether a selection represents intentional, actionable text."""
    value = str(text or "").strip()
    if not value:
        return SelectionIntent(False, "empty", 0.0)
    if reject_sensitive and context.sensitive:
        return SelectionIntent(False, "sensitive", 0.0)

    application = context.application.casefold()
    role = context.role.casefold()
    if "textpik" in application:
        return SelectionIntent(False, "self", 0.0)
    if any(token in role for token in NON_TEXT_ROLES):
        return SelectionIntent(False, "non-text-control", 0.0)
    if ignore_files and is_file_workspace_selection(context, value):
        return SelectionIntent(False, "file-selection", 0.0)
    if context.selection_start is not None and context.selection_end is not None:
        if context.selection_start == context.selection_end:
            return SelectionIntent(False, "collapsed-selection", 0.0)

    confidence = 0.66
    if context.application:
        confidence += 0.05
    if any(token in role for token in TEXT_ROLES):
        confidence += 0.08
    elif role:
        confidence += 0.02
    if context.editable:
        confidence += 0.05
    if context.selection_rect:
        confidence += 0.08
    if context.anchor is not None:
        confidence += 0.05
    if context.backend == "atspi":
        confidence += 0.03
    if len(value) == 1:
        confidence -= 0.14
    elif len(value) <= 80:
        confidence += 0.02
    elif len(value) > 2000:
        confidence -= 0.08
    return SelectionIntent(True, confidence=min(1.0, max(0.0, confidence)))
