/*
 * TextPik KWin placement effect.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Qt cannot place a toplevel at an arbitrary position on Wayland: the
 * xdg-shell protocol it implements has no move request, so `QWidget.move()` is
 * a silent no-op and the compositor chooses the position instead.  This effect
 * runs inside KWin, where `KWin::Window::move()` does exist, applies the
 * requested position, and reports the geometry KWin actually applied back over
 * D-Bus so the Python side can verify the placement instead of trusting Qt.
 *
 * The effect is intentionally placement-only.  Anchors, hysteresis, screen
 * edge strategy and popup contents all stay in Python; this component only
 * identifies the TextPik window, moves it, and reports what happened.
 */

#pragma once

#include <effect/effect.h>
#include <effect/effecthandler.h>
#include <effect/globals.h>
#include <workspace.h>

#include <QObject>
#include <QPointer>

#include <KPluginFactory>
#include <QtPlugin>
#include <kwin_export.h>

namespace TextPik
{

/*!
 * \brief The TextPik placement effect.
 *
 * Identifies TextPik's popup, moves it with the compositor's own geometry API
 * and reports the geometry KWin actually applied.
 *
 * The D-Bus interface name comes from `Q_CLASSINFO`, not from the C++ class
 * name: a plain `registerObject()` export would publish the dotless class name
 * and D-Bus rejects interface names without a dot, making the effect
 * unreachable.  `Q_SCRIPTABLE` is only an annotation in Qt 6, so the methods
 * have to sit in a `Q_SLOTS` section to be exported.
 */
class TextPikPlacementEffect : public KWin::Effect
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.textpik.KWinPlacement")

public:
    TextPikPlacementEffect();
    ~TextPikPlacementEffect() override;

public Q_SLOTS:
    /// Registers the window TextPik wants moved, identified by internalId.
    Q_SCRIPTABLE void registerTextPikWindow(const QString &internalId);

    /*!
     * Moves the registered window and records the revision we answered.
     *
     * Revision is `int` rather than `quint64` because D-Bus distinguishes the
     * two on the wire and a Python caller marshals a plain int as 32 bits.  A
     * monotonic counter per popup cannot exhaust it.
     */
    Q_SCRIPTABLE void requestPlacement(int revision, int x, int y, int w, int h);

    /*!
     * Reports the geometry KWin currently has for the registered window.
     *
     * The payload is `revision,has_window,x,y,w,h,output`.  The revision is the
     * last one the effect actually processed, so a client can detect that its
     * request was superseded instead of receiving an echo of its own number.
     * `has_window` is 0 when no popup is registered, which keeps the trailing
     * fields meaningless instead of a plausible-looking position at 0,0.
     */
    Q_SCRIPTABLE QString readback() const;

    /// Drops the registered window, e.g. when the popup was destroyed.
    Q_SCRIPTABLE void unregisterTextPikWindow();

private:
    /// Re-resolves the registered window after it was (re)created.
    void resolveWindow();

    QPointer<KWin::Window> m_window;
    QString m_registeredId;
    int m_revision = 0;
};

/// Plugin factory for the effect.
///
/// The factory is declared explicitly rather than through
/// `KWIN_EFFECT_FACTORY`, because moc does not expand macros: a factory hidden
/// behind one would never get its `Q_PLUGIN_METADATA` emitted and the plugin
/// would load as "not a Qt plugin".
class TextPikPlacementEffectFactory : public KWin::EffectPluginFactory
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.kde.kwin.EffectPluginFactory6.7.5" FILE "metadata.json")
    Q_INTERFACES(KPluginFactory)

public:
    bool isSupported() const override;
    bool enabledByDefault() const override;
    KWin::Effect *createEffect() const override;
};

} // namespace TextPik
