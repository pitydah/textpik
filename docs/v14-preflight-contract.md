# V14 mandatory pre-apply contract

Target baseline:

- branch: `agent/textpik-next-0-5-rc`
- exact HEAD: `2c8daf5f57190a72b44ce7b304fcf06d644e8bbc`

This patch is intentionally **fail closed**.

## OpenCode order

OpenCode MUST execute these checks **before applying any hunk**:

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --porcelain=v1
git diff --check
python -m py_compile src/textpik.py src/textpik_core/*.py
python -m unittest discover -s tests -v
git apply --stat /path/to/textpik-popup-wayland-v14-rc.patch
git apply --check --verbose /path/to/textpik-popup-wayland-v14-rc.patch
```

Required results:

1. HEAD equals `2c8daf5f57190a72b44ce7b304fcf06d644e8bbc` exactly.
2. The working tree is clean.
3. Existing baseline tests pass before mutation.
4. `git apply --check` exits 0.

If the working tree is dirty, **do not stash, reset, checkout, clean, or overwrite it**.
Stop and report the dirty paths.

If HEAD differs, **do not use `--3way`, `--reject`, fuzz, manual context guessing, or
force**. Stop and rebase V14 against the new exact commit.

Only after every preflight gate is green may OpenCode run:

```bash
git apply /path/to/textpik-popup-wayland-v14-rc.patch
```

Then it MUST run:

```bash
git diff --check
python -m py_compile src/textpik.py src/textpik_core/*.py
python -m unittest tests.test_popup_v14_rc -v
python -m unittest discover -s tests -v
python scripts/check_performance.py
```

No commit and no push are authorized by this patch. They require a separate
explicit instruction.

## Scope

V14 is RC-native. It does not apply V7–V13 historical patches.

It closes:
- remote Ollama probe escape from the local-only contract;
- stale cached AT-SPI focus;
- zero/degenerate AT-SPI geometry promoted as authoritative;
- Qt button state treated as global Wayland state;
- AT-SPI `None` incorrectly clearing clipboard authority;
- KWin activation mislabeled as a raw outside click;
- diagnostics that lacked a truthful Wayland capability ledger.

It deliberately does **not** claim exact Wayland placement. KWin 6 documents
`KWin::Window.frameGeometry` as read-only in the normal scripting API; direct
window movement belongs to an Effect-level API. Plasma therefore remains
`DEGRADED` for positioning until a KWin Effect or real layer-shell presentation
backend is implemented and physically tested.
