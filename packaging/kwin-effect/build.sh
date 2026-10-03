#!/usr/bin/env bash
# Builds the TextPik KWin placement effect for a package recipe.
#
# The effect is optional and native: it links against the KWin the host ships,
# so a package build without the KWin and KF6 development files must still
# succeed. Missing dependencies are reported and the script exits 0, leaving
# the sources in place for a later per-user build.
#
# usage: build.sh <destination-directory> [source-directory]

set -euo pipefail

DEST="${1:?usage: build.sh <destination-directory> [source-directory]}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${2:-$(cd "$SCRIPT_DIR/../../native/kwin-effect" && pwd)}"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "textpik: KWin effect sources not found in $SOURCE_DIR" >&2
    exit 0
fi

# Names differ per distribution on purpose: the message is read by whoever
# builds the package and has to point at packages they can actually install.
missing=()
command -v cmake >/dev/null || missing+=("cmake")
if ! command -v ninja >/dev/null && ! command -v make >/dev/null; then
    missing+=("ninja or make")
fi
command -v c++ >/dev/null || missing+=("a C++ compiler")
[[ -f /usr/include/kwin/effect/effect.h ]] || missing+=("kwin headers")
[[ -d /usr/include/KF6/KCoreAddons ]] || missing+=("KF6 CoreAddons headers")
[[ -d /usr/include/KF6/KConfigCore ]] || missing+=("KF6 Config headers")
[[ -d /usr/include/KF6/KWindowSystem ]] || missing+=("KF6 WindowSystem headers")

if (( ${#missing[@]} > 0 )); then
    echo "textpik: skipping the KWin placement effect; missing: ${missing[*]}"
    echo "textpik: the sources stay packaged so the effect can be built later"
    exit 0
fi

BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/textpik-kwin-effect.XXXXXX")"
GENERATOR="Ninja"
command -v ninja >/dev/null || GENERATOR="Unix Makefiles"

cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" -G "$GENERATOR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR"

mkdir -p "$DEST"
cp "$BUILD_DIR/textpik-placement.so" "$DEST/"

# The verifier is a build artifact, not a deliverable: run it quietly to prove
# the plugin matches the KWin it was compiled against.
if [[ -x "$BUILD_DIR/textpik-verify-effect" ]] \
    && ! "$BUILD_DIR/textpik-verify-effect" "$BUILD_DIR/textpik-placement.so" >/dev/null 2>&1; then
    echo "textpik: warning: the KWin effect did not verify against this KWin" >&2
fi

echo "textpik: KWin placement effect installed to $DEST/textpik-placement.so"
