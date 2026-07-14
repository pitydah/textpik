"""Local, manifest-only extension discovery with path confinement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .actions import migrate_action
from .storage import read_json

SAFE_BUILTINS = {
    "copy",
    "paste",
    "uppercase",
    "lowercase",
    "capitalize",
    "remove-breaks",
    "count",
}
MAX_EXTENSION_MANIFESTS = 64
MAX_MANIFEST_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ExtensionIssue:
    extension: str
    reason: str


def load_local_extensions(directory: Path) -> list[dict]:
    """Compatibility wrapper returning only accepted declarative actions."""
    actions, _issues = inspect_local_extensions(directory)
    return actions


def inspect_local_extensions(
    directory: Path,
) -> tuple[list[dict], list[ExtensionIssue]]:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        return [], []
    actions = []
    issues = []
    seen_ids = set()
    manifests = sorted(directory.glob("*/manifest.json"))
    if len(manifests) > MAX_EXTENSION_MANIFESTS:
        issues.append(ExtensionIssue("*", "extension-limit"))
    for manifest in manifests[:MAX_EXTENSION_MANIFESTS]:
        extension = manifest.parent.name
        try:
            resolved = manifest.resolve()
            if directory not in resolved.parents:
                issues.append(ExtensionIssue(extension, "path-outside-root"))
                continue
            if resolved.stat().st_size > MAX_MANIFEST_BYTES:
                issues.append(ExtensionIssue(extension, "manifest-too-large"))
                continue
            payload = read_json(resolved)
            if payload.get("schema_version") != 1:
                issues.append(ExtensionIssue(extension, "unsupported-schema"))
                continue
            action = migrate_action(payload.get("action"))
            if not action:
                issues.append(ExtensionIssue(extension, "invalid-action"))
                continue
            if (
                action["cmd"] not in SAFE_BUILTINS
                and "process" not in action["permissions"]
            ):
                issues.append(ExtensionIssue(extension, "missing-process-permission"))
                continue
            if action["id"] in seen_ids:
                issues.append(ExtensionIssue(extension, "duplicate-action-id"))
                continue
            seen_ids.add(action["id"])
            action["extension"] = extension
            actions.append(action)
        except (OSError, ValueError, AttributeError):
            issues.append(ExtensionIssue(extension, "unreadable-manifest"))
    return actions, issues
