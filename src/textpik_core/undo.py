"""Bounded in-memory undo records for selection replacements."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class UndoRecord:
    before: str
    after: str
    application: str
    created_at: float


class UndoManager:
    def __init__(self, maximum: int = 12, ttl: float = 300.0):
        self._records: deque[UndoRecord] = deque(maxlen=max(1, min(50, maximum)))
        self.ttl = max(5.0, ttl)

    def remember(self, before: str, after: str, application: str = "") -> None:
        if before != after:
            self._records.append(UndoRecord(before, after, application, monotonic()))

    def pop(self, application: str = "") -> UndoRecord | None:
        now = monotonic()
        while self._records:
            record = self._records.pop()
            if now - record.created_at > self.ttl:
                continue
            if application and record.application and application != record.application:
                continue
            return record
        return None

    def clear(self) -> None:
        self._records.clear()
