"""Allocation-light aggregate performance telemetry with no user content."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from pathlib import Path

MAX_METRICS = 16


@dataclass(frozen=True, slots=True)
class ProcessResources:
    rss_kib: int
    pss_kib: int | None
    threads: int


def read_process_resources(proc_root: Path = Path("/proc/self")) -> ProcessResources | None:
    """Read Linux process counters without importing psutil or starting a probe."""
    try:
        status = (proc_root / "status").read_text(encoding="utf-8")
    except OSError:
        return None

    def field(name: str) -> int | None:
        for line in status.splitlines():
            if line.startswith(f"{name}:"):
                try:
                    return int(line.split()[1])
                except (IndexError, ValueError):
                    return None
        return None

    pss = None
    try:
        rollup = (proc_root / "smaps_rollup").read_text(encoding="utf-8")
        for line in rollup.splitlines():
            if line.startswith("Pss:"):
                pss = int(line.split()[1])
                break
    except (OSError, ValueError, IndexError):
        pass
    rss, threads = field("VmRSS"), field("Threads")
    return ProcessResources(rss or 0, pss, threads or 0)


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    name: str
    count: int
    last_ms: float
    average_ms: float
    maximum_ms: float
    budget_ms: float | None
    budget_exceeded: int


@dataclass(slots=True)
class _Metric:
    count: int = 0
    total_ns: int = 0
    last_ns: int = 0
    maximum_ns: int = 0
    budget_exceeded: int = 0


class PerformanceTracker:
    """Keep aggregate timings only; selected text is never accepted or stored."""

    __slots__ = ("_budgets_ns", "_metrics")

    def __init__(self, budgets_ms: dict[str, float] | None = None):
        self._budgets_ns = {
            name: round(value * 1_000_000)
            for name, value in (budgets_ms or {}).items()
        }
        self._metrics: dict[str, _Metric] = {}

    @staticmethod
    def start() -> int:
        return perf_counter_ns()

    def observe(self, name: str, started_ns: int) -> int:
        duration_ns = max(0, perf_counter_ns() - started_ns)
        self.record_ns(name, duration_ns)
        return duration_ns

    def record_ns(self, name: str, duration_ns: int) -> None:
        duration_ns = max(0, int(duration_ns))
        if name not in self._metrics and len(self._metrics) >= MAX_METRICS:
            return
        metric = self._metrics.setdefault(name, _Metric())
        metric.count += 1
        metric.total_ns += duration_ns
        metric.last_ns = duration_ns
        metric.maximum_ns = max(metric.maximum_ns, duration_ns)
        budget = self._budgets_ns.get(name)
        if budget is not None and duration_ns > budget:
            metric.budget_exceeded += 1

    def snapshots(self) -> tuple[MetricSnapshot, ...]:
        snapshots = []
        for name in sorted(self._metrics):
            metric = self._metrics[name]
            budget = self._budgets_ns.get(name)
            snapshots.append(
                MetricSnapshot(
                    name=name,
                    count=metric.count,
                    last_ms=metric.last_ns / 1_000_000,
                    average_ms=(metric.total_ns / metric.count) / 1_000_000,
                    maximum_ms=metric.maximum_ns / 1_000_000,
                    budget_ms=None if budget is None else budget / 1_000_000,
                    budget_exceeded=metric.budget_exceeded,
                )
            )
        return tuple(snapshots)
