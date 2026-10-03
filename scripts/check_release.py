#!/usr/bin/env python3
"""Validate that all release metadata describes the same version."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def project_version() -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        read("pyproject.toml"),
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("pyproject.toml does not declare a version")
    return match.group(1)


def release_values(version: str) -> dict[str, str]:
    rc = re.fullmatch(r"(\d+\.\d+\.\d+)rc(\d+)", version)
    if rc:
        base, number = rc.groups()
        return {
            "tag": f"v{base}-rc.{number}",
            "display": f"{base}-rc.{number}",
            "debian": f"{base}~rc{number}-1",
            "rpm_version": base,
            "rpm_release": f"0.rc{number}",
            "arch": f"{base}rc{number}",
        }
    stable = re.fullmatch(r"\d+\.\d+\.\d+", version)
    if stable:
        return {
            "tag": f"v{version}",
            "display": version,
            "debian": f"{version}-1",
            "rpm_version": version,
            "rpm_release": "1",
            "arch": version,
        }
    raise ValueError(f"unsupported release version: {version}")


def validate(tag: str | None = None) -> tuple[str, dict[str, str]]:
    version = project_version()
    values = release_values(version)
    errors = []

    if tag is not None and tag != values["tag"]:
        errors.append(f"tag {tag!r} must be {values['tag']!r}")

    debian = read("packaging/debian/changelog")
    if not debian.startswith(f"textpik ({values['debian']})"):
        errors.append("Debian changelog version is inconsistent")

    rpm = read("packaging/rpm/textpik.spec")
    if not re.search(
        rf"^Version:\s+{re.escape(values['rpm_version'])}$", rpm, re.MULTILINE
    ):
        errors.append("RPM Version is inconsistent")
    if not re.search(
        rf"^Release:\s+{re.escape(values['rpm_release'])}%", rpm, re.MULTILINE
    ):
        errors.append("RPM Release is inconsistent")
    if values["tag"] not in rpm:
        errors.append("RPM source tag is inconsistent")

    arch = read("packaging/arch/PKGBUILD")
    if not re.search(
        rf"^pkgver={re.escape(values['arch'])}$", arch, re.MULTILINE
    ):
        errors.append("Arch pkgver is inconsistent")
    if not re.search(
        rf"^_tag={re.escape(values['display'])}$", arch, re.MULTILINE
    ):
        errors.append("Arch source tag is inconsistent")

    appstream = ET.parse(
        ROOT / "packaging/io.github.pitydah.textpik.metainfo.xml"
    ).getroot()
    latest = appstream.find("releases/release")
    if latest is None or latest.get("version") != values["display"]:
        errors.append("AppStream release version is inconsistent")

    if f"## {values['tag']}" not in read("CHANGELOG.md"):
        errors.append("CHANGELOG.md has no entry for this release")
    if f'APP_VERSION = "{values["display"]}"' not in read("src/textpik.py"):
        errors.append("Runtime application version is inconsistent")

    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.extend(validate_stable_evidence(version))

    if errors:
        raise ValueError("\n".join(f"- {error}" for error in errors))
    return version, values


def validate_stable_evidence(version: str) -> list[str]:
    """Require explicit human evidence before stable metadata can pass."""
    try:
        evidence = json.loads(read("release-validation.json"))
    except (OSError, ValueError):
        return ["stable release validation evidence is missing or invalid"]
    errors = []
    if evidence.get("target_version") != version:
        errors.append("stable evidence target_version is inconsistent")
    try:
        crash_free_cycles = int(evidence.get("crash_free_rc_cycles", 0))
    except (TypeError, ValueError):
        crash_free_cycles = 0
    if crash_free_cycles < 2:
        errors.append("stable promotion requires two crash-free RC cycles")
    matrix = evidence.get("manual_desktop_matrix", {})
    required = (
        "kde_wayland",
        "kde_x11",
        "gnome_wayland",
        "gnome_x11",
        "hyprland_or_sway_wayland",
    )
    missing = [name for name in required if not matrix.get(name, False)]
    if missing:
        errors.append("stable desktop validation missing: " + ", ".join(missing))
    distribution = evidence.get("distribution_matrix", {})
    required_distributions = (
        "debian_stable",
        "ubuntu_lts",
        "fedora",
        "arch_clean_chroot",
        "flatpak_wayland",
        "flatpak_x11",
        "appimage_clean_host",
    )
    missing_distributions = [
        name for name in required_distributions if not distribution.get(name, False)
    ]
    if missing_distributions:
        errors.append(
            "stable distribution validation missing: "
            + ", ".join(missing_distributions)
        )
    if not evidence.get("accessibility_reviewed", False):
        errors.append("stable accessibility review is incomplete")
    if not evidence.get("translations_reviewed", False):
        errors.append("stable translation review is incomplete")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Git tag to compare with project metadata")
    args = parser.parse_args()
    try:
        version, values = validate(args.tag)
    except ValueError as exc:
        print(f"release metadata validation failed:\n{exc}", file=sys.stderr)
        return 1
    print(f"release metadata valid: {version} ({values['tag']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
