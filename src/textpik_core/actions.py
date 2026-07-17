"""Action schema migration, transformations and explicit permissions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote

from .models import ActionOperation, ActionResultType
from .storage import read_json, write_json_atomic

TRANSFORMS = {
    "uppercase", "lowercase", "capitalize", "remove-breaks", "trim",
    "normalize-spaces", "title-case", "quote-text", "bullet-list",
    "sort-lines", "unique-lines", "url-encode", "url-decode",
    "base64-encode", "base64-decode", "html-escape", "html-unescape",
}
KNOWN_PERMISSIONS = {"clipboard", "network", "process", "filesystem", "accessibility"}
DEFAULT_PRIORITIES = {
    "copy": 100, "cut": 98, "paste": 96, "open-url": 92,
    "trim": 86, "normalize-spaces": 84, "capitalize": 80,
    "title-case": 78, "quote-text": 76, "bullet-list": 74,
    "sort-lines": 72, "unique-lines": 70,
}
PALETTE_COMMANDS = {
    "print", "terminal", "ollama", "textpik-history", "ocr-image",
    "ocr-region", "klipper-menu", "speak",
}
BAR_COMMANDS = {"copy", "cut", "paste"}

BUILTIN_ICON_UPGRADES = {
    "count": ("counter.svg", "count-words.svg"),
    "insight": ("counter.svg", "calculator.svg"),
    "grammar": ("spellcheck.svg", "grammar.svg"),
    "undo": ("paste.svg", "undo.svg"),
    "textpik-history": ("klipper-history.svg", "history.svg"),
    "ocr-image": ("dictionary.svg", "ocr-image.svg"),
    "ocr-region": ("dictionary.svg", "ocr-region.svg"),
    "format-json": ("capitalize.svg", "json.svg"),
    "extract-entities": ("counter.svg", "extract-entities.svg"),
    "color-details": ("counter.svg", "color-picker.svg"),
    "slugify": ("remove-breaks.svg", "slug.svg"),
    "clean-terminal": ("terminal.svg", "terminal-clean.svg"),
    "compare-clipboard": ("counter.svg", "compare.svg"),
    "speak": ("dictionary.svg", "speak.svg"),
}

BUILTIN_CONTEXT_UPGRADES = {
    "insight": (("number", "currency", "text"), ("number", "currency")),
    "terminal": (
        ("text", "code", "ip", "number"),
        ("code", "ip", "number", "path", "error"),
    ),
    "clean-terminal": (("error", "code", "text"), ("error", "code")),
    "xdg-open 'https://www.google.com/maps?q={url}'": (
        ("text",),
        ("text", "coordinates"),
    ),
    "xdg-open 'https://dle.rae.es/{url}'": ((), ("word",)),
    "open-media-player": (("url",), ("url", "stream-url")),
}

BUILTIN_NAME_UPGRADES = {
    "uppercase": (("MAYUSCULAS", "MAYÚSCULAS", "Mayúsculas"), "Convertir a mayúsculas"),
    "lowercase": (("minusculas", "MINÚSCULAS", "Minúsculas"), "Convertir a minúsculas"),
    "capitalize": (("Tipo oración", "Capitalizar"), "Capitalizar oraciones"),
    "remove-breaks": (("Quitar saltos",), "Unir líneas limpiamente"),
    "quote-text": (("Entre comillas",), "Añadir comillas tipográficas"),
    "bullet-list": (("Crear lista",), "Crear lista con viñetas"),
    "count": (("Contar palabras",), "Contar texto"),
}


def upgrade_builtin_action_metadata(actions: list[dict]) -> bool:
    """Upgrade only untouched legacy metadata, preserving user customization."""
    changed = False
    for action in actions:
        command = action.get("cmd")
        icon_upgrade = BUILTIN_ICON_UPGRADES.get(command)
        if icon_upgrade and action.get("icon") == icon_upgrade[0]:
            action["icon"] = icon_upgrade[1]
            changed = True
        context_upgrade = BUILTIN_CONTEXT_UPGRADES.get(command)
        if context_upgrade and tuple(action.get("context", ())) == context_upgrade[0]:
            action["context"] = list(context_upgrade[1])
            changed = True
        name_upgrade = BUILTIN_NAME_UPGRADES.get(command)
        if name_upgrade and action.get("name") in name_upgrade[0]:
            action["name"] = name_upgrade[1]
            changed = True
        if command == "compare-clipboard" and not action.get("requires_clipboard"):
            action["requires_clipboard"] = True
            changed = True
    return changed


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
    if command in {"copy", "cut", "paste", "klipper-save", "klipper-menu"}:
        return "Portapapeles"
    if command in TRANSFORMS or command in {
        "count", "spellcheck", "grammar", "format-json", "extract-entities",
        "slugify", "compare-clipboard",
    } or "diccionario" in lowered:
        return "Texto"
    if command in {"terminal", "print", "ocr-image", "ocr-region", "speak"}:
        return "Sistema"
    if command in {"insight", "color-details"}:
        return "Utilidades"
    if command in {"undo", "textpik-history"}:
        return "Portapapeles"
    if command == "kdeconnect":
        return "Compartir"
    if command in {"open-magnet", "send-magnet"}:
        return "Descargas"
    if command == "open-media-player":
        return "Multimedia"
    if command == "ollama" or any(
        name in lowered for name in ("chatgpt", "deepseek", "claude", "gemini")
    ):
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
    if command in PALETTE_COMMANDS:
        default_placement = "palette"
    elif command in BAR_COMMANDS:
        default_placement = "bar"
    else:
        default_placement = "contextual"
    placement = str(raw.get("placement", default_placement))
    if placement not in {"bar", "contextual", "palette"}:
        placement = "contextual"
    try:
        priority = max(
            -100, min(100, int(raw.get("priority", DEFAULT_PRIORITIES.get(command, 0))))
        )
    except (TypeError, ValueError):
        priority = 0
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
        "requires_editable": bool(raw.get("requires_editable", False)),
        "requires_multiline": bool(raw.get("requires_multiline", False)),
        "requires_clipboard": bool(raw.get("requires_clipboard", False)),
        "placement": placement,
        "priority": priority,
        "pinned": bool(raw.get("pinned", False)),
    }


def transform_text(command: str, text: str) -> str:
    if command == "uppercase":
        return text.upper()
    if command == "lowercase":
        return text.lower()
    if command == "remove-breaks":
        value = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
        joined = ""
        for raw_line in value.split("\n"):
            line = re.sub(r"[^\S\r\n]+", " ", raw_line).strip()
            if not line:
                continue
            if (
                joined.endswith("-")
                and len(joined) >= 2
                and joined[-2].isalpha()
                and line[0].islower()
            ):
                joined = joined[:-1] + line
            else:
                joined = f"{joined} {line}".strip()
        joined = re.sub(r"\s+([,.;:!?%\)\]\}»”])", r"\1", joined)
        return re.sub(r"([¿¡\(\[\{«“])\s+", r"\1", joined).strip()
    if command == "capitalize":
        capitalize_next, output = True, []
        for char in text.lower():
            if capitalize_next and char.isalpha():
                char, capitalize_next = char.upper(), False
            elif capitalize_next and char.isdigit():
                capitalize_next = False
            output.append(char)
            if char in ".!?…\n":
                capitalize_next = True
        return "".join(output)
    if command == "trim":
        return text.strip()
    if command == "normalize-spaces":
        lines = [re.sub(r"[^\S\r\n]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(lines).strip()
    if command == "title-case":
        return text.title()
    if command == "quote-text":
        value = text.strip()
        if not value:
            return ""
        if value.startswith("“") and value.endswith("”"):
            return value
        for opening, closing in (("«", "»"), ('"', '"'), ("‘", "’"), ("'", "'")):
            if len(value) >= 2 and value.startswith(opening) and value.endswith(closing):
                value = value[len(opening) : -len(closing)].strip()
                break
        return f"“{value}”"
    if command == "bullet-list":
        marker = re.compile(
            r"^(?P<indent>[ \t]*)(?:(?:[•●◦▪‣*+\-–—])|(?:\d{1,4}[.)])|(?:[A-Za-z][.)]))[ \t]+"
        )
        output = []
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            match = marker.match(raw_line)
            indent = match.group("indent") if match else raw_line[: len(raw_line) - len(raw_line.lstrip())]
            content = raw_line[match.end() :] if match else raw_line.strip()
            content = content.strip()
            if content:
                output.append(f"{indent}• {content}")
        return "\n".join(output)
    if command == "sort-lines":
        return "\n".join(sorted(text.splitlines(), key=str.casefold))
    if command == "unique-lines":
        return "\n".join(dict.fromkeys(text.splitlines()))
    if command == "url-encode":
        return quote(text, safe="")
    if command == "url-decode":
        return unquote(text)
    if command == "base64-encode":
        return base64.b64encode(text.encode("utf-8")).decode("ascii")
    if command == "base64-decode":
        try:
            return base64.b64decode(text.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("El texto no es Base64 UTF-8 válido") from exc
    if command == "html-escape":
        return html.escape(text, quote=True)
    if command == "html-unescape":
        return html.unescape(text)
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
