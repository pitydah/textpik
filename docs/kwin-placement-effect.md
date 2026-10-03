# KWin placement effect

TextPik can only place its popup next to the cursor when a compositor-side
authority confirms the position. On Plasma Wayland that authority is a small
KWin effect built from `native/kwin-effect/`.

## Why the effect exists

On Wayland, `QWidget.move()` is a no-op for toplevels: the xdg-shell protocol
implements no move request, so the toolkit never asks the compositor to move the
window and the compositor chooses the position instead. Measured on KDE Plasma 6
with KWin 6.7.5 and Qt 6:

- Qt sends zero `set_bounds`/`request_move` requests to the `xdg_toplevel`.
- KWin reports `configure(0, 0)` and places the popup at screen centre.
- With `Qt.Tool`, `QWidget.geometry()` still returns the requested value, so it
  reports a position that never existed.

KWin's scripting API does not help either: `Window` exposes no `move()` and its
`x`/`y`/`pos`/`rect`/`frameGeometry` properties are read-only, which was
verified by attempting every write strategy. The C++ API does expose
`KWin::Window::move(const QPointF &)` and `moveResize(const RectF &)`, and those
are only reachable from inside the compositor.

## Architecture

```
selection -> anchor resolver -> desired_position
                                      |
                                      v
                       Python applies workarea constraints
                                      |
                              requested_position
                                      |
                              D-Bus requestPlacement
                                      v
                      KWin effect -> KWin::Window::move()
                                      |
                            compositor geometry
                                      |
                             D-Bus readback
                                      v
                    observed_position -> PopupPlacementResult
```

Python owns selection, anchors, action planning, popup contents, hysteresis and
the screen-edge strategy. The effect only identifies the popup, moves it and
reports the geometry KWin ended up with.

`textpik_core.placement_client` is the only component that talks to the
compositor, and `textpik_core.placement.select_placement_backend()` decides
which authority a session gets. There is no single generic "Wayland
positioner": each compositor needs its own backend.

## Placement authority by session

| Session | Backend | Position verified |
| --- | --- | --- |
| X11 | `x11` | yes, from the post-map frame position |
| Plasma Wayland, effect loaded | `kwin-effect` | yes, from the compositor |
| Plasma Wayland, effect missing | `qt-xdg-toplevel-unverified` | never |
| Sway / Hyprland / GNOME / other Wayland | `qt-xdg-toplevel-unverified` | never |
| offscreen / headless | `unavailable` | never |

A non-authoritative backend can never publish an observed position: the
`PopupPlacementResult` type drops it, so the popup cannot report a verified
position it did not receive from the compositor.

## D-Bus API

Service `org.textpik.KWinPlacement`, object `/KWinPlacement`, interface
`org.textpik.KWinPlacement`.

| Method | Purpose |
| --- | --- |
| `registerTextPikWindow(QString internalId)` | pin the effect to one window; optional, see below |
| `requestPlacement(int revision, int x, int y, int w, int h)` | move and resize the popup |
| `readback() -> QString` | `revision,has_window,x,y,w,h,output` |
| `unregisterTextPikWindow()` | forget the popup |

`readback()` answers with the last revision the effect actually processed, not
an echo of the caller's number, so a confirmation that a newer selection
superseded is detectable. `has_window=0` means the trailing fields carry no
geometry.

The revision type is `int`, not `quint64`, because D-Bus distinguishes the two
on the wire and a Python caller marshals a plain int as 32 bits.

TextPik does not currently call `registerTextPikWindow`: KWin's `internalId` is
a compositor-side `QUuid` that is not exposed over xdg-shell, so the popup
cannot know it. The effect resolves the popup by its window class instead.

## Build and install

The effect is optional. TextPik starts and works without it, reporting placement
as degraded.

```sh
cmake -S native/kwin-effect -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
cmake --install build --prefix ~/.local
```

`packaging/install.sh` does this automatically, and skips the step with an
explanation when the build dependencies are missing.

Build requirements: a C++20 compiler, CMake, Ninja, Qt 6 (Core, Gui, Widgets,
DBus), KF6 CoreAddons, KF6 ConfigCore and KF6 WindowSystem headers, plus the
KWin development headers. The effect compiles as C++20 because KWin 6.7's
`core/rect.h` uses a `constexpr` default constructor that C++17 rejects.

## Loading the effect

KWin discovers native effects by scanning Qt plugin directories at startup, and
it does not add any user plugin path of its own. Qt only looks in
`/usr/lib/qt6/plugins`, so the user-local install directory has to be exported:

```
# ~/.config/environment.d/90-textpik-qt-plugin-path.conf
QT_PLUGIN_PATH=/home/<user>/.local/lib/qt6/plugins
```

`install.sh` writes that file. Because the plugin list is cached when the
compositor starts, the effect only becomes available after logging out and back
in; neither `loadEffect` over D-Bus nor a reconfiguration reloads it.

Verify the result after logging back in:

```sh
python3 scripts/check_placement_backend.py
```

If the effect is listed but not active, enable it with:

```sh
qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadEffect textpik-placement
```

## Packaging

The effect links against the KWin of the machine that builds it, and KWin
rejects a plugin whose interface id does not match its own version. The id is
therefore taken from `EffectPluginFactory_iid` in the KWin headers rather than
from a pinned literal, and packages ship the **sources** plus an optional
builder instead of a binary that could be refused elsewhere:

- `packaging/kwin-effect/build.sh` compiles the effect and skips with a clear
  message, exiting successfully, when the KWin, KF6 or Qt development files are
  absent. A package build without the toolchain still succeeds and still ships
  the sources.
- Debian and Arch build the effect at package time and install it into the
  system Qt plugin directory. RPM builds it into the package data directory,
  because RPM cannot own a path that only exists when an optional build
  dependency is present.
- The wheel ships the sources, so a packaged install can still compile the
  effect against the local KWin.
- `packaging/install.sh` builds and installs it per user, which is the path that
  works for any of them.

A `kwin-effect` CI job builds the plugin in a rolling Arch container and runs
`textpik-verify-effect`, so the native component is a real gate rather than a
local check. That job also asserts the embedded id matches the KWin headers it
compiled against.

## Verifying a build

`native/kwin-effect/verify_effect.cpp` loads the built plugin the way KWin would
and checks both the plugin contract and the D-Bus surface:

```sh
./build/textpik-verify-effect ./build/textpik-placement.so
```

It asserts that the factory satisfies `KWin::EffectPluginFactory`, that the
published interface is `org.textpik.KWinPlacement` rather than the dotless C++
class name (which D-Bus rejects), that the methods accept the argument types the
Python client sends, and that `readback()` follows its documented protocol.

## Known limits

- The effect has not yet been exercised with a loaded KWin at runtime; the
  physical placement test requires a session restart.
- X11 placement is reported from the post-map frame position. A window manager
  that relocates the window after the client's request would be reported as a
  mismatch only once Qt processes the resulting `ConfigureNotify`.
- Multi-monitor, mixed-DPI and fractional-scaling placement still need physical
  validation.
