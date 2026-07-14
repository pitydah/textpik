# Release candidate checklist

The tag workflow enforces the automated gates. Complete the manual desktop matrix
before creating an RC tag.

## Automated gates

- CI passes on Python 3.10, 3.11, 3.12 and 3.13.
- Core branch coverage is at least 60%.
- Offscreen startup, popup display and clean shutdown smoke test passes.
- Ruff, byte compilation, unit tests and packaging metadata validation pass.
- Wheel and source distribution pass `twine check`.
- Project, Debian, RPM, Arch, AppStream and Git tag versions agree.
- Release artifacts include a verified `SHA256SUMS` file.

## Manual desktop matrix

Test text selection, popup placement, action execution and clean shutdown in:

| Desktop | Wayland | X11 |
|---|---:|---:|
| KDE Plasma | Required | Required |
| GNOME | Required | Required |
| Hyprland or Sway | Required | N/A |

Use Firefox or Chromium, LibreOffice, a Qt editor, a GTK editor, a terminal and
the desktop's file manager. Confirm that password fields, context menus, file
dragging and multi-file selections never expose a popup.

## Distribution matrix

- Install, launch and uninstall the DEB on the current Ubuntu or Debian stable.
- Install, launch and uninstall the RPM on the current Fedora release.
- Build and install the Arch package in a clean chroot.
- Build the Flatpak manifest and verify Wayland/X11 fallback behavior.
- Build and launch the AppImage on a machine without the source checkout.

## Promotion

Create `v0.4.0-rc.1` only after every automated gate and required manual entry is
green. Promote to stable only after the RC has no unresolved P0/P1 defects during
the agreed testing period.
