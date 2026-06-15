#!/usr/bin/env bash
set -euo pipefail

APP_NAME="TextPik"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DESKTOP_FILE="$SCRIPT_DIR/$APP_NAME.desktop"
RUN_SCRIPT="$SCRIPT_DIR/run.sh"
COMPILED_BINARY="$SCRIPT_DIR/textpik"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
KWIN_SCRIPT_SOURCE="$PROJECT_DIR/kwin/textpik-cursor-bridge"
KWIN_SCRIPT_DEST="$HOME/.local/share/kwin/scripts/textpik-cursor-bridge"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m  OK\033[0m  %s\n" "$*"; }
warn()  { printf "\033[1;33m WARN\033[0m  %s\n" "$*"; }
err()   { printf "\033[1;31mFAIL\033[0m  %s\n" "$*"; }

detect_pkg_manager() {
    for pm in pacman apt dnf zypper; do
        if command -v "$pm" &>/dev/null; then
            echo "$pm"
            return 0
        fi
    done
    echo "unknown"
    return 1
}

PM=$(detect_pkg_manager)
NEEDS_PKEXEC=false
NEEDS_SUDO=false
if command -v sudo &>/dev/null; then
    NEEDS_SUDO=true
elif command -v pkexec &>/dev/null; then
    NEEDS_PKEXEC=true
fi

pkg_install() {
    local packages=("$@")
    if [[ ${#packages[@]} -eq 0 ]]; then
        return 0
    fi

    if $NEEDS_SUDO; then
        case "$PM" in
            pacman) sudo pacman -S --needed --noconfirm "${packages[@]}" ;;
            apt)    sudo apt install -y "${packages[@]}" ;;
            dnf)    sudo dnf install -y "${packages[@]}" ;;
            zypper) sudo zypper install -y "${packages[@]}" ;;
        esac
    elif $NEEDS_PKEXEC; then
        local cmd
        case "$PM" in
            pacman) cmd="pacman -S --needed --noconfirm" ;;
            apt)    cmd="apt install -y" ;;
            dnf)    cmd="dnf install -y" ;;
            zypper) cmd="zypper install -y" ;;
        esac
        pkexec bash -c "$cmd ${packages[*]}"
    else
        warn "No se tiene sudo ni pkexec. Instalacion manual requerida:"
        case "$PM" in
            pacman) echo "  sudo pacman -S --needed ${packages[*]}" ;;
            apt)    echo "  sudo apt install -y ${packages[*]}" ;;
            dnf)    echo "  sudo dnf install -y ${packages[*]}" ;;
            zypper) echo "  sudo zypper install -y ${packages[*]}" ;;
        esac
        return 1
    fi
}

install_pyside6() {
    if python3 -c "import PySide6" &>/dev/null; then
        return 0
    fi

    local pm_pkg=""
    local pip_pkg="PySide6"

    case "$PM" in
        pacman) pm_pkg="pyside6" ;;
        apt)    pm_pkg="python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets" ;;
        dnf)    pm_pkg="python3-pyside6" ;;
        zypper) pm_pkg="python3-pyside6" ;;
    esac

    if [[ -n "$pm_pkg" ]]; then
        if pkg_install $pm_pkg && python3 -c "import PySide6" &>/dev/null; then
            return 0
        fi
        warn "PySide6 no quedo disponible via paquetes del sistema; probando pip."
    fi

    info "Instalando PySide6 via pip..."
    if command -v pip3 &>/dev/null; then
        if $NEEDS_SUDO; then
            sudo pip3 install --break-system-packages "$pip_pkg" 2>/dev/null ||
            sudo pip3 install "$pip_pkg"
        elif $NEEDS_PKEXEC; then
            pkexec pip3 install --break-system-packages "$pip_pkg" 2>/dev/null ||
            pkexec pip3 install "$pip_pkg"
        else
            pip3 install --user "$pip_pkg"
        fi
    fi
}

install_deps() {
    local pkgs=()

    case "$PM" in
        pacman)
            pkgs=(wl-clipboard xdotool ydotool wtype konsole xdg-utils python-dbus)
            ;;
        apt)
            pkgs=(wl-clipboard xdotool ydotool wtype konsole xdg-utils python3-dbus)
            ;;
        dnf)
            pkgs=(wl-clipboard xdotool ydotool wtype konsole xdg-utils python3-dbus)
            ;;
        zypper)
            pkgs=(wl-clipboard xdotool ydotool wtype konsole xdg-utils python3-dbus)
            ;;
        *)
            warn "Gestor de paquetes no reconocido. Intentando con pip..."
            pkgs=()
            ;;
    esac

    if [[ -x "$COMPILED_BINARY" ]]; then
        info "Ejecutable compilado detectado; se omite PySide6."
    else
        install_pyside6
    fi

    if [[ ${#pkgs[@]} -gt 0 ]]; then
        pkg_install "${pkgs[@]}" || warn "Algunos paquetes no se instalaron."
    fi
}

install_desktop_entry() {
    local user_desktop="$HOME/.local/share/applications/$APP_NAME.desktop"
    mkdir -p "$HOME/.local/share/applications"
    cat > "$user_desktop" << EOF
[Desktop Entry]
Type=Application
Name=textpik
Comment=Barra emergente de acciones al seleccionar texto
Exec=$RUN_SCRIPT
Icon=$PROJECT_DIR/assets/app/textpik.svg
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
    ok "Registrado $user_desktop"
}

install_autostart() {
    mkdir -p "$AUTOSTART_DIR"
    local autostart_file="$AUTOSTART_DIR/$APP_NAME.desktop"
    cat > "$autostart_file" << EOF
[Desktop Entry]
Type=Application
Name=textpik
Comment=Barra emergente de acciones al seleccionar texto
Exec=$RUN_SCRIPT
Terminal=false
X-KDE-autostart-phase=2
NoDisplay=true
EOF
    ok "Autostart creado en $autostart_file"
}

install_kwin_bridge() {
    if [[ ! -d "$KWIN_SCRIPT_SOURCE" ]]; then
        warn "No se encuentra $KWIN_SCRIPT_SOURCE. Omitiendo puente KWin."
        return
    fi

    mkdir -p "$KWIN_SCRIPT_DEST"
    cp -a "$KWIN_SCRIPT_SOURCE/." "$KWIN_SCRIPT_DEST/"
    ok "Puente KWin instalado en $KWIN_SCRIPT_DEST"
    info "En Wayland puede requerir activar el script en KWin Scripts o reiniciar sesion."
}

make_executable() {
    chmod +x "$RUN_SCRIPT"
    ok "run.sh ejecutable"
}

main() {
    info "Instalando $APP_NAME..."
    make_executable
    install_deps
    install_desktop_entry
    install_autostart
    install_kwin_bridge
    ok "Instalacion completada."
    info "Ejecuta: $RUN_SCRIPT"
    info "O desde el menu de aplicaciones: $APP_NAME"
}

main "$@"
