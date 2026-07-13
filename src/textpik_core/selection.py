"""Selection policy independent from Qt and desktop-specific APIs."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SelectionContext

FILE_MANAGERS = ("dolphin", "nautilus", "nemo", "thunar", "pcmanfm", "caja")
TEXT_ROLES = ("text", "entry", "paragraph", "document", "terminal")
FILE_ROLES = ("icon", "list item", "tree item", "table cell")
NON_TEXT_ROLES = (
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
        return SelectionIntent(False, "empty")
    if reject_sensitive and context.sensitive:
        return SelectionIntent(False, "sensitive")

    application = context.application.casefold()
    role = context.role.casefold()
    if "textpik" in application:
        return SelectionIntent(False, "self")
    if any(token in role for token in NON_TEXT_ROLES):
        return SelectionIntent(False, "non-text-control")
    if ignore_files and is_file_workspace_selection(context, value):
        return SelectionIntent(False, "file-selection")
    return SelectionIntent(True)
