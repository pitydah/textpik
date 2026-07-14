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

## Next delivery gates

- Complete the physical KDE/GNOME X11/Wayland matrix and record results in
  `release-validation.json`.
- Complete the human accessibility and translation reviews.
- Finish two crash-free RC cycles without unresolved P0/P1 defects.
- Build/install the Flatpak and AppImage on clean target systems.

## Non-negotiable performance rules

- No network request, model, dictionary or new subprocess on selection.
- No selected text in metrics, logs or persisted context profiles.
- A maximum of five popup placement candidates.
- Optional providers execute in the existing bounded Qt thread pool.
- New resident dependencies require an explicit benchmark and release review.
