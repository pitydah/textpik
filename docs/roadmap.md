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
- Optional content-free usage ranking with at most two recommendations.
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

## Non-negotiable performance rules

- No network request, model, dictionary or new subprocess on selection.
- No selected text in metrics, logs or persisted context profiles.
- A maximum of five popup placement candidates.
- Optional providers execute in the existing bounded Qt thread pool.
- New resident dependencies require an explicit benchmark and release review.
