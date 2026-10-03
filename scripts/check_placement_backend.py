#!/usr/bin/env python3
"""Report whether the TextPik KWin placement effect is loaded.

Run this after logging back in. It answers the only question that matters
before trusting popup placement on Plasma: is a compositor-side authority
actually present, or is TextPik running degraded?

Exit codes: 0 loaded, 1 not loaded, 2 cannot tell.
"""

from __future__ import annotations

import json
import subprocess
import sys

EFFECT_ID = "textpik-placement"
PLACEMENT_SERVICE = "org.textpik.KWinPlacement"
PLACEMENT_PATH = "/KWinPlacement"
PLACEMENT_INTERFACE = "org.textpik.KWinPlacement"


def qdbus(*args: str) -> str:
    result = subprocess.run(
        ["qdbus6", *args], capture_output=True, text=True, timeout=15
    )
    return result.stdout.strip()


def check() -> int:
    active = qdbus("org.kde.KWin", "/Effects", "org.kde.kwin.Effects.activeEffects")
    listed = qdbus("org.kde.KWin", "/Effects", "org.kde.kwin.Effects.listOfEffects")
    service = qdbus(PLACEMENT_SERVICE, PLACEMENT_PATH)
    readback = qdbus(
        PLACEMENT_SERVICE,
        PLACEMENT_PATH,
        f"{PLACEMENT_INTERFACE}.readback",
    )

    parsed = readback.split(",", 6)
    service_up = "no such" not in service.lower() and service != ""
    readback_ok = len(parsed) == 7

    report = {
        "listed_by_kwin": EFFECT_ID in listed,
        "active": EFFECT_ID in active,
        "dbus_service_up": service_up,
        "readback_ok": readback_ok,
        "readback_raw": readback,
        "active_effects": [a for a in active.split(",") if a],
    }
    if readback_ok:
        report["last_revision"] = int(parsed[0])
        report["has_window"] = parsed[1] == "1"

    print(json.dumps(report, indent=2))

    if report["active"] and report["dbus_service_up"]:
        print(
            "\nOK: el effect esta cargado y org.textpik.KWinPlacement responde.\n"
            "TextPik deberia reportar backend=kwin-effect y verified=true."
        )
        return 0

    if not report["listed_by_kwin"]:
        print(
            "\nEl effect NO aparece en la lista de KWin. KWin cachea el\n"
            "descubrimiento de plugins al arrancar: si instalaste el .so o\n"
            "cambiaste QT_PLUGIN_PATH despues del ultimo login, hay que\n"
            "volver a cerrar sesion."
        )
        return 1

    print(
        "\nKWin ve el effect pero no esta activo. Habilitalo con:\n"
        "  qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadEffect "
        f"{EFFECT_ID}"
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(check())
    except subprocess.TimeoutExpired:
        print("No se pudo consultar D-Bus; KWin no responde.", file=sys.stderr)
        sys.exit(2)
