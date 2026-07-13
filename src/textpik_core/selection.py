"""Selection policy independent from Qt and desktop-specific APIs."""

from __future__ import annotations

from .models import SelectionContext

FILE_MANAGERS = ("dolphin", "nautilus", "nemo", "thunar", "pcmanfm", "caja")
TEXT_ROLES = ("text", "entry", "paragraph", "document", "terminal")
FILE_ROLES = ("icon", "list item", "tree item", "table cell")


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
