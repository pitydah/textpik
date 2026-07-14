# TextPik architecture

TextPik keeps the resident process small by separating deterministic core logic
from Qt and desktop adapters. Code under `textpik_core` must not import PySide6,
start processes or perform network I/O on the popup hot path.

## Hot path

1. A monitor creates a `SelectionContext`.
2. Selection policy rejects sensitive and non-text controls and calculates a
   deterministic confidence score from accessibility metadata.
3. `classify_text()` assigns immutable text categories using local rules.
4. `ContextSnapshot` copies only the metadata needed for planning; it never
   retains the selected text.
5. `plan_actions()` filters actions while preserving user order.
6. The Qt popup composes and displays the resulting action list.

Optional context profiles are normalized into application substrings, text-type
sets and stable action IDs. The first matching profile limits the planner's
allowed action set while the global user order remains authoritative. Profiles
store no selected text and add only bounded set membership checks to planning.

When context confidence is incomplete, adaptive mode uses a compact direct
action set and leaves the remainder in the action palette. Very low confidence
can suppress the popup. Both thresholds and the compact size are configurable;
the scoring itself is pure arithmetic and adds no probes or background work.

Popup placement scores at most five candidates. It heavily penalizes covering
the selection or cursor, then considers edge clamping and distance. This keeps
placement stable and constant-time near monitor edges.

Persisted defaults, bounds and migrations live in `textpik_core.settings`.
Toolkit-specific color validation is injected by the Qt boundary, so loading or
testing the settings schema never initializes a graphical runtime.

Session/desktop discovery lives in `textpik_core.platform`; command
classification and confirmation policy live in `textpik_core.execution`.
Both accept explicit or injectable inputs in tests and never probe the desktop
through subprocesses. Actual process creation remains in the application
adapter, outside the pure policy layer.

JSON persistence is centralized in `textpik_core.storage`. Writes use a private
temporary file, flush it before an atomic replace and keep the previous file if
serialization fails. TextPik does not rewrite normalized settings during startup
unless a migration or recovery actually changed their contents.

`PerformanceTracker` stores aggregate durations only. It has no timers, worker
threads, persistence or user-content fields. Diagnostics currently track these
budgets:

| Metric | Budget |
|---|---:|
| Text classification | 5 ms |
| Action planning | 5 ms |
| Successful popup hot path | 50 ms |

## Dependency rule

Core modules may depend on the Python standard library and other core modules.
Qt, AT-SPI, D-Bus, compositor commands and network providers belong behind
adapters. Optional providers such as LanguageTool, OCR or local AI must be
discovered and invoked on demand; they must never become resident dependencies
of the core process.

The spelling contract follows that rule: it accepts an injected dictionary,
loads the optional system provider only on the first explicit spelling request,
caches only dictionary handles, and never retains selected text.

## Compatibility rule

Modularization must preserve public imports from `textpik.py` until a versioned
migration is documented. Pure contracts require unit tests, and desktop adapters
require smoke or integration tests appropriate to the affected environment.
