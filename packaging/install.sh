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

MISSING=()

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
            pacman) sudo pacman -S --needed --noconfirm "${pkgs[@]}" 2>/dev/null ;;
            apt)    sudo apt install -y "${pkgs[@]}" 2>/dev/null ;;
            dnf)    sudo dnf install -y "${pkgs[@]}" 2>/dev/null ;;
            zypper) sudo zypper install -y "${pkgs[@]}" 2>/dev/null ;;
        esac
    else
        warn "Sin sudo. Instalacion manual:"
        case "$PM" in
            pacman) echo "  sudo pacman -S --needed ${pkgs[*]}" ;;
            apt)    echo "  sudo apt install ${pkgs[*]}" ;;
            dnf)    echo "  sudo dnf install ${pkgs[*]}" ;;
            zypper) echo "  sudo zypper install ${pkgs[*]}" ;;
        esac
        return 1
    fi
}

try_install() {
    local desc="$1"; shift
    if pkg_install "$@"; then
        ok "$desc"
    else
        warn "$desc — no disponible, continuando sin ello"
        MISSING+=("$desc")
    fi
}

install_pyside6() {
    if python3 -c "import PySide6" &>/dev/null; then return 0; fi

    case "$PM" in
        pacman) try_install "PySide6" pyside6 ;;
        dnf)    try_install "PySide6" python3-pyside6 ;;
        zypper) try_install "PySide6" python3-pyside6 ;;
        apt)
            if pkg_install python3-pyside6 && python3 -c "import PySide6" &>/dev/null; then
                ok "PySide6"; return 0
            fi
            if pkg_install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtdbus \
                && python3 -c "import PySide6" &>/dev/null; then
                ok "PySide6 (modular)"; return 0
            fi
            warn "PySide6 no disponible via apt. Probando pip."
            ;;
        *) warn "Gestor desconocido. Probando pip." ;;
    esac

    if python3 -c "import PySide6" &>/dev/null; then return 0; fi

    info "Instalando PySide6 via pip..."
    pip3 install --user PySide6 2>/dev/null || {
        warn "PySide6 no se pudo instalar. Instalalo manualmente."
        MISSING+=("PySide6 (pip)")
    }
}

install_required_deps() {
    # Paquetes esenciales: sin ellos la app no funciona
    case "$PM" in
        pacman) try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        apt)    try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        dnf)    try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        zypper) try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        *)      warn "Instala manualmente: wl-clipboard xdotool xdg-utils" ;;
    esac
}

install_optional_deps() {
    # Paquetes opcionales: mejoran funcionalidad pero no bloquean
    case "$PM" in
        pacman)
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || \
                warn "ydotool no disponible (solo AUR). Paste en Wayland usara wtype como fallback."
            ;;
        apt)
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
        dnf)
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
        zypper)
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
    esac
}

install_binary() {
    mkdir -p "$BIN_DIR"
    cat > "$BIN_PATH" << SCRIPT
#!/usr/bin/env bash
exec python3 "$PROJECT_DIR/src/textpik.py" "\$@"
SCRIPT
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
    ok "KWin bridge copiado"

    if command -v qdbus &>/dev/null; then
        if qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript \
            "textpik-cursor-bridge" 2>/dev/null && \
           qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.start 2>/dev/null; then
            ok "KWin bridge activado"
        else
            info "No se pudo activar automaticamente."
            info "  Ve a: Preferencias del sistema > Administracion de ventanas"
            info "  Scripts KWin > activa 'TextPik Cursor Bridge'"
        fi
    else
        info "qdbus no encontrado (instala qt6-tools)."
        info "  Activa manualmente: Preferencias del sistema > Administracion de ventanas"
        info "  Scripts KWin > activa 'TextPik Cursor Bridge'"
    fi
}

main() {
    info "Instalando TextPik para KDE Plasma..."

    chmod +x "$RUN_SCRIPT"
    install_required_deps
    install_optional_deps
    install_pyside6
    install_binary
    install_desktop_entry
    install_autostart
    install_kwin_bridge

    echo ""
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        warn "Paquetes no instalados: ${MISSING[*]}"
        info "La app funciona igual, pero algunas acciones estaran limitadas."
    fi
    ok "Instalacion completa."
    info "Ejecuta: textpik"
    info "O busca 'TextPik' en el menu de aplicaciones"
}

main "$@"
