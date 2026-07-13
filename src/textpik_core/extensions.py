"""Local, manifest-only extension discovery with path confinement."""

from __future__ import annotations

import json
from pathlib import Path

from .actions import migrate_action

SAFE_BUILTINS = {
    "copy",
    "paste",
    "uppercase",
    "lowercase",
    "capitalize",
    "remove-breaks",
    "count",
}


def load_local_extensions(directory: Path) -> list[dict]:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        return []
    actions = []
    for manifest in sorted(directory.glob("*/manifest.json")):
        try:
            resolved = manifest.resolve()
            if directory not in resolved.parents:
                continue
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                continue
            action = migrate_action(payload.get("action"))
            if action:
                if (
                    action["cmd"] not in SAFE_BUILTINS
                    and "process" not in action["permissions"]
                ):
                    continue
                action["extension"] = resolved.parent.name
                actions.append(action)
        except (OSError, ValueError, AttributeError):
            continue
    return actions
