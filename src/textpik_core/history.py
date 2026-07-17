"""Optional bounded text history; disabled unless explicitly constructed by UI."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import time

from .storage import read_json, write_json_atomic


SENSITIVE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:\d[ -]*?){13,19}\b|\b(?:password|contraseña|token|secret)\s*[:=])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    text: str
    created_at: float
    application: str = ""
    favorite: bool = False


class HistoryStore:
    def __init__(self, path: Path, *, maximum: int = 100, max_age_days: int = 30, key: bytes | None = None):
        self.path = path
        self.maximum = max(1, min(1000, maximum))
        self.max_age = max(1, min(3650, max_age_days)) * 86400
        self.key = key

    @staticmethod
    def sensitive(text: str) -> bool:
        return bool(SENSITIVE.search(text))

    def _cipher(self):
        if self.key is None:
            return None
        from cryptography.fernet import Fernet

        return Fernet(base64.urlsafe_b64encode(sha256(self.key).digest()))

    def load(self) -> list[HistoryEntry]:
        if not self.path.exists():
            return []
        try:
            payload = read_json(self.path)
            if not isinstance(payload, dict):
                return []
            if payload.get("encrypted"):
                cipher = self._cipher()
                if cipher is None:
                    return []
                import json

                payload = json.loads(cipher.decrypt(str(payload["payload"]).encode()))
                if not isinstance(payload, dict):
                    return []
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            return []
        cutoff = time() - self.max_age
        entries = []
        for item in payload.get("entries", [])[: self.maximum]:
            try:
                created_at = float(item["created_at"])
                if created_at >= cutoff:
                    entries.append(HistoryEntry(
                        str(item["text"]), created_at,
                        str(item.get("application", "")), bool(item.get("favorite")),
                    ))
            except (KeyError, TypeError, ValueError):
                continue
        return entries

    def save(self, entries) -> None:
        payload = {"entries": [entry.__dict__ if hasattr(entry, "__dict__") else {
            "text": entry.text, "created_at": entry.created_at, "application": entry.application, "favorite": entry.favorite
        } for entry in list(entries)[: self.maximum]]}
        cipher = self._cipher()
        if cipher:
            import json

            token = cipher.encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()
            payload = {"encrypted": True, "payload": token}
        write_json_atomic(self.path, payload)

    def add(self, text: str, application: str = "", excluded_apps=()) -> bool:
        value = text.strip()
        if not value or self.sensitive(value) or any(name.casefold() in application.casefold() for name in excluded_apps):
            return False
        entries = [entry for entry in self.load() if entry.text != value]
        entries.insert(0, HistoryEntry(value, time(), application))
        self.save(entries)
        return True
