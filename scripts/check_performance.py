#!/usr/bin/env python3
"""Deterministic lightweight performance gates suitable for shared CI runners."""

from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.textpik_core.insights import local_insight  # noqa: E402
from src.textpik_core.performance import read_process_resources  # noqa: E402
from src.textpik_core.text import classify_text  # noqa: E402


def average_ms(function, values, rounds=2000):
    started = time.perf_counter_ns()
    for index in range(rounds):
        function(values[index % len(values)])
    return (time.perf_counter_ns() - started) / rounds / 1_000_000


def main() -> int:
    samples = (
        "https://example.com/path",
        "10.1000/xyz123",
        "2026-07-14",
        "RuntimeError: failed: sample",
        "def example(value):\n    return value + 1",
    )
    classification = average_ms(classify_text, samples)
    insight = average_ms(local_insight, ("(5 + 3) * 2", "10 km a mi"))
    resources = read_process_resources()
    pss_mib = None if resources is None or resources.pss_kib is None else resources.pss_kib / 1024
    print(f"classification_average_ms={classification:.4f}")
    print(f"inline_insight_average_ms={insight:.4f}")
    print(f"core_process_pss_mib={pss_mib if pss_mib is not None else 'unknown'}")
    if classification >= 5 or insight >= 5:
        return 1
    if pss_mib is not None and pss_mib > 70:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
