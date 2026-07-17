"""Pure popup composition and action-modifier policies."""

from __future__ import annotations

from dataclasses import dataclass


MODIFIER_ORDER = ("control", "alt", "shift")
MAX_POPUP_ROWS = 2


@dataclass(frozen=True, slots=True)
class PopupComposition:
    direct_count: int
    rows: int
    columns: int
    overflow_count: int


def modifier_key(*, shift: bool = False, control: bool = False, alt: bool = False) -> str:
    active = {"shift": shift, "control": control, "alt": alt}
    return "+".join(name for name in MODIFIER_ORDER if active[name])


def resolve_action_command(action: dict, modifier: str = "") -> str:
    """Resolve an optional action variant without changing its stable identity."""
    command = str(action.get("cmd", ""))
    variants = action.get("variants", {})
    if not modifier or not isinstance(variants, dict):
        return command
    candidate = variants.get(modifier)
    return str(candidate) if isinstance(candidate, str) and candidate.strip() else command


def plan_popup_composition(
    action_count: int,
    *,
    requested: int,
    row_capacity: int,
    compact_limit: int | None = None,
    allow_two_rows: bool = True,
    catalog_count: int | None = None,
) -> PopupComposition:
    """Bound the direct bar while reserving overflow for the full catalog."""
    action_count = max(0, int(action_count))
    total_count = action_count
    if catalog_count is not None:
        total_count = max(action_count, int(catalog_count))
    row_capacity = max(3, int(row_capacity))
    direct_target = min(action_count, max(3, int(requested)))
    if compact_limit is not None:
        direct_target = min(direct_target, max(3, int(compact_limit)))
    maximum_rows = MAX_POPUP_ROWS if allow_two_rows else 1
    direct_count = min(direct_target, row_capacity * maximum_rows)
    overflow = max(0, total_count - direct_count)
    if overflow and direct_count >= row_capacity * maximum_rows:
        direct_count = max(3, direct_count - 1)
        overflow = total_count - direct_count
    total_slots = direct_count + (1 if overflow else 0)
    rows = 1 if total_slots <= row_capacity else 2
    columns = min(row_capacity, max(1, total_slots))
    return PopupComposition(direct_count, rows, columns, overflow)
