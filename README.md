# TextPik

Popup action bar on text selection for Linux desktops (Wayland & X11).

Development status: **0.5.0 RC1 candidate**. Promotion requirements are tracked
in the [release checklist](docs/release-checklist.md). Security-sensitive reports
must follow [SECURITY.md](SECURITY.md) instead of a public bug report.

Select text anywhere and a customizable action bar appears at your cursor —
copy, search, translate, open links, and more with one click.
<p align="center">
  <img src="assets/logo.png" width="160" alt="TextPik logo">
</p>

## Features

- 45+ built-in actions: copy/cut/paste, search, translation, text transforms,
  on-demand spelling correction, terminal, print, Ollama, KDE Connect and Klipper
- Context-aware filtering for URLs, email, code, numbers and regular text,
  with optional smart ordering that always honors explicitly pinned actions
- Optional context profiles choose an explicit action subset for an application
  and/or text type, with first-match priority and no automatic reordering
- Expandable popup with a user-defined number of direct actions, optional
  “show all” mode and drag-and-drop ordering; “More actions” contains only the
  real overflow and remains fuzzy-searchable
- Optional two-row composition on narrow displays, placement preference and
  Alt-based action variants without duplicating toolbar icons
- Adaptive selection stabilization delays suspicious file-manager, terminal and
  rapidly changing selections while keeping editable text fields immediate
- Local inline calculations, unit conversions and text statistics without a
  network request
- On-demand LanguageTool grammar review with before/after confirmation
- Transactional undo for transforms, spelling, grammar and automations
- Optional bounded private history, disabled by default and encryptable through
  `TEXTPIK_HISTORY_KEY`
- Declarative shell-free automations and integrity-checked WASI extensions
- Visual automation editor with application, text type, editability and regex
  conditions plus replace/prefix/suffix and transformation steps
- Local OCR for image files or screen regions through an external Tesseract
  installation
- Local JSON formatting, entity extraction, color conversion, slug creation,
  terminal-output cleaning, clipboard comparison and on-demand text-to-speech
- Confidence-aware composition: incomplete desktop context gets a smaller bar,
  while clearly non-text or very low-confidence selections are suppressed
- Editability and multiline gates prevent cut, paste and list operations from
  appearing where they cannot work; distant-pointer dismissal keeps the bar out
  of the way when the user moves on
- Constant-time candidate placement beside the pointer without covering the
  selected text, right-click suppression and optional inactivity auto-hide
- Configurable icon size, bar padding, spacing, 3–40 direct actions and cursor gap
- File-manager awareness: file objects are ignored while text fields still work
- Native desktop identity, XDG autostart management, AppStream metadata and
  system-tray active/paused status
- Privacy-safe crash sentinel and richer capability diagnostics for portals,
  Secret Service, selection backends and the active positioning provider
- Capability-aware actions with clear status for CUPS, Ollama, terminals,
  KDE Connect, Klipper and automatic paste fallbacks
- Native URL/file opening through Qt desktop services and sandbox portals
- KDE Plasma integration: Klipper D-Bus, KWin cursor bridge, system tray
- Event-driven AT-SPI selection detection with a low-frequency compatibility
  fallback for applications that do not emit accessibility notifications
- Revisioned selection sessions discard stale Wayland/AT-SPI results, while the
  intent engine suppresses menus, file objects and TextPik's own interface
- Wayland positioning via AT-SPI selection geometry, KWin, Hyprland and Sway;
  slow compositor/process probes run outside the popup display path and position
  hysteresis prevents small cursor changes from making the bar jitter
- Text transformations replace editable selections through AT-SPI, with a safe
  clipboard fallback
- Click-outside-to-close
- Configurable settings with theme presets (Light, Dark, OLED)
- Numeric shortcuts 1-9 and arrow/Enter keyboard navigation when invoked by hotkey
- Accessible names and descriptions for the compact bar, overflow search and
  every action, without forcing focus during normal mouse selection
- Per-application, activity and game exclusions

## Requirements

- KDE Plasma, GNOME, Hyprland, Sway or another modern Linux desktop
- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- Optional: PyEnchant plus a Hunspell dictionary for local spelling correction;
  neither is loaded until the spelling action is explicitly used
- `wl-clipboard` plus `wtype` or `ydotool` on Wayland
- `xdotool` on X11

## Installation

```bash
git clone https://github.com/pitydah/textpik.git
cd textpik
chmod +x packaging/install.sh
./packaging/install.sh
```

This installs system packages, creates the `textpik` command, a `.desktop`
entry, autostart, and the KWin cursor bridge script.

After installation, launch from the app menu or run:

```bash
textpik
```

## Quick run (no install)

```bash
git clone https://github.com/pitydah/textpik.git
cd textpik
python3 src/textpik.py
```

## Wayland vs X11

| Feature | Wayland | X11 |
|---------|---------|-----|
| Popup anchor | AT-SPI, then KWin/Hyprland/Sway/pointer | AT-SPI or xdotool |
| Click-outside | focus events + KWin | X11 pointer polling |
| Clipboard | wl-clipboard | xclip / xsel |
| Window opacity | Not supported | Fade-in animation |

On KDE Wayland, activate the optional KWin bridge after installation:

**System Settings → Window Management → KWin Scripts → check "TextPik Cursor Bridge" → Apply**

On other Wayland desktops, TextPik first asks AT-SPI for the selected text
geometry. If the application does not expose accessibility information it uses
the compositor adapter, and finally a safe screen-relative fallback. Enable the
desktop accessibility bus for the most accurate result on GNOME and other
non-KDE environments.

## Compatibility

Distribution support:

| Distro | Status |
|--------|--------|
| Arch / CachyOS / Manjaro | Primary target |
| Fedora KDE Spin | Supported |
| KDE neon / Kubuntu 24.04+ | AppImage, Flatpak or private-venv installer |
| openSUSE Tumbleweed KDE | Supported |
| Debian 13 | Native DEB with modular PySide6 packages |
| Ubuntu 24.04+ | AppImage, Flatpak or isolated per-user PySide6 environment |
| Fedora | Native RPM |
| CentOS Stream | AppImage recommended; desktop dependencies vary by release |
| Alpine Linux | Supported through `apk` |
| Void Linux | Supported through `xbps-install` |
| Slackware | Community support; SlackBuilds required for desktop tools |

Desktop support:

| Desktop | X11 | Wayland |
|---------|-----|---------|
| KDE Plasma | Full | Full with optional KWin cursor bridge |
| GNOME | Full | Supported with safe popup-position fallback |
| Cinnamon / MATE / XFCE | Full | Supported where the desktop offers Wayland |
| Sway / Hyprland / other wlroots | N/A | Supported with `wl-clipboard` and `wtype` |

Klipper actions are shown only in KDE. KDE Connect remains available on other
desktops when its D-Bus service or `kdeconnect-cli` is installed. Selection
monitoring uses X11 PRIMARY or the standard Wayland `wl-clipboard` protocol.

## Magnet y reproducción multimedia

- **Abrir magnet en cliente torrent** usa la asociación estándar
  `x-scheme-handler/magnet`, respetando el cliente predeterminado del escritorio.
- **Enviar magnet a servidor** admite Transmission RPC y qBittorrent Web API.
  Los servidores se administran en **Configuración → Integraciones**.
- **Abrir en reproductor local** usa primero la aplicación predeterminada para
  vídeo y degrada a MPV, VLC, Celluloid, Haruna o SMPlayer cuando es necesario.

Las solicitudes de red se ejecutan fuera del hilo gráfico, tienen tiempo límite
y solo se realizan al invocar explícitamente una acción.

## Packaging

- `packaging/install.sh`: portable per-user installation for Arch, Debian,
  Ubuntu, Fedora, CentOS, openSUSE, Alpine, Void and Slackware. Files are copied to
  `~/.local/share/textpik`, so the original checkout can be moved or deleted.
- `packaging/arch/PKGBUILD`: native Arch package with optional integrations.
- `packaging/debian`: Debian 13 source package metadata. Build it with
  `packaging/debian/build.sh`; resulting packages are written to `dist/`.
- `packaging/rpm/textpik.spec`: Fedora/RHEL-family RPM recipe. Build it from a
  committed tree with `packaging/rpm/build.sh`; packages are written to `dist/`.
- `packaging/io.github.pitydah.textpik.metainfo.xml`: AppStream metadata used
  by software centers and native packages.
- `packaging/flatpak/io.github.pitydah.textpik.json`: KDE/PySide Flatpak
  manifest with `wl-clipboard` bundled for primary-selection monitoring.
- `packaging/appimage/build-container.sh`: reproducible AppImage build on the
  Ubuntu 22.04 compatibility floor.
- `packaging/arch/build-container.sh`: clean Arch `makepkg` build.
- `packaging/flatpak/build.sh`: bundle build with optional install/self-check.

The source resolves assets from development checkouts, user installations,
system packages, Flatpak and PyInstaller/AppImage layouts.

## CLI mode

```bash
textpik run "Buscar en Google" "search query"
textpik run "Buscar en DuckDuckGo" "text to search"
```

## Configuration

Settings: `~/.config/textpik/settings.json`
Actions:  `~/.config/textpik/actions.json`
Local extensions: `~/.local/share/textpik/extensions/<id>/manifest.json`

The local extension format and permission model are documented in
[`docs/extensions.md`](docs/extensions.md).
Declarative automations are documented in
[`docs/automations.md`](docs/automations.md).
The lightweight core boundaries and popup performance budgets are documented in
[`docs/architecture.md`](docs/architecture.md).
The phased delivery status and remaining lightweight improvements are tracked in
[`docs/roadmap.md`](docs/roadmap.md).
Logs:     `~/.cache/textpik/textpik.log`

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
