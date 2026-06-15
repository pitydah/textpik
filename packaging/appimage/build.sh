#!/usr/bin/env bash
# AppImage build script for textpik
# Requires: python3, PySide6, PyInstaller
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="TextPik"
BUILD_DIR="$PROJECT_DIR/.build-appimage"
APPDIR="$BUILD_DIR/$APP_NAME.AppDir"

echo "==> Building textpik AppImage..."

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$APPDIR"

# Compile with PyInstaller
cd "$PROJECT_DIR"
python3 -m venv "$BUILD_DIR/venv"
"$BUILD_DIR/venv/bin/pip" install pyinstaller PySide6
"$BUILD_DIR/venv/bin/python" -m PyInstaller \
    --onedir --name "$APP_NAME" --clean \
    --add-data "assets:assets" \
    --add-data "kwin:kwin" \
    --hidden-import PySide6.QtDBus \
    --hidden-import PySide6.QtSvg \
    src/textpik.py

# Prepare AppDir
cp -r "$PROJECT_DIR/dist/$APP_NAME"/* "$APPDIR/"
cp "$PROJECT_DIR/packaging/textpik.desktop" "$APPDIR/"
cp "$PROJECT_DIR/assets/app/textpik.svg" "$APPDIR/textpik.svg"
ln -sf textpik "$APPDIR/AppRun"

echo "==> AppImage prepared at $APPDIR"
echo "==> Run 'appimagetool $APPDIR' to create the AppImage"
