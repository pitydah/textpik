"""Pure action planning contracts for the popup hot path."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .models import SelectionContext


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable, content-minimal context consumed by action planners."""

    application: str = ""
    role: str = ""
    editable: bool = False
    sensitive: bool = False
    selection_rect: tuple[int, int, int, int] | None = None
    text_types: frozenset[str] = frozenset()
    clipboard_has_text: bool = False
    multiline: bool = False
    undo_available: bool = False

    @classmethod
    def from_selection(
        cls,
        context: SelectionContext,
        *,
        text_types: Iterable[str] = (),
        clipboard_has_text: bool = False,
        multiline: bool = False,
        undo_available: bool = False,
    ) -> ContextSnapshot:
        return cls(
            application=context.application,
            role=context.role,
            editable=context.editable,
            sensitive=context.sensitive,
            selection_rect=context.selection_rect,
            text_types=frozenset(text_types),
            clipboard_has_text=clipboard_has_text,
            multiline=multiline,
            undo_available=undo_available,
        )


def plan_actions(
    actions: Iterable[Mapping],
    snapshot: ContextSnapshot,
    *,
    context_aware: bool = True,
    is_available: Callable[[Mapping], bool] | None = None,
    allowed_action_ids: frozenset[str] | None = None,
) -> list[Mapping]:
    """Filter actions while preserving the exact order chosen by the user."""
    available = is_available or (lambda _action: True)
    planned = []
    for action in actions:
        action_id = action.get("id", action.get("cmd", ""))
        pinned = bool(action.get("pinned", False))
        if (
            allowed_action_ids is not None
            and action_id not in allowed_action_ids
            and not pinned
        ):
            continue
        if not action.get("enabled", True) or not available(action):
            continue
        if action.get("cmd") == "paste" and (
            not snapshot.clipboard_has_text or not snapshot.editable
        ):
            continue
        if action.get("requires_clipboard", False) and not snapshot.clipboard_has_text:
            continue
        if action.get("cmd") == "undo" and not snapshot.undo_available:
            continue
        if action.get("requires_editable", False) and not snapshot.editable:
            continue
        if action.get("requires_multiline", False) and not snapshot.multiline:
            continue
        contexts = action.get("context", ())
        if (
            context_aware
            and not pinned
            and snapshot.text_types
            and contexts
            and not any(value in snapshot.text_types for value in contexts)
        ):
            continue
        planned.append(action)
    return planned


def order_actions_for_popup(
    actions: Iterable[Mapping], snapshot: ContextSnapshot
) -> list[Mapping]:
    """Compatibility boundary that now guarantees the user's exact order."""
    del snapshot
    return list(actions)
