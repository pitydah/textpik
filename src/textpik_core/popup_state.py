"""Deterministic popup lifecycle independent from Qt."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic


class PopupPhase(str, Enum):
    IDLE = "idle"
    STABILIZING = "stabilizing"
    VISIBLE = "visible"
    INTERACTING = "interacting"
    SUPPRESSED = "suppressed"


@dataclass
class PopupStateMachine:
    """Small state machine that makes popup transitions explicit and testable."""

    phase: PopupPhase = PopupPhase.IDLE
    signature: tuple | None = None
    changed_at: float = 0.0
    reason: str = ""

    def transition(self, phase: PopupPhase, *, signature=None, reason="") -> None:
        self.phase = phase
        if signature is not None:
            self.signature = signature
        self.reason = reason
        self.changed_at = monotonic()

    def begin(self, signature: tuple) -> bool:
        duplicate = self.phase in {
            PopupPhase.STABILIZING,
            PopupPhase.VISIBLE,
            PopupPhase.INTERACTING,
        } and signature == self.signature
        if duplicate:
            return False
        self.transition(PopupPhase.STABILIZING, signature=signature)
        return True

    def visible(self) -> None:
        self.transition(PopupPhase.VISIBLE)

    def interacting(self) -> None:
        self.transition(PopupPhase.INTERACTING)

    def suppress(self, reason: str) -> None:
        self.transition(PopupPhase.SUPPRESSED, reason=reason)

    def reset(self) -> None:
        self.phase = PopupPhase.IDLE
        self.signature = None
        self.reason = ""
        self.changed_at = monotonic()
