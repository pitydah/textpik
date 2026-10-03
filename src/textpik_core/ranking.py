"""Content-free local action ranking with bounded frequency and recency data."""

from __future__ import annotations

from dataclasses import dataclass
from time import time


@dataclass(slots=True)
class Usage:
    count: int = 0
    last_used: float = 0.0


class LocalActionRanker:
    """Suggest actions without ever accepting or persisting selected text."""

    def __init__(self, raw: dict | None = None, maximum: int = 256):
        self.maximum = max(16, min(1024, maximum))
        self._usage: dict[str, Usage] = {}
        for key, value in (raw or {}).items():
            if not isinstance(value, dict) or len(self._usage) >= self.maximum:
                break
            try:
                self._usage[str(key)] = Usage(max(0, int(value["count"])), float(value["last_used"]))
            except (KeyError, TypeError, ValueError):
                continue

    @staticmethod
    def key(action_id: str, application: str, text_types) -> str:
        app = application.casefold().strip()[:64]
        types = ",".join(sorted(str(value)[:24] for value in text_types))[:96]
        return f"{action_id[:80]}|{app}|{types}"

    def record(self, action_id: str, application: str, text_types) -> None:
        key = self.key(action_id, application, text_types)
        if key not in self._usage and len(self._usage) >= self.maximum:
            oldest = min(self._usage, key=lambda item: self._usage[item].last_used)
            del self._usage[oldest]
        usage = self._usage.setdefault(key, Usage())
        usage.count += 1
        usage.last_used = time()

    def suggest(self, action_ids, application: str, text_types, limit: int = 2) -> tuple[str, ...]:
        now = time()
        scored = []
        for order, action_id in enumerate(action_ids):
            usage = self._usage.get(self.key(action_id, application, text_types))
            if not usage:
                continue
            age_days = max(0.0, (now - usage.last_used) / 86400)
            score = min(20, usage.count) * 4 + max(0.0, 14 - age_days) - order / 1000
            scored.append((score, action_id))
        return tuple(action_id for _score, action_id in sorted(scored, reverse=True)[: max(0, min(2, limit))])

    def serialize(self) -> dict:
        return {key: {"count": value.count, "last_used": value.last_used} for key, value in self._usage.items()}
