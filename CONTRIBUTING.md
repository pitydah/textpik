# Contributing to TextPik

## Getting Started

1. Fork the repository
2. Clone your fork
3. Create a branch: `git checkout -b feature/my-feature`
4. Make changes and verify: `python3 -m py_compile src/textpik.py`
5. Commit and push
6. Open a Pull Request

## Adding Actions

Edit `DEFAULT_ACTIONS` in `src/textpik.py`:
- `name`: display name
- `icon`: SVG filename in `assets/actions/`
- `cmd`: command string or keyword (copy, paste, open-url, terminal, print, ollama)

## License

All contributions are licensed under GPL v3.0.
