#!/usr/bin/env python3
"""Exercise repeated popup composition and enforce bounded process growth."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.TemporaryDirectory(prefix="textpik-stability-")
os.environ["HOME"] = _HOME.name
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME.name) / ".config")
os.environ["XDG_CACHE_HOME"] = str(Path(_HOME.name) / ".cache")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.textpik as textpik  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler  # noqa: E402
from src.textpik_core.performance import read_process_resources  # noqa: E402


class StabilityMonitor(textpik.BaseSelectionMonitor):
    pass


def main() -> int:
    def qt_messages(_kind, _context, message):
        if "does not support" not in message and "systemTrayWindowChanged" not in message:
            print(message, file=sys.stderr)

    qInstallMessageHandler(qt_messages)
    textpik.X11SelectionMonitor = StabilityMonitor
    textpik.WaylandSelectionMonitor = StabilityMonitor
    controller = textpik.TextPikApp()
    before = read_process_resources()
    initial_threads = before.threads if before else None
    for index in range(500):
        controller.popup.set_actions(
            controller.actions,
            compact=bool(index % 2),
        )
        controller.popup.show()
        controller.app.processEvents()
        controller.popup.hide()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    controller.app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    after = read_process_resources()
    controller.cleanup()
    if before and after and before.pss_kib is not None and after.pss_kib is not None:
        growth_mib = (after.pss_kib - before.pss_kib) / 1024
        print(f"popup_500_cycle_pss_growth_mib={growth_mib:.2f}")
        if growth_mib > 16:
            return 1
    if initial_threads is not None and after and after.threads > initial_threads + 2:
        print(f"thread_growth={after.threads - initial_threads}")
        return 1
    print("popup_500_cycle_status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
