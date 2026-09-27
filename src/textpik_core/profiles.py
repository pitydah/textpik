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
    action_ids: tuple[str, ...]
    mode: str = "custom"
    applications: tuple[str, ...] = ()

    def matches(self, snapshot: ContextSnapshot) -> bool:
        application_rules = self.applications or ((self.application,) if self.application else ())
        application_matches = any(
            value.casefold() in snapshot.application.casefold()
            for value in application_rules
        )
        type_matches = bool(
            self.text_types.intersection(snapshot.text_types)
        )
        if self.mode == "developer":
            return application_matches or type_matches
        return (
            (not application_rules or application_matches)
            and (not self.text_types or type_matches)
        )


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
        applications = _unique_strings(raw.get("applications", ()), 24)
        if application and application not in applications:
            applications.insert(0, application)
        text_types = _unique_strings(raw.get("text_types", ()), 12)
        action_ids = _unique_strings(raw.get("action_ids", ()), 64)
        mode = "developer" if raw.get("mode") == "developer" else "custom"
        if not name or not action_ids or (not applications and not text_types):
            continue
        normalized.append(
            {
                "name": name,
                "application": application,
                "applications": applications,
                "text_types": text_types,
                "action_ids": action_ids,
                "mode": mode,
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
            tuple(raw["action_ids"]),
            raw["mode"],
            tuple(raw["applications"]),
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
