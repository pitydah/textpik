#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SPEC_FILE="$ROOT_DIR/packaging/rpm/textpik.spec"
TOP_DIR="$(mktemp -d)"
trap 'rm -rf "$TOP_DIR"' EXIT

SOURCE_DIR="$(sed -n 's/^%autosetup -n //p' "$SPEC_FILE")"
ARCHIVE_NAME="$(sed -n 's|^Source0:.*tags/||p' "$SPEC_FILE")"
if [[ -z "$SOURCE_DIR" || -z "$ARCHIVE_NAME" ]]; then
    echo "Unable to determine RPM source archive metadata" >&2
    exit 1
fi

mkdir -p "$TOP_DIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
git -C "$ROOT_DIR" archive \
    --format=tar.gz \
    --prefix="$SOURCE_DIR/" \
    --output="$TOP_DIR/SOURCES/$ARCHIVE_NAME" \
    HEAD

rpmbuild --define "_topdir $TOP_DIR" -ba "$SPEC_FILE"

mkdir -p "$ROOT_DIR/dist"
cp "$TOP_DIR"/RPMS/noarch/*.rpm "$TOP_DIR"/SRPMS/*.rpm "$ROOT_DIR/dist/"
