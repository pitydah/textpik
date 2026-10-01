#!/usr/bin/env bash
set -euo pipefail

APP_NAME="textpik"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/$APP_NAME"
APP_DIR="$HOME/.local/share/$APP_NAME"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
KWIN_SCRIPT_SOURCE="$APP_DIR/kwin/textpik-cursor-bridge"
KWIN_SCRIPT_DEST="$HOME/.local/share/kwin/scripts/textpik-cursor-bridge"
KWIN_EFFECT_SOURCE="$PROJECT_DIR/native/kwin-effect"
KWIN_EFFECT_DEST="$HOME/.local/lib/qt6/plugins/kwin/effects"
QT_PLUGIN_PATH_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-textpik-qt-plugin-path.conf"

MISSING=()
RUNTIME_PYTHON="python3"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m  OK\033[0m  %s\n" "$*"; }
warn()  { printf "\033[1;33m WARN\033[0m  %s\n" "$*"; }

detect_pm() {
    for pm in pacman apt dnf zypper apk xbps-install slackpkg; do
        if command -v "$pm" &>/dev/null; then echo "$pm"; return 0; fi
    done
    echo "unknown"; return 1
}

PM=$(detect_pm) || { warn "No se detecto gestor de paquetes conocido. Instale las dependencias manualmente."; PM="none"; }
HAS_SUDO=false
command -v sudo &>/dev/null && HAS_SUDO=true

pkg_install() {
    local pkgs=("$@")
    [[ ${#pkgs[@]} -eq 0 ]] && return 0
    local privileged=()
    if [[ "$EUID" -eq 0 ]]; then
        privileged=()
    elif $HAS_SUDO; then
        privileged=(sudo)
    else
        privileged=()
    fi
    if [[ "$EUID" -eq 0 ]] || $HAS_SUDO; then
        case "$PM" in
            pacman) "${privileged[@]}" pacman -S --needed --noconfirm "${pkgs[@]}" 2>/dev/null ;;
            apt)    "${privileged[@]}" apt install -y "${pkgs[@]}" 2>/dev/null ;;
            dnf)    "${privileged[@]}" dnf install -y "${pkgs[@]}" 2>/dev/null ;;
            zypper) "${privileged[@]}" zypper install -y "${pkgs[@]}" 2>/dev/null ;;
            apk) "${privileged[@]}" apk add "${pkgs[@]}" 2>/dev/null ;;
            xbps-install) "${privileged[@]}" xbps-install -Sy "${pkgs[@]}" 2>/dev/null ;;
            slackpkg) "${privileged[@]}" slackpkg install "${pkgs[@]}" 2>/dev/null ;;
        esac
    else
        warn "Sin sudo. Instalacion manual:"
        case "$PM" in
            pacman) echo "  sudo pacman -S --needed ${pkgs[*]}" ;;
            apt)    echo "  sudo apt install ${pkgs[*]}" ;;
            dnf)    echo "  sudo dnf install ${pkgs[*]}" ;;
            zypper) echo "  sudo zypper install ${pkgs[*]}" ;;
            apk) echo "  sudo apk add ${pkgs[*]}" ;;
            xbps-install) echo "  sudo xbps-install -Sy ${pkgs[*]}" ;;
            slackpkg) echo "  sudo slackpkg install ${pkgs[*]}" ;;
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
        apk) try_install "PySide6" py3-pyside6 ;;
        xbps-install) try_install "PySide6" python3-PySide6 ;;
        slackpkg) warn "Slackware: PySide6 se instalará en un entorno privado." ;;
        apt)
            if pkg_install python3-pyside6 && python3 -c "import PySide6" &>/dev/null; then
                ok "PySide6"; return 0
            fi
            if pkg_install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtdbus \
                && python3 -c "import PySide6" &>/dev/null; then
                ok "PySide6 (modular)"; return 0
            fi
            warn "PySide6 no disponible vía apt. Creando un entorno privado."
            ;;
        *) warn "Gestor desconocido. Creando un entorno privado." ;;
    esac

    if python3 -c "import PySide6" &>/dev/null; then return 0; fi

    info "Instalando PySide6 en $APP_DIR/venv..."
    if ! python3 -m venv "$APP_DIR/venv" 2>/dev/null; then
        [[ "$PM" == "apt" ]] && pkg_install python3-venv || true
        python3 -m venv "$APP_DIR/venv"
    fi
    if "$APP_DIR/venv/bin/pip" install "PySide6>=6.5,<6.12"; then
        RUNTIME_PYTHON="$APP_DIR/venv/bin/python"
        ok "PySide6 (entorno privado)"
    else
        warn "PySide6 no se pudo instalar. Instálalo manualmente."
        MISSING+=("PySide6 (venv)")
        return 1
    fi
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
        apk)    try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        xbps-install) try_install "wl-clipboard" wl-clipboard
                try_install "xdotool" xdotool
                try_install "xdg-utils" xdg-utils ;;
        slackpkg) warn "Slackware: instala wl-clipboard y xdotool desde SlackBuilds.org." ;;
        *)      warn "Instala manualmente: wl-clipboard xdotool xdg-utils" ;;
    esac
}

install_optional_deps() {
    # Paquetes opcionales: mejoran funcionalidad pero no bloquean
    case "$PM" in
        pacman)
            try_install "AT-SPI (selección precisa)" python-gobject at-spi2-core
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "wtype (Wayland)" wtype 2>/dev/null || true
            try_install "ydotool (Wayland fallback)" ydotool 2>/dev/null || true
            ;;
        apt)
            try_install "AT-SPI (selección precisa)" python3-gi gir1.2-atspi-2.0
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "wtype (Wayland)" wtype 2>/dev/null || true
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
        dnf)
            try_install "AT-SPI (selección precisa)" python3-gobject at-spi2-core
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "wtype (Wayland)" wtype 2>/dev/null || true
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
        zypper)
            try_install "AT-SPI (selección precisa)" python3-gobject at-spi2-core
            try_install "xclip (X11)" xclip
            try_install "xsel (X11 alt)" xsel
            try_install "konsole" konsole
            try_install "wtype (Wayland)" wtype 2>/dev/null || true
            try_install "ydotool (Wayland)" ydotool 2>/dev/null || true
            ;;
        apk|xbps-install)
            try_install "xclip (X11)" xclip 2>/dev/null || true
            try_install "wtype (Wayland)" wtype 2>/dev/null || true
            ;;
        slackpkg)
            warn "Integraciones opcionales disponibles mediante SlackBuilds.org"
            ;;
    esac
}

install_binary() {
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR/src"
    cp "$PROJECT_DIR/src/textpik.py" "$APP_DIR/src/textpik.py"
    cp -a "$PROJECT_DIR/src/textpik_core" "$APP_DIR/src/textpik_core"
    cp -a "$PROJECT_DIR/assets" "$APP_DIR/assets"
    cp -a "$PROJECT_DIR/kwin" "$APP_DIR/kwin"
    if [[ -d "$PROJECT_DIR/native" ]]; then
        cp -a "$PROJECT_DIR/native" "$APP_DIR/native"
    fi
    mkdir -p "$APP_DIR/scripts"
    cp "$PROJECT_DIR/scripts/check_placement_backend.py" "$APP_DIR/scripts/"
    cp "$PROJECT_DIR/LICENSE" "$PROJECT_DIR/README.md" "$APP_DIR/"
}

install_launcher() {
    mkdir -p "$BIN_DIR"
    cat > "$BIN_PATH" << SCRIPT
#!/usr/bin/env bash
exec "$RUNTIME_PYTHON" "$APP_DIR/src/textpik.py" "\$@"
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
GenericName=Selected Text Actions
Exec=$BIN_PATH
Icon=$APP_DIR/assets/app/textpik.svg
Terminal=false
Categories=Utility;TextTools;
Keywords=text;selection;clipboard;actions;search;translate;
StartupNotify=false
StartupWMClass=textpik
X-GNOME-UsesNotifications=true
EOF
    ok "Desktop entry: $user_desktop"
    mkdir -p "$HOME/.local/share/metainfo"
    cp "$PROJECT_DIR/packaging/io.github.pitydah.textpik.metainfo.xml" \
        "$HOME/.local/share/metainfo/io.github.pitydah.textpik.metainfo.xml"
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
    case "${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}" in
        *KDE*|*kde*|*Plasma*|*plasma*) ;;
        *) info "Entorno no KDE: se omite el puente de cursor KWin."; return ;;
    esac
    if [[ ! -d "$KWIN_SCRIPT_SOURCE" ]]; then
        warn "Script KWin no encontrado en $KWIN_SCRIPT_SOURCE"
        return
    fi
    mkdir -p "$KWIN_SCRIPT_DEST"
    cp -a "$KWIN_SCRIPT_SOURCE/." "$KWIN_SCRIPT_DEST/"
    ok "KWin bridge copiado"

    local qdbus_command=""
    if command -v qdbus6 &>/dev/null; then
        qdbus_command="qdbus6"
    elif command -v qdbus &>/dev/null; then
        qdbus_command="qdbus"
    fi
    if [[ -n "$qdbus_command" ]]; then
        command -v kwriteconfig6 &>/dev/null && \
            kwriteconfig6 --file kwinrc --group Plugins \
                --key textpik-cursor-bridgeEnabled true
        "$qdbus_command" org.kde.KWin /Scripting \
            org.kde.kwin.Scripting.unloadScript \
            "textpik-cursor-bridge" 2>/dev/null || true
        local script_id
        script_id=$("$qdbus_command" org.kde.KWin /Scripting \
            org.kde.kwin.Scripting.loadScript \
            "$KWIN_SCRIPT_DEST/contents/code/main.js" \
            "textpik-cursor-bridge" 2>/dev/null || true)
        if [[ "$script_id" =~ ^[0-9]+$ ]] && \
           "$qdbus_command" org.kde.KWin "/Scripting/Script${script_id}" \
            org.kde.kwin.Script.run 2>/dev/null; then
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

install_kwin_placement_effect() {
    case "${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}" in
        *KDE*|*kde*|*Plasma*|*plasma*) ;;
        *) info "Entorno no KDE: se omite el backend de placement."; return ;;
    esac

    if [[ ! -d "$KWIN_EFFECT_SOURCE" ]]; then
        warn "Fuentes del efecto KWin no encontradas en $KWIN_EFFECT_SOURCE"
        info "TextPik funciona igual; el popup queda sin placement verificado."
        return
    fi

    # El efecto es opcional: si falta cualquier dependencia de compilacion se
    # omite y TextPik arranca igual en modo degradado y explicito.
    local missing_build=()
    command -v cmake &>/dev/null || missing_build+=("cmake")
    command -v ninja &>/dev/null || command -v make &>/dev/null || missing_build+=("ninja-build")
    command -v c++ &>/dev/null || missing_build+=("gcc-c++")
    [[ -f /usr/include/kwin/effect/effect.h ]] || missing_build+=("kwin-dev")
    [[ -d /usr/include/KF6/KCoreAddons ]] || missing_build+=("kf6-kcoreaddons-dev")
    [[ -d /usr/include/KF6/KConfigCore ]] || missing_build+=("kf6-kconfig-dev")
    [[ -d /usr/include/KF6/KWindowSystem ]] || missing_build+=("kf6-kwindowsystem-dev")

    if (( ${#missing_build[@]} > 0 )); then
        warn "Faltan dependencias para compilar el efecto: ${missing_build[*]}"
        info "TextPik funciona igual; solo se pierde el placement verificado en Plasma."
        info "Instalalas y volve a correr este instalador para activarlo."
        return
    fi

    local build_dir
    build_dir="$(mktemp -d "${TMPDIR:-/tmp}/textpik-kwin-effect.XXXXXX")"
    local generator="Ninja"
    command -v ninja &>/dev/null || generator="Unix Makefiles"

    if cmake -S "$KWIN_EFFECT_SOURCE" -B "$build_dir" -G "$generator" \
            -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 && \
       cmake --build "$build_dir" >/dev/null 2>&1; then
        mkdir -p "$KWIN_EFFECT_DEST"
        cp "$build_dir/textpik-placement.so" "$KWIN_EFFECT_DEST/"
        ok "Efecto KWin compilado e instalado"

        # Verificacion ABI + D-Bus antes de darlo por bueno.
        if [[ -x "$build_dir/textpik-verify-effect" ]]; then
            if "$build_dir/textpik-verify-effect" \
                    "$build_dir/textpik-placement.so" >/dev/null 2>&1; then
                ok "Efecto verificado contra la libkwin instalada"
            else
                warn "La verificacion del efecto fallo."
                "$build_dir/textpik-verify-effect" \
                    "$build_dir/textpik-placement.so" || true
            fi
        fi
    else
        warn "No se pudo compilar el efecto KWin."
        info "TextPik funciona igual; el popup queda sin placement verificado."
        rm -rf "$build_dir"
        return
    fi
    rm -rf "$build_dir"

    # KWin no agrega rutas de plugin de usuario y Qt solo mira /usr/lib/qt6/plugins,
    # asi que el directorio tiene que exponerse a la sesion.
    mkdir -p "$(dirname "$QT_PLUGIN_PATH_CONF")"
    cat > "$QT_PLUGIN_PATH_CONF" <<EOF
# Generado por TextPik: expone el directorio de plugins Qt del usuario para que
# KWin encuentre el efecto de placement. Borra este archivo para desactivarlo.
QT_PLUGIN_PATH=$HOME/.local/lib/qt6/plugins
EOF
    ok "QT_PLUGIN_PATH configurado para la sesion"

    info "KWin carga los efectos solo al arrancar: cerra sesion y volve a entrar."
    info "Despues verifica con:"
    info "  python3 $APP_DIR/scripts/check_placement_backend.py"
}

main() {
    info "Instalando TextPik para escritorios Linux..."

    install_required_deps
    install_optional_deps
    install_binary
    install_pyside6
    install_launcher
    install_desktop_entry
    install_autostart
    install_kwin_bridge
    install_kwin_placement_effect

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
