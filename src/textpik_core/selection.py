"""Selection policy independent from Qt and desktop-specific APIs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


class SelectionKind(str, Enum):
    """What the user actually highlighted, not what the string looks like."""

    TEXT = "text"
    FILE_OBJECT = "file-object"
    NON_TEXT_CONTROL = "non-text-control"
    SENSITIVE = "sensitive"
    UNKNOWN = "unknown"


# Formats a file manager offers when the selection is a file rather than text.
# text/uri-list is the strong one: it is what desktops use to publish dropped or
# copied file objects, and KDE ships it alongside text/plain for the same
# selection.
URI_LIST_FORMATS = ("text/uri-list", "application/x-kde4-urilist")
FILE_OBJECT_FORMATS = URI_LIST_FORMATS + (
    "application/x-kde-cutselection",
    "application/x-qabstractitemmodeldatalist",
)


@dataclass(frozen=True, slots=True)
class SelectionMimeEvidence:
    """MIME flavours offered by the selection, captured at read time.

    This exists because the selected string cannot decide what was selected: a
    path inside an editor is text, and the same path copied from Dolphin is a
    file object. The clipboard says which, and it says it immediately, before
    AT-SPI has described the node.
    """

    has_text: bool = False
    has_urls: bool = False
    formats: tuple[str, ...] = ()
    local_file_urls: bool = False

    @property
    def is_file_object(self) -> bool:
        if self.has_urls:
            return True
        return any(
            fmt.casefold() in FILE_OBJECT_FORMATS for fmt in self.formats
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "has_text": self.has_text,
            "has_urls": self.has_urls,
            "formats": list(self.formats),
            "local_file_urls": self.local_file_urls,
            "file_object": self.is_file_object,
        }


@dataclass(frozen=True, slots=True)
class SelectionIntent:
    allowed: bool
    reason: str = ""
    confidence: float = 0.0
    kind: SelectionKind = SelectionKind.UNKNOWN


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


def classify_selection(
    context: SelectionContext,
    text: str,
    mime: SelectionMimeEvidence | None = None,
) -> SelectionKind:
    """Classify what was selected, before deciding whether to show anything.

    The order encodes the authority of each piece of evidence. MIME comes first
    because it is the only source that distinguishes a file object from text
    that looks like a path, and it arrives with the selection itself. AT-SPI
    then separates a text field inside a file manager from the file grid, which
    MIME cannot do on its own. The string is deliberately never inspected: a
    path selected in an editor must keep working.
    """
    if context.sensitive:
        return SelectionKind.SENSITIVE

    role = context.role.casefold()
    if any(token in role for token in NON_TEXT_ROLES):
        return SelectionKind.NON_TEXT_CONTROL

    if mime is not None and mime.is_file_object:
        return SelectionKind.FILE_OBJECT

    application = context.application.casefold()
    if any(name in application for name in FILE_MANAGERS):
        # Inside a file manager the node decides: the icon grid is a file, the
        # rename and search fields are text.
        if any(token in role for token in TEXT_ROLES):
            return SelectionKind.TEXT
        if any(token in role for token in FILE_ROLES):
            return SelectionKind.FILE_OBJECT
        if mime is not None and not mime.is_file_object:
            # The clipboard published only text flavours, so this is not a file
            # object even though the node has not been described yet. This is
            # what keeps the rename and search fields working when AT-SPI is
            # slower than the clipboard.
            return SelectionKind.TEXT
        if not role:
            # No node description and nothing but a bare string: in a file
            # manager that string is the selected item's name.
            return SelectionKind.FILE_OBJECT
        return SelectionKind.UNKNOWN

    if any(token in role for token in TEXT_ROLES):
        return SelectionKind.TEXT
    if not role:
        return SelectionKind.UNKNOWN
    return SelectionKind.TEXT


def evaluate_selection_intent(
    context: SelectionContext,
    text: str,
    *,
    ignore_files: bool = True,
    reject_sensitive: bool = True,
    mime: SelectionMimeEvidence | None = None,
) -> SelectionIntent:
    """Decide whether a selection represents intentional, actionable text."""
    value = str(text or "").strip()
    if not value:
        return SelectionIntent(False, "empty", 0.0, SelectionKind.UNKNOWN)
    if reject_sensitive and context.sensitive:
        return SelectionIntent(False, "sensitive", 0.0, SelectionKind.SENSITIVE)

    application = context.application.casefold()
    role = context.role.casefold()
    if "textpik" in application:
        return SelectionIntent(False, "self", 0.0, SelectionKind.UNKNOWN)
    if any(token in role for token in NON_TEXT_ROLES):
        return SelectionIntent(
            False, "non-text-control", 0.0, SelectionKind.NON_TEXT_CONTROL
        )

    kind = classify_selection(context, value, mime)
    if kind is SelectionKind.SENSITIVE:
        return SelectionIntent(False, "sensitive", 0.0, kind)
    if ignore_files and kind is SelectionKind.FILE_OBJECT:
        return SelectionIntent(False, "file-selection", 0.0, kind)
    if kind is SelectionKind.NON_TEXT_CONTROL:
        return SelectionIntent(False, "non-text-control", 0.0, kind)
    if context.selection_start is not None and context.selection_end is not None:
        if context.selection_start == context.selection_end:
            return SelectionIntent(False, "collapsed-selection", 0.0, kind)

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
    return SelectionIntent(
        True, confidence=min(1.0, max(0.0, confidence)), kind=kind
    )
