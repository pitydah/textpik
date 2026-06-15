# TextPik

Popup action bar on text selection for **KDE Plasma 6** (Wayland & X11).

Select text anywhere and a customizable action bar appears at your cursor —
copy, search, translate, open links, and more with one click.
<p align="center">
  <img src="assets/logo.png" width="160" alt="TextPik logo">
</p>

## Features

- 13 built-in actions: copy, paste, open URL, Google, YouTube, Maps,
  ChatGPT, DeepSeek, DuckDuckGo, terminal, print, translate, Ollama
- KDE Plasma integration: Klipper D-Bus, KWin cursor bridge, system tray
- Wayland native support via KWin
- Click-outside-to-close
- Configurable settings with theme presets (Light, Dark, OLED)
- Numeric shortcuts 1-9
- Spanish / English

## Requirements

- **KDE Plasma 6** (Wayland or X11)
- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- `wl-clipboard` (Wayland) or `xclip`/`xsel` (X11)
- `xdotool`

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
| Cursor position | KWin bridge script | xdotool (native) |
| Click-outside | focus events + KWin | X11 pointer polling |
| Clipboard | wl-clipboard | xclip / xsel |
| Window opacity | Not supported | Fade-in animation |

On Wayland, activate the KWin bridge after installation:

**System Settings → Window Management → KWin Scripts → check "TextPik Cursor Bridge" → Apply**

Without this, cursor positioning falls back to screen center.

## Compatibility

Supported and tested on KDE Plasma 6:

| Distro | Status |
|--------|--------|
| Arch / CachyOS / Manjaro | Primary target |
| Fedora KDE Spin | Supported |
| KDE neon / Kubuntu 24.04+ | Supported |
| Debian 13 KDE | Supported |
| openSUSE Tumbleweed KDE | Supported |

Non-KDE environments (GNOME, XFCE, Sway, Hyprland) are **not supported**.
The app depends on KWin for cursor positioning and popup behavior.

## CLI mode

```bash
textpik run "Google" "search query"
textpik run "Copiar" "text to copy"
```

## Configuration

Settings: `~/.config/textpik/settings.json`
Actions:  `~/.config/textpik/actions.json`
Logs:     `~/.cache/textpik/textpik.log`

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
