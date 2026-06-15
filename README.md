# TextPik

Popup action bar on text selection for Linux (KDE Plasma).

Select any text and a customizable action bar appears at your cursor — copy,
search, translate, open links, and more with one click.

## Features

- 13 built-in actions: copy, paste, open URL, Google, YouTube, Maps,
  ChatGPT, DeepSeek, DuckDuckGo, terminal, print, translate, Ollama
- KDE Plasma integration: Klipper, KWin cursor bridge, system tray
- Wayland native support
- Click-outside-to-close
- Configurable settings dialog with theme presets (Light, Dark, OLED)
- Numeric shortcuts 1-9
- Sticky popup mode
- Spanish / English

## Requirements

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- `wl-clipboard` (Wayland) or `xclip`/`xsel` (X11)
- `xdotool`
- KDE Plasma (recommended, for KWin integration)

## Installation

```bash
git clone https://github.com/pitydah/textpik.git
cd textpik
chmod +x packaging/install.sh
./packaging/install.sh
```

This installs system dependencies, creates a `.desktop` entry, sets up
autostart, and installs the KWin cursor bridge script.

## Quick run (no install)

```bash
git clone https://github.com/pitydah/textpik.git
cd textpik
python3 src/textpik.py
```

## CLI mode

```bash
python3 src/textpik.py run "Google" "search query"
python3 src/textpik.py run "Copiar" "text to copy"
```

## Configuration

Settings and actions are stored in `~/.config/textpik/`:

- `settings.json` — appearance, behavior, language, blocked apps
- `actions.json` — action list (editable via Settings dialog)

Logs: `~/.cache/textpik/textpik.log`

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
