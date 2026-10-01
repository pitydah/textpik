/*
 * TextPik KWin placement effect.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "effect.h"

#include "window.h"

#include <QDBusConnection>
#include <QDebug>
#include <QRectF>
#include <QStringList>

namespace TextPik
{

static const char *const s_dbusService = "org.textpik.KWinPlacement";
static const char *const s_dbusPath = "/KWinPlacement";

/// The window identifier TextPik advertises; matches the Python side.
static const char *const s_windowClass = "textpik";

TextPikPlacementEffect::TextPikPlacementEffect()
    : KWin::Effect()
{
    if (auto *workspace = KWin::Workspace::self()) {
        // The popup is destroyed and recreated per selection, so the effect has
        // to pick up the new surface whenever it appears.
        connect(workspace, &KWin::Workspace::windowAdded, this, [this](KWin::Window *w) {
            if (!w) {
                return;
            }
            if (!m_registeredId.isEmpty() && w->internalId() == QUuid(m_registeredId)) {
                m_window = w;
                return;
            }
            if (m_window.isNull()
                && w->resourceClass() == QLatin1String(s_windowClass)) {
                m_window = w;
            }
        });
    }

    QDBusConnection::sessionBus().registerObject(
        s_dbusPath,
        this,
        QDBusConnection::ExportScriptableSlots | QDBusConnection::ExportScriptableProperties);

    if (!QDBusConnection::sessionBus().registerService(s_dbusService)) {
        qWarning() << "textpik: could not own" << s_dbusService
                   << "- another placement effect is already loaded";
    }
}

TextPikPlacementEffect::~TextPikPlacementEffect()
{
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (bus.objectRegisteredAt(s_dbusPath) == this) {
        bus.unregisterObject(s_dbusPath);
    }
    bus.unregisterService(s_dbusService);
}

void TextPikPlacementEffect::registerTextPikWindow(const QString &internalId)
{
    m_registeredId = internalId;
    resolveWindow();
}

void TextPikPlacementEffect::unregisterTextPikWindow()
{
    m_window = nullptr;
    m_registeredId.clear();
}

void TextPikPlacementEffect::resolveWindow()
{
    auto *workspace = KWin::Workspace::self();
    if (!workspace) {
        return;
    }

    // Prefer the exact id TextPik handed us; fall back to the class match so a
    // popup that was recreated between register and request is still found.
    const QList<KWin::Window *> windows = workspace->windows();
    if (!m_registeredId.isEmpty()) {
        const QUuid wanted(m_registeredId);
        for (KWin::Window *w : windows) {
            if (w && w->internalId() == wanted) {
                m_window = w;
                return;
            }
        }
    }

    for (KWin::Window *w : windows) {
        if (w && w->resourceClass() == QLatin1String(s_windowClass)) {
            m_window = w;
            return;
        }
    }
}

void TextPikPlacementEffect::requestPlacement(int revision, int x, int y, int w, int h)
{
    if (m_window.isNull()) {
        resolveWindow();
    }

    m_revision = revision;

    if (m_window.isNull()) {
        qWarning() << "textpik: placement requested but no popup window is known";
        return;
    }

    KWin::Window *window = m_window.data();

    // Resize only when the popup really changed size, so repeated placement
    // requests for the same selection do not fight the client.
    const QRectF current = window->frameGeometry();
    const bool sizeMatches = std::abs(current.width() - w) <= 1
        && std::abs(current.height() - h) <= 1;
    if (!sizeMatches && w > 0 && h > 0) {
        window->moveResize(KWin::RectF(x, y, w, h));
    } else {
        window->move(QPointF(x, y));
    }
}

QString TextPikPlacementEffect::readback() const
{
    if (m_window.isNull()) {
        // has_window=0 tells the client that the trailing fields carry no
        // geometry, instead of reporting a believable position at 0,0.
        return QStringLiteral("%1,0,0,0,0,0,").arg(m_revision);
    }

    const KWin::Window *window = m_window.data();
    const QRectF geometry = window->frameGeometry();
    const QString output = window->output() ? window->output()->name() : QString();

    return QStringLiteral("%1,1,%2,%3,%4,%5,%6")
        .arg(m_revision)
        .arg(qRound(geometry.x()))
        .arg(qRound(geometry.y()))
        .arg(qRound(geometry.width()))
        .arg(qRound(geometry.height()))
        .arg(output);
}

bool TextPikPlacementEffectFactory::isSupported() const
{
    // The effect only calls Window::move()/moveResize(), which both backends
    // implement, so no compositing-backend check is needed here.
    return true;
}

bool TextPikPlacementEffectFactory::enabledByDefault() const
{
    // TextPik probes for the effect and degrades loudly when it is absent, so
    // loading it on every session would only add a D-Bus name for nothing.
    return false;
}

KWin::Effect *TextPikPlacementEffectFactory::createEffect() const
{
    return new TextPikPlacementEffect;
}

} // namespace TextPik
