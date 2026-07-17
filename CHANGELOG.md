# Changelog

## Unreleased

- Acciones contextuales para abrir magnet con el cliente torrent predeterminado,
  enviarlos a servidores Transmission/qBittorrent configurables y reproducir
  URLs multimedia con la aplicación local predeterminada o un fallback conocido.
- Ciclo determinista del popup: permanece ocho segundos sin interacción, un clic
  externo confirmado lo cierra de inmediato incluso durante la inmunidad inicial,
  y los vaciados transitorios de PRIMARY nunca adelantan su cierre. El posicionador
  prueba los cuatro cuadrantes inmediatos del cursor con una separación menor.
- Cerrar «Más acciones» mediante un clic exterior cierra también su barra
  propietaria, en lugar de dejarla esperando el temporizador de ocho segundos.
- Nuevas acciones «Preguntar a Claude» y «Preguntar a Gemini», con integración
  no destructiva para perfiles existentes y SVG monocromáticos de marca sin fondo.
- Retardo adaptativo de selección y rechazo de rangos colapsados.
- Diagnóstico de proveedores de anclaje, preferencia de posición y composición
  opcional en dos filas.
- Variantes de acciones con modificadores que conservan permisos e identidad.
- Editor visual completo de automatizaciones y límites reforzados de regex y salida.
- Acciones locales de JSON, entidades, colores, slugs, limpieza de terminal,
  comparación con portapapeles y lectura en voz alta.
- Marcador privado de cierres anómalos y gate CI de 500 ciclos del popup.
- Captura de región OCR mediante XDG Screenshot Portal cargado bajo demanda.
- Plantillas reutilizables y orden visual exacto de pasos de automatización.
- Flatpak actualizado a KDE/PySide 6.9 y autodiagnóstico de paquetes.
- Barra contextual con prioridad para acciones básicas, respeto absoluto de
  acciones fijadas y nivel secundario para integraciones invasivas.
- Nuevas acciones locales: cortar, limpiar espacios, tipos oración/título,
  comillas, listas, ordenar/eliminar duplicados, URL, Base64 y HTML.
- Ocultación por alejamiento sostenido del cursor y umbrales de intención menos
  propensos a mostrar el popup en selecciones accidentales.
- Rediseño óptico a 17 px de los trece nuevos SVG: retícula y trazo unificados,
  siluetas simplificadas y diferenciación precisa de URL/Base64 sin fondos.
- Catorce pictogramas semánticos nuevos para cálculo, conteo, gramática, deshacer,
  historial, OCR, JSON, extracción, color, slug, terminal, comparación y voz; migración
  no destructiva de configuraciones existentes y filtrado contextual más preciso.
- Corregido el cierre prematuro del popup al mezclar coordenadas Wayland y
  XWayland durante el modo de posicionamiento alternativo.
- El clic secundario tiene prioridad sobre Clipboard y AT-SPI: cancela lecturas
  pendientes, oculta la barra incluso durante su inmunidad inicial y evita que
  reaparezca sobre el menú contextual nativo.
- Auditoría de acciones sin efecto: los monitores exigen un backend real y las
  integraciones de Klipper validan errores D-Bus antes de informar éxito.
- La barra muestra al menos ocho acciones directas más el acceso al excedente,
  calcula ese botón dentro de la misma fila y ajusta su geometría al conjunto
  activo; Configuración permite elegir de 8 a 40 o mostrar todas.
- La composición adaptativa reutiliza los botones cuando produce el mismo
  resultado visual, evitando reconstrucciones y asignaciones innecesarias.
- Las palabras autoseleccionadas por clic secundario reciben estabilización
  adicional y se descartan si AT-SPI confirma que el menú nativo está activo.
- El orden manual es ahora contractual: contexto y disponibilidad solo filtran;
  nunca reordenan. Se retiraron las promociones automáticas por prioridad y uso.
- El popup no activable deja de cerrarse por cambios de foco normales y mantiene
  una geometría mínima estable durante recomposiciones nativas en Wayland.
- Las integraciones opcionales se validan en segundo plano: modelo real de Ollama,
  idiomas de Tesseract, diccionario Enchant, servidor LanguageTool y runtime WASI.
- Ollama selecciona automáticamente un modelo local disponible y OCR degrada a
  los idiomas instalados en vez de fallar por exigir siempre inglés y español.
- Historial Klipper abre ahora el historial real; recargar acciones conserva las
  automatizaciones y extensiones dinámicas, y se retiró la escritura de ranking
  que ya no tenía efecto sobre el orden configurado.
- El ciclo de interacción conserva una instantánea del texto aunque Wayland
  vacíe PRIMARY al pulsar, coalesce fragmentos de un mismo arrastre y protege
  pulsaciones de acciones frente a cierres por foco, KWin y temporizadores.
- La ventana normal declara explícitamente que no acepta foco; el modo teclado
  lo habilita solo para una invocación por atajo. KWin ignora activaciones de la
  propia ventana y TextPik confirma los vaciados de selección antes de ocultar.
- Las acciones básicas de texto reciben semántica Unicode y nombres más claros:
  tipo oración real, unión de líneas con reparación de palabras cortadas,
  comillas tipográficas idempotentes y listas que respetan sangría y negativos.
- Contar texto distingue palabras compuestas y decimales y muestra caracteres
  con/sin espacios, oraciones, párrafos, líneas y tiempo estimado de lectura.
- Conteos, cálculos, conversiones, comparaciones, OCR y otros resultados
  informativos se presentan en una tarjeta flotante independiente, desplazable
  y copiable; la barra de acciones nunca se expande para mostrar información.
- La tarjeta de resultados se crea de forma diferida solo al solicitarla, se
  mantiene mientras el usuario interactúa y se cierra de forma independiente.

## v0.5.0-rc.1 — 2026-07-14

### Inteligencia local
- Resultados inline para cálculos, conversiones y estadísticas sin red.
- Clasificación de fechas, monedas, coordenadas, DOI, ISBN, rutas y errores.
- Ranking local opcional por contexto, frecuencia y recencia sin guardar texto.
- Posicionamiento que evita la dirección reciente del puntero.

### Escritura y productividad
- Ortografía con detección ligera de idioma, ignorados, diccionario personal y deshacer.
- LanguageTool bajo demanda con vista antes/después y aplicación transaccional.
- Automatizaciones declarativas, condicionadas, con vista previa y sin shell.
- Historial privado limitado, excluyente de secretos y cifrable opcionalmente.

### Proveedores y ecosistema
- Ollama local con tareas explícitas, respuesta limitada y endpoint exclusivamente local.
- OCR local de archivos y regiones con Tesseract y adaptadores de escritorio.
- Extensiones WASI v2 confinadas, con timeout, permiso explícito e integridad SHA-256.
- Puertas CI para latencia del núcleo y PSS, además de 102 pruebas automatizadas.

## v0.4.0-rc.1 — 2026-07-13

### Estabilidad
- Corregido el crash de arranque causado por referencias débiles incompatibles.
- Ciclo de vida seguro para workers Qt durante ejecución y cierre.
- Sesiones de selección versionadas que descartan resultados AT-SPI y Wayland obsoletos.
- Protección de campos sensibles mediante el estado AT-SPI `PROTECTED`.

### Comportamiento
- Motor de intención para ignorar menús, controles y objetos de gestores de archivos.
- Posicionamiento con histéresis para evitar vibraciones del popup.
- Pegado sin sobrescribir el contenido existente del portapapeles.
- Paleta de más acciones opaca, buscador difuso y reglas por aplicación.
- Barra expandible con 3–40 iconos directos, modo para mostrar todas las acciones
  y orden libre mediante arrastrar y soltar; la paleta contiene solo el excedente.

### Distribución
- Recetas DEB, RPM, Arch, Flatpak y AppImage alineadas.
- Matriz CI para Python 3.10–3.13, cobertura del núcleo y smoke test gráfico.
- Automatización de releases con artefactos Python y checksums SHA-256.

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
