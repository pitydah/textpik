#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="${CONTAINER_ENGINE:-podman}"
IMAGE="${ARCH_BUILD_IMAGE:-archlinux:latest}"
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
pacman -Syu --noconfirm --needed base-devel >/tmp/textpik-pacman.log
useradd -m builder
mkdir -p /build
release_tag=$(sed -n "s/^_tag=//p" /source/packaging/arch/PKGBUILD)
tar --exclude=.git --exclude=.build-appimage --exclude=build --exclude=dist \
    --transform="s#^\./#textpik-$release_tag/#" \
    -czf /build/textpik-local.tar.gz -C /source .
cp /source/packaging/arch/PKGBUILD /build/PKGBUILD
checksum=$(sha256sum /build/textpik-local.tar.gz | cut -d" " -f1)
sed -i "s#^source=.*#source=(\"textpik-local.tar.gz\")#" /build/PKGBUILD
sed -i "s#^sha256sums=.*#sha256sums=(\"$checksum\")#" /build/PKGBUILD
chown -R builder:builder /build
su builder -c "cd /build && makepkg --nodeps --noconfirm"
package=$(find /build -maxdepth 1 -name "textpik-*.pkg.tar.zst" -print -quit)
pacman -Qp "$package"
bsdtar -tf "$package" | grep -q "usr/bin/textpik$"
cp "$package" /out/
chown "$OUTPUT_UID:$OUTPUT_GID" /out/"$(basename "$package")"
'

echo "Arch package written to $ROOT_DIR/dist"
