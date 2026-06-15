# TextPik
<p align="center">
  <img src="assets/logo.png" width="160" alt="TextPik logo">
</p>

Popup action bar on text selection for Linux (KDE Plasma). Select any text
and a customizable action bar appears at your cursor.

## Features

- 13 built-in actions (copy, paste, open URL, search engines, AI, terminal, print)
- KDE Plasma integration (Klipper, KWin cursor bridge)
- Wayland native support
- Configurable via `~/.config/textpik/settings.json`
- System tray with pause/resume

## Requirements

- Python 3.10+ with PySide6
- wl-clipboard (Wayland) or xclip/xsel (X11)
- xdotool for cursor position
- KDE Plasma (optional, for KWin integration)

## Quick Start

```bash
git clone https://github.com/pitydah/textpik.git
cd textpik
/usr/bin/python3 src/textpik.py
```

## CLI Mode

```bash
/usr/bin/python3 src/textpik.py run "Copiar" "text to copy"
/usr/bin/python3 src/textpik.py run "Google" "search query"
```

## Settings

Settings are stored at `~/.config/textpik/settings.json`. Edit manually or use
the tray icon > Settings dialog.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
