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
    """Small state machine that makes popup transitions explicit and testable.

    ``signature`` describes *what* is being shown, and ``generation`` describes
    *which gesture* asked for it. Both are needed: re-selecting the same text
    produces an identical signature, and without the generation the duplicate
    guard would swallow a selection the user really made and leave the popup
    anchored to the previous cursor position.
    """

    phase: PopupPhase = PopupPhase.IDLE
    signature: tuple | None = None
    generation: int | None = None
    changed_at: float = 0.0
    reason: str = ""

    def transition(
        self, phase: PopupPhase, *, signature=None, generation=None, reason=""
    ) -> None:
        self.phase = phase
        if signature is not None:
            self.signature = signature
        if generation is not None:
            self.generation = generation
        self.reason = reason
        self.changed_at = monotonic()

    def begin(self, signature: tuple, generation: int | None = None) -> bool:
        """Start a new popup unless this exact gesture already owns the phase.

        A caller that supplies no generation keeps the previous behaviour: it
        cannot tell gestures apart, so an identical signature still counts as a
        duplicate.
        """
        duplicate = (
            self.phase
            in {
                PopupPhase.STABILIZING,
                PopupPhase.VISIBLE,
                PopupPhase.INTERACTING,
            }
            and signature == self.signature
            and generation == self.generation
        )
        if duplicate:
            return False
        self.transition(
            PopupPhase.STABILIZING, signature=signature, generation=generation
        )
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
        self.generation = None
        self.reason = ""
        self.changed_at = monotonic()
