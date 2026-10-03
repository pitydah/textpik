# Lightweight premium roadmap

TextPik evolves through vertical releases: every phase must preserve startup
time, popup latency and a small resident memory footprint. Optional features are
loaded only after an explicit action.

## Delivered in the current RC worktree

- **Phase 0 — Technical base:** desktop-independent core contracts, atomic
  persistence, bounded performance telemetry, versioned settings and release
  architecture documentation.
- **Phase 1 — Intelligent popup:** deterministic selection-intent confidence,
  configurable compact/full composition, low-confidence suppression and
  constant-time placement scoring around the selection and screen edges.
- **Phase 2 — Writing foundation:** optional, local and lazy spelling provider;
  explicit spelling action runs off the UI thread, offers bounded suggestions
  and refuses to replace a selection that changed while the provider loaded.
- **Phase 3 — Context profiles:** user-defined action sets per application and
  text type, with drag-and-drop first-match priority, stable global ordering and
  no selected content stored in settings.
- **Phase 4 — Extension quality:** bounded declarative discovery, path
  confinement, duplicate detection, explicit rejection diagnostics and visible
  permission/capability previews.
- **Phase 5 — Automated desktop foundation:** offscreen lifecycle tests, virtual
  X11 smoke tests through Xvfb, headless Wayland smoke tests through Weston,
  compositor adapter fixtures and DEB/RPM artifact inspection in CI.
- **Phase 6 — Stable technical gate:** accessible popup names/descriptions,
  startup proof that optional dictionaries remain unloaded, signed SLSA/Sigstore
  artifact provenance and machine-enforced manual promotion evidence.

## TextPik Next 0.5 additions

- Local inline result card with safe arithmetic, unit conversion and statistics.
- Extended deterministic classification for dates, currency, coordinates, DOI,
  ISBN, paths and error output.
- Exact user-defined action order with contextual filtering that never promotes
  or rearranges actions behind the user's back.
- Personal spelling words, ignored words, automatic dictionary ordering and
  transactional undo.
- Explicit LanguageTool review, before/after confirmation and bounded response.
- Declarative shell-free automations loaded from a versionable JSON file.
- Ollama task selection through a local-only endpoint and bounded responses.
- On-demand Tesseract OCR for files and desktop-specific region capture.
- Optional bounded private history with sensitive-data rejection and lazy
  Fernet encryption when a user key is configured.
- Integrity-checked WASI extension manifests with explicit permission and
  execution timeout.
- CI gates for core classification/insight latency and process PSS.

## Intelligent interaction delivery

- Adaptive 30–250 ms stabilization based on accessible metadata, with extra
  protection for file managers, terminals and unstable selections.
- Collapsed accessibility ranges are rejected before action planning.
- Anchor decisions include source reliability, freshness and a diagnostic
  reason; fractional normalization is available to compositor adapters.
- User-selectable placement and bounded two-row composition expose more actions
  without creating an unbounded window.
- Action manifests support modifier variants while retaining the original
  permission and ranking identity.
- A graphical automation editor covers application, type, editability, safe
  regex conditions and all shell-free engine operations.
- Local JSON, entity, color, slug, terminal cleanup, diff and speech actions add
  useful depth without resident dependencies.
- A content-free crash sentinel identifies unclean shutdowns, and CI exercises
  500 popup lifecycles with bounded PSS and thread growth.
- OCR region capture falls back to the XDG Screenshot portal through lazy
  QtDBus, with race-free request handles and local-file validation.
- The visual automation editor includes reusable safe templates and exact step
  ordering through drag-and-drop or explicit move buttons.
- The popup planner filters edit-only and multiline operations, keeps pinned
  actions authoritative, promotes local contextual basics and moves disruptive
  integrations to the searchable palette. Thirteen new monochrome masters cover
  cut, whitespace, case, list, URL, Base64 and HTML operations.

## Next delivery gates

- Complete the physical KDE/GNOME X11/Wayland matrix and record results in
  `release-validation.json`.
- Complete the human accessibility and translation reviews.
- Finish two crash-free RC cycles without unresolved P0/P1 defects.
- Verify visible Flatpak/AppImage behavior on clean Wayland and X11 desktops;
  automated clean-container build, install and self-check are delivered.
- Evaluate a signed community catalog only after the WASI v2 runtime has passed
  an independent sandbox review.
- Keep semantic history and cross-device synchronization out of the resident
  application until they can be delivered as separately installed components.

## Next substantial improvement plan

### Phase A — Interaction contract (P0)

- Model one immutable interaction session per completed selection: captured
  text, action set, anchor, application and generation number.
- Add a pointer travel corridor between selection and toolbar. Distance-based
  dismissal must pause while the pointer is moving toward either surface.
- Freeze the toolbar anchor after its first stable presentation; selection
  fragments may update the captured text without making the toolbar jump.
- Normalize compositor notifications into explicit reasons: own-window map,
  action press, external click, context menu, timeout and selection replacement.
- Acceptance: every action remains clickable after PRIMARY clears; no toolbar
  closes during its first 750 ms; no more than one placement per selection drag.

### Phase B — Unobtrusive context engine (P1)

- Introduce per-application behavior profiles: normal, editor, browser,
  terminal, file manager and excluded/sensitive, resolved without subprocesses.
- Filter actions by applicability while preserving the exact configured order.
- Add a temporary “do not show again here” gesture and session-only snooze,
  separate from permanent blocked applications.
- Use selection geometry and role to avoid covering handles, carets, rename
  fields, drag operations and native context menus.
- Acceptance: zero appearances during file drag/rename and right-click flows in
  the physical KDE/GNOME test matrix.

### Phase C — Reliable lightweight actions (P1)

- Give every action a typed preflight and result contract: available, degraded,
  unavailable, success, copied fallback or actionable failure.
- Add a diagnostics panel showing only capability state and last error category;
  never retain selected text.
- Expand dependency probes for reachable KDE Connect devices, printer queues,
  OCR languages and provider models, refreshed outside the popup hot path.
- Add transactional replacement checks so undo is offered only for the exact
  application and selection generation that produced the change.
- Acceptance: no enabled action silently does nothing and every degraded path
  explains whether its result was replaced, copied or opened.

### Phase D — High-value local actions (P2)

- Add dependency-free actions for hashes/checksums, case-style conversion,
  Markdown links, URL inspection, timestamp/date conversion and richer entity
  extraction.
- Expand safe calculations and units through static tables loaded on demand.
- Provide correction profiles using system dictionaries first; LanguageTool and
  local AI remain optional providers loaded only on explicit use.
- Keep brand/web integrations as URL adapters and isolate richer connectors as
  optional extensions rather than resident core code.
- Acceptance: each new action adds no resident thread, timer, network request or
  measurable popup-path allocation when it is not invoked.

### Phase E — Stable desktop evidence (P2)

- Record scripted interaction tests for press/release, PRIMARY loss, multi-step
  selection and external click on KDE/GNOME under native X11 and Wayland.
- Add crash-loop recovery and a bounded restart policy for autostart services.
- Run 5,000 popup/action cycles and require stable PSS, zero native crashes and
  p95 selection-to-popup latency below 220 ms on the reference machine.
- Promote to stable only after two physical RC cycles have no unresolved P0/P1.

## Non-negotiable performance rules

- No network request, model, dictionary or new subprocess on selection.
- No selected text in metrics, logs or persisted context profiles.
- A maximum of five popup placement candidates.
- Optional providers execute in the existing bounded Qt thread pool.
- New resident dependencies require an explicit benchmark and release review.
