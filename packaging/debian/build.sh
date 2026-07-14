#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

cp -a "$ROOT_DIR/." "$BUILD_DIR/textpik"
rm -rf "$BUILD_DIR/textpik/.git" "$BUILD_DIR/textpik/build" "$BUILD_DIR/textpik/dist"
cp -a "$BUILD_DIR/textpik/packaging/debian" "$BUILD_DIR/textpik/debian"

cd "$BUILD_DIR/textpik"
dpkg-buildpackage -us -uc -b

mkdir -p "$ROOT_DIR/dist"
cp "$BUILD_DIR"/textpik_*.deb "$ROOT_DIR/dist/"
