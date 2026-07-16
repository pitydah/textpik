"""Action schema migration, transformations and explicit permissions."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from .models import ActionOperation, ActionResultType
from .storage import read_json, write_json_atomic

TRANSFORMS = {"uppercase", "lowercase", "capitalize", "remove-breaks"}
KNOWN_PERMISSIONS = {"clipboard", "network", "process", "filesystem", "accessibility"}


def fuzzy_score(query: str, candidate: str) -> int | None:
    """Rank compact action queries while tolerating missing characters."""
    def fold(value):
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

    needle = " ".join(fold(query).split())
    haystack = fold(candidate)
    if not needle:
        return 0
    if needle in haystack:
        return haystack.index(needle) - 1000
    position = -1
    gaps = 0
    for char in needle:
        next_position = haystack.find(char, position + 1)
        if next_position < 0:
            return None
        if position >= 0:
            gaps += next_position - position - 1
        position = next_position
    return gaps + position


def infer_category(name: str, command: str) -> str:
    lowered = f"{name} {command}".casefold()
    if command in {"copy", "paste", "klipper-save", "klipper-menu"}:
        return "Portapapeles"
    if command in TRANSFORMS or command in {"count", "spellcheck"} or "diccionario" in lowered:
        return "Texto"
    if command in {"terminal", "print"}:
        return "Sistema"
    if command == "kdeconnect":
        return "Compartir"
    if command == "ollama" or any(name in lowered for name in ("chatgpt", "deepseek")):
        return "IA"
    if "http" in command or "buscar" in lowered or "search" in lowered:
        return "Buscar"
    return "General"


def stable_action_id(name: str, command: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "action"
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def migrate_action(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name, icon, command = raw.get("name"), raw.get("icon"), raw.get("cmd")
    if not all(isinstance(value, str) and value.strip() for value in (name, icon, command)):
        return None
    operation = raw.get("operation")
    if operation is None:
        operation = "transform" if command in TRANSFORMS else "command"
    result = raw.get("result")
    if result is None:
        result = "replace-selection" if command in TRANSFORMS else "none"
    try:
        ActionOperation(operation)
        ActionResultType(result)
    except ValueError:
        return None
    contexts = raw.get("context", raw.get("contexts", []))
    contexts = contexts if isinstance(contexts, list) else []
    permissions = raw.get("permissions", [])
    if not isinstance(permissions, list) or any(p not in KNOWN_PERMISSIONS for p in permissions):
        return None
    variants = raw.get("variants", {})
    if not isinstance(variants, dict) or any(
        key not in {"shift", "control", "alt", "control+alt", "control+shift", "alt+shift"}
        or not isinstance(value, str) or not value.strip()
        for key, value in variants.items()
    ):
        return None
    return {
        "id": raw.get("id") or stable_action_id(name, command),
        "name": name.strip(),
        "icon": icon.strip(),
        "cmd": command.strip(),
        "operation": operation,
        "result": result,
        "enabled": bool(raw.get("enabled", True)),
        "context": [value for value in contexts if isinstance(value, str)],
        "permissions": permissions,
        "category": str(raw.get("category") or infer_category(name, command)),
        "variants": dict(variants),
    }


def transform_text(command: str, text: str) -> str:
    if command == "uppercase":
        return text.upper()
    if command == "lowercase":
        return text.lower()
    if command == "remove-breaks":
        return re.sub(r" +", " ", text.replace("\n", " ").replace("\r", " ")).strip()
    if command == "capitalize":
        capitalize_next, output = True, []
        for char in text:
            if capitalize_next and char.isalpha():
                char, capitalize_next = char.upper(), False
            output.append(char)
            if char in ".!?":
                capitalize_next = True
        return "".join(output)
    raise ValueError(f"Unknown transform: {command}")


class PermissionStore:
    def __init__(self, path: Path):
        self.path = path
        self._grants: dict[str, list[str]] = {}
        try:
            payload = read_json(path)
            if isinstance(payload, dict):
                self._grants = payload
        except (OSError, ValueError):
            pass

    def allows(self, action_id: str, permission: str) -> bool:
        return permission in self._grants.get(action_id, [])

    def grant(self, action_id: str, permission: str) -> None:
        if permission not in KNOWN_PERMISSIONS:
            raise ValueError(permission)
        values = set(self._grants.get(action_id, []))
        if permission in values:
            return
        values.add(permission)
        self._grants[action_id] = sorted(values)
        write_json_atomic(self.path, self._grants)
