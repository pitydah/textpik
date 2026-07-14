"""Small, content-free context profile rules for action planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .planning import ContextSnapshot


@dataclass(frozen=True, slots=True)
class ContextProfile:
    name: str
    application: str
    text_types: frozenset[str]
    action_ids: frozenset[str]

    def matches(self, snapshot: ContextSnapshot) -> bool:
        application_matches = (
            not self.application
            or self.application.casefold() in snapshot.application.casefold()
        )
        type_matches = not self.text_types or bool(
            self.text_types.intersection(snapshot.text_types)
        )
        return application_matches and type_matches


def normalize_profiles(raw_profiles) -> list[dict]:
    """Validate persisted profiles and discard ambiguous empty rules."""
    if not isinstance(raw_profiles, list):
        return []
    normalized = []
    for raw in raw_profiles[:32]:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name", "")).strip()[:64]
        application = str(raw.get("application", "")).strip()[:128]
        text_types = _unique_strings(raw.get("text_types", ()), 12)
        action_ids = _unique_strings(raw.get("action_ids", ()), 64)
        if not name or not action_ids or (not application and not text_types):
            continue
        normalized.append(
            {
                "name": name,
                "application": application,
                "text_types": text_types,
                "action_ids": action_ids,
            }
        )
    return normalized


def resolve_profile(
    profiles: Iterable[Mapping], snapshot: ContextSnapshot
) -> ContextProfile | None:
    """Return the first matching profile, preserving explicit user priority."""
    for raw in normalize_profiles(list(profiles)):
        profile = ContextProfile(
            raw["name"],
            raw["application"],
            frozenset(raw["text_types"]),
            frozenset(raw["action_ids"]),
        )
        if profile.matches(snapshot):
            return profile
    return None


def _unique_strings(values, maximum: int) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    output = []
    for value in values:
        value = str(value).strip()
        if value and value not in output:
            output.append(value)
        if len(output) >= maximum:
            break
    return output
