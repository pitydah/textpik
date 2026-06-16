# Changelog

## v0.3.0 — 2026-06-15 (Sprint 2 + pulido)

### Nuevas acciones
- Transformaciones de texto: mayusculas, minusculas, capitalizar, quitar saltos, contar palabras/caracteres/lineas
- KDE Connect: enviar texto al movil via D-Bus (copia al portapapeles + sendClipboard)
- Klipper: guardar texto en historial (setClipboardContents) y mostrar menu de acciones (showKlipperManuallyInvokeActionMenu)

### Contexto inteligente
- Deteccion automatica del tipo de texto: URL, email, IP, numero, codigo, texto plano
- Las acciones de busqueda solo aparecen cuando el texto es una URL
- Las acciones de codigo/terminal solo aparecen cuando el texto parece codigo
- Configurable desde Ajustes → Comportamiento

### Correcciones
- Toast de notificaciones arreglado (referencia tray_icon → tray)
- 7 ajustes que se perdian al guardar: sticky_popup, show_numeric_badges, enable_global_hotkey, app_language, blocked_activities_enabled, blocked_activities, context_aware
- Fix NameError potencial en request_cursor_update() cuando values vacio
- Directorio duplicado textpik/textpik/ eliminado
- enable_global_hotkey ahora respeta el checkbox de configuracion
- blocked_activities implementado: comprueba actividad Plasma via D-Bus
- Colores de boton del popup ahora se usan desde los ajustes (ya no hardcodeados)
- Badges numericos (1-9) implementados en los iconos
- Modo sticky implementado: popup no se cierra al clic fuera, solo con Escape o accion
- Todos los except Exception: pass ahora loguean el error
- Codigo muerto _call_klipper eliminado
- PKGBUILD actualizado de selectxt a textpik

## v0.2.0 — 2026-06-15

### Settings redisenados
- QTabWidget con 6 pestañas: Apariencia, Comportamiento, Filtros, Wayland, Diagnostico, Acciones
- Swatches visuales de color (QPushButton con el color real + QColorDialog)
- 7 ajustes nuevos con UI: show_numeric_badges, sticky_popup, enable_global_hotkey, app_language, context_aware, blocked_activities_enabled, blocked_activities

## v0.1.3 — 2026-06-14 (Sprint 1 estabilidad)

- Bug #1: CLI guard para print y ollama
- Bug #2: null check en cursor_bridge
- Bug #3: Klipper D-Bus se reactiva tras pause
- Bug #4: fallback wl-paste → Qt clipboard en _read_selection_text
- Rendimiento: RSS ~83 MB, PSS ~64 MB (-57% vs original)

## v0.1.2 — 2026-06-14

- install.sh robusto: paquetes REQUIRED vs OPTIONAL separados, tracking de fallos (MISSING[])
- Binario auto-detecta ruta en install time

## v0.1.1 — 2026-06-14

- Shebang #!/usr/bin/env python3
- README multi-distro, mensajes multi-gestor en codigo

## v0.1 — 2026-06-14

Release inicial desde selectxt v0.4.

- Popup action bar on text selection
- 13 acciones: copiar, pegar, abrir URL, Google, YouTube, Maps, ChatGPT, DeepSeek, DuckDuckGo, terminal, imprimir, traducir, Ollama
- X11 via QClipboard.Selection, Wayland via wl-paste --primary
- KDE KWin cursor bridge para posicion del cursor
- Bandeja de sistema con pausar/reanudar, configuracion, diagnosticos
- Editor visual de acciones (anadir/editar/eliminar/reordenar)
- Atajos numericos 1-9
- Temas predefinidos (Custom, Claro, Oscuro, OLED)
- Cierre al clic fuera (focusOutEvent + X11Pointer polling + KWin notifyClickOutside)
- KWin bridge para Wayland
