#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="${CONTAINER_ENGINE:-podman}"
IMAGE="${APPIMAGE_BUILD_IMAGE:-ubuntu:22.04}"
OUTPUT_UID="$(id -u)"
OUTPUT_GID="$(id -g)"
if [[ "$("$ENGINE" info --format '{{.Host.Security.Rootless}}' 2>/dev/null || true)" == "true" ]]; then
    # Container root already maps to the invoking user under rootless Podman.
    OUTPUT_UID=0
    OUTPUT_GID=0
fi
mkdir -p "$ROOT_DIR/dist"

"$ENGINE" run --rm \
    -e OUTPUT_UID="$OUTPUT_UID" -e OUTPUT_GID="$OUTPUT_GID" \
    -v "$ROOT_DIR:/source:ro" -v "$ROOT_DIR/dist:/out" \
    "$IMAGE" bash -lc '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl file \
    libegl1 libgl1 libglib2.0-0 libdbus-1-3 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 >/tmp/textpik-apt.log
curl -fsSL \
    https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    -o /tmp/appimagetool
echo "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0  /tmp/appimagetool" \
    | sha256sum --check
chmod +x /tmp/appimagetool
cp -a /source /work
find /work/dist -maxdepth 1 -name "*.AppImage" -delete
cd /work
APPIMAGETOOL=/tmp/appimagetool packaging/appimage/build.sh
cp dist/TextPik-x86_64.AppImage /out/
chown "$OUTPUT_UID:$OUTPUT_GID" /out/TextPik-x86_64.AppImage
'

echo "AppImage reproducible: $ROOT_DIR/dist/TextPik-x86_64.AppImage"
