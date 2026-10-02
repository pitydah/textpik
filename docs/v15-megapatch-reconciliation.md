# TextPik V15 — Reconciliación de auditorías y mega-parche

## Baseline canónico

- Repositorio: `pitydah/textpik`
- Rama: `agent/textpik-next-0-5-rc`
- HEAD requerido: `daafe3c91ffc67c824d32b7f7b704477f355959a`

Este mega-parche reconcilia las auditorías previas con el estado real de la RC.

## Regla P0

Después de seleccionar texto, el popup principal debe aparecer visualmente junto
al cursor, sin flash visible en el centro de la pantalla.

## Cambios V15

- Reproduce un requestPlacement si éste llega antes de windowAdded.
- Cloak visual hasta confirmación compositor-side.
- Cursor global/compositor fresco gana a geometría AT-SPI como anchor.
- Raw AT-SPI es evidencia, no autoridad.
- El hot path automático deja de hacer traversal AT-SPI síncrono.
- Contexto de acción congelado.
- JIT revalidation antes de mutar una selección AT-SPI.
- Same-text reselection explícita para wl-paste/Klipper.
- Diagnóstico conoce el KWin Effect.
- LanguageTool usa rangos LAN explícitos.

## VERIFY-FIRST

Antes de aplicar:

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --porcelain=v1
git diff --check
python -m py_compile src/textpik.py src/textpik_core/*.py
python -m unittest discover -s tests -v
git apply --stat /ruta/textpik-mega-v15-daafe3c.patch
git apply --check --verbose /ruta/textpik-mega-v15-daafe3c.patch
```

Requisitos: rama `agent/textpik-next-0-5-rc`, HEAD `daafe3c91ffc67c824d32b7f7b704477f355959a`, árbol limpio, baseline verde y
`git apply --check` verde. Si falla cualquiera, STOP.

Después:

```bash
git diff --check
python -m py_compile src/textpik.py src/textpik_core/*.py
python -m unittest tests.test_megapatch_v15 -v
python -m unittest discover -s tests -v
python scripts/check_performance.py
```

No commit ni push sin instrucción explícita.
