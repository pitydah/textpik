#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$ROOT_DIR/packaging/flatpak/io.github.pitydah.textpik.json"
BUILDER="${FLATPAK_BUILDER:-flatpak-builder}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/textpik-flatpak.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$ROOT_DIR/dist"

"$BUILDER" --user --install-deps-from=flathub --disable-rofiles-fuse \
    --force-clean --state-dir="$WORK_DIR/state" --repo="$WORK_DIR/repo" \
    "$WORK_DIR/build" "$MANIFEST"
flatpak build-bundle "$WORK_DIR/repo" "$ROOT_DIR/dist/TextPik.flatpak" \
    io.github.pitydah.textpik

if [[ "${TEXTPIK_FLATPAK_SMOKE:-0}" == "1" ]]; then
    flatpak install --user --reinstall -y "$WORK_DIR/repo" \
        io.github.pitydah.textpik
    flatpak run io.github.pitydah.textpik --self-check-gui
    flatpak uninstall --user -y io.github.pitydah.textpik
fi

echo "Flatpak bundle: $ROOT_DIR/dist/TextPik.flatpak"
