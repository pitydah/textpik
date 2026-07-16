"""Privacy-preserving local crash sentinel with no user-content fields."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import time

from .storage import read_json, write_json_atomic


@dataclass(frozen=True, slots=True)
class PreviousRun:
    unclean: bool = False
    started_at: float = 0.0
    version: str = ""


class CrashSentinel:
    def __init__(self, path: Path):
        self.path = Path(path)

    def start(self, version: str) -> PreviousRun:
        previous = PreviousRun()
        if self.path.exists():
            try:
                payload = read_json(self.path)
                if isinstance(payload, dict):
                    previous = PreviousRun(
                        True,
                        float(payload.get("started_at", 0)),
                        str(payload.get("version", "")),
                    )
            except (OSError, ValueError, TypeError):
                previous = PreviousRun(True)
        write_json_atomic(
            self.path,
            {"pid": os.getpid(), "started_at": time(), "version": str(version)},
        )
        return previous

    def clean(self) -> None:
        self.path.unlink(missing_ok=True)
