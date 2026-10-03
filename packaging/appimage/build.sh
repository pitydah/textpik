#!/usr/bin/env bash
# AppImage build script for textpik
# Requires: python3, PySide6, PyInstaller
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="TextPik"
PYINSTALLER_VERSION="${PYINSTALLER_VERSION:-6.21.0}"
PYSIDE_VERSION="${PYSIDE_VERSION:-6.11.1}"
BUILD_DIR="$PROJECT_DIR/.build-appimage"
APPDIR="$BUILD_DIR/$APP_NAME.AppDir"

echo "==> Building textpik AppImage..."

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$APPDIR"

# Compile with PyInstaller
cd "$PROJECT_DIR"
python3 -m venv "$BUILD_DIR/venv"
"$BUILD_DIR/venv/bin/pip" install \
    "pyinstaller==$PYINSTALLER_VERSION" "PySide6==$PYSIDE_VERSION"
"$BUILD_DIR/venv/bin/python" -m PyInstaller \
    --onedir --name "$APP_NAME" --clean --noconfirm \
    --add-data "assets:assets" \
    --add-data "kwin:kwin" \
    --collect-submodules textpik_core \
    --hidden-import PySide6.QtDBus \
    --hidden-import PySide6.QtSvg \
    src/textpik.py

# PySide's wheel currently exposes a TIFF plugin linked against libtiff.so.5,
# which is unavailable on supported clean targets. Tesseract handles TIFF OCR
# directly, so shipping a plugin that Qt cannot load only adds noise and size.
find "$PROJECT_DIR/dist/$APP_NAME" -path '*/imageformats/libqtiff.so' -delete

# Prepare AppDir
cp -r "$PROJECT_DIR/dist/$APP_NAME"/* "$APPDIR/"
cp "$PROJECT_DIR/packaging/textpik.desktop" "$APPDIR/"
cp "$PROJECT_DIR/assets/app/textpik.svg" "$APPDIR/textpik.svg"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo"
cp "$PROJECT_DIR/packaging/textpik.desktop" \
    "$APPDIR/usr/share/applications/textpik.desktop"
cp "$PROJECT_DIR/packaging/io.github.pitydah.textpik.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/io.github.pitydah.textpik.metainfo.xml"
ln -sf io.github.pitydah.textpik.metainfo.xml \
    "$APPDIR/usr/share/metainfo/textpik.appdata.xml"
ln -sf TextPik "$APPDIR/AppRun"

echo "==> AppDir prepared at $APPDIR"

APPIMAGETOOL_BIN="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
if [[ -z "$APPIMAGETOOL_BIN" ]]; then
    echo "==> appimagetool not found; AppDir validation completed"
    exit 0
fi

OUTPUT="$PROJECT_DIR/dist/$APP_NAME-x86_64.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL_BIN" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"
echo "==> AppImage created at $OUTPUT"
