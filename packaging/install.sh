#!/usr/bin/env bash
set -euo pipefail

APP_NAME="textpik"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_SCRIPT="$SCRIPT_DIR/run.sh"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/$APP_NAME"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
KWIN_SCRIPT_SOURCE="$PROJECT_DIR/kwin/textpik-cursor-bridge"
KWIN_SCRIPT_DEST="$HOME/.local/share/kwin/scripts/textpik-cursor-bridge"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m  OK\033[0m  %s\n" "$*"; }
warn()  { printf "\033[1;33m WARN\033[0m  %s\n" "$*"; }

detect_pm() {
    for pm in pacman apt dnf zypper; do
        if command -v "$pm" &>/dev/null; then echo "$pm"; return 0; fi
    done
    echo "unknown"; return 1
}

PM=$(detect_pm)
HAS_SUDO=false
command -v sudo &>/dev/null && HAS_SUDO=true

pkg_install() {
    local pkgs=("$@")
    [[ ${#pkgs[@]} -eq 0 ]] && return 0
    if $HAS_SUDO; then
        case "$PM" in
            pacman) sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
            apt)    sudo apt install -y "${pkgs[@]}" ;;
            dnf)    sudo dnf install -y "${pkgs[@]}" ;;
            zypper) sudo zypper install -y "${pkgs[@]}" ;;
        esac
    else
        warn "Sin sudo. Instalacion manual:"
        case "$PM" in
            pacman) echo "  sudo pacman -S --needed ${pkgs[*]}" ;;
            apt)    echo "  sudo apt install ${pkgs[*]}" ;;
            dnf)    echo "  sudo dnf install ${pkgs[*]}" ;;
            zypper) echo "  sudo zypper install ${pkgs[*]}" ;;
        esac
    fi
}

install_pyside6() {
    if python3 -c "import PySide6" &>/dev/null; then return 0; fi

    local pm_pkg=""
    case "$PM" in
        pacman) pm_pkg="pyside6" ;;
        apt)    pm_pkg="python3-pyside6" ;;
        dnf)    pm_pkg="python3-pyside6" ;;
        zypper) pm_pkg="python3-pyside6" ;;
    esac

    if [[ -n "$pm_pkg" ]]; then
        if pkg_install "$pm_pkg" && python3 -c "import PySide6" &>/dev/null; then
            return 0
        fi
        warn "PySide6 no disponible via paquetes. Probando pip."
    fi

    info "Instalando PySide6 via pip..."
    pip3 install --user PySide6 2>/dev/null || true
}

install_deps() {
    local pkgs=()
    case "$PM" in
        pacman) pkgs=(wl-clipboard xdotool xdg-utils) ;;
        apt)    pkgs=(wl-clipboard xdotool xdg-utils) ;;
        dnf)    pkgs=(wl-clipboard xdotool xdg-utils) ;;
        zypper) pkgs=(wl-clipboard xdotool xdg-utils) ;;
        *)      warn "Gestor desconocido. Instala manualmente: wl-clipboard xdotool xdg-utils" ;;
    esac
    [[ ${#pkgs[@]} -gt 0 ]] && pkg_install "${pkgs[@]}"
    install_pyside6
}

install_binary() {
    mkdir -p "$BIN_DIR"
    cat > "$BIN_PATH" << EOF
#!/usr/bin/env bash
exec python3 "$PROJECT_DIR/src/textpik.py" "\$@"
EOF
    chmod +x "$BIN_PATH"
    ok "Comando instalado: $BIN_PATH"
}

install_desktop_entry() {
    local user_desktop="$HOME/.local/share/applications/$APP_NAME.desktop"
    mkdir -p "$HOME/.local/share/applications"
    cat > "$user_desktop" << EOF
[Desktop Entry]
Type=Application
Name=TextPik
Comment=Popup action bar on text selection
Exec=$BIN_PATH
Icon=$PROJECT_DIR/assets/app/textpik.svg
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
    ok "Desktop entry: $user_desktop"
}

install_autostart() {
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/$APP_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=TextPik
Exec=$BIN_PATH
Terminal=false
X-KDE-autostart-phase=2
NoDisplay=true
EOF
    ok "Autostart: $AUTOSTART_DIR/$APP_NAME.desktop"
}

install_kwin_bridge() {
    if [[ ! -d "$KWIN_SCRIPT_SOURCE" ]]; then
        warn "Script KWin no encontrado en $KWIN_SCRIPT_SOURCE"
        return
    fi
    mkdir -p "$KWIN_SCRIPT_DEST"
    cp -a "$KWIN_SCRIPT_SOURCE/." "$KWIN_SCRIPT_DEST/"
    ok "KWin bridge: $KWIN_SCRIPT_DEST"
    info "Activalo en Preferencias del sistema > KWin Scripts"
}

main() {
    info "Instalando TextPik..."
    chmod +x "$RUN_SCRIPT"
    install_deps
    install_binary
    install_desktop_entry
    install_autostart
    install_kwin_bridge
    ok "Instalacion completa."
    info "Ejecuta: textpik"
    info "O busca 'TextPik' en el menu de aplicaciones"
}

main "$@"
