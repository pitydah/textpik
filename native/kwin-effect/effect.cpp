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

/// Window identity advertised by the main popup; other TextPik top-levels must
/// never be moved by the placement effect.
static const char *const s_windowClass = "textpik";
static const char *const s_windowCaption = "textpik-popup";

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
                applyPendingPlacement();
                return;
            }
            if (m_window.isNull() && isTextPikPopup(w)) {
                m_window = w;
                applyPendingPlacement();
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
    m_hasPendingPlacement = false;
}

bool TextPikPlacementEffect::isTextPikPopup(KWin::Window *window) const
{
    if (!window || window->resourceClass() != QLatin1String(s_windowClass)) {
        return false;
    }
    return window->caption().startsWith(
        QLatin1String(s_windowCaption),
        Qt::CaseInsensitive);
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
        if (isTextPikPopup(w)) {
            m_window = w;
            return;
        }
    }
}

void TextPikPlacementEffect::applyPendingPlacement()
{
    if (!m_hasPendingPlacement || m_window.isNull()) {
        return;
    }

    KWin::Window *window = m_window.data();
    const QRectF current = window->frameGeometry();
    const bool sizeMatches = std::abs(current.width() - m_pendingWidth) <= 1
        && std::abs(current.height() - m_pendingHeight) <= 1;

    if (!sizeMatches && m_pendingWidth > 0 && m_pendingHeight > 0) {
        window->moveResize(KWin::RectF(
            m_pendingX,
            m_pendingY,
            m_pendingWidth,
            m_pendingHeight));
    } else {
        window->move(QPointF(m_pendingX, m_pendingY));
    }
    m_hasPendingPlacement = false;
}

void TextPikPlacementEffect::requestPlacement(int revision, int x, int y, int w, int h)
{
    // The Python side can request placement immediately after show(). KWin may
    // not have emitted windowAdded yet, so preserve the request and replay it
    // from the windowAdded callback instead of silently losing the P0 action.
    m_revision = revision;
    m_pendingX = x;
    m_pendingY = y;
    m_pendingWidth = w;
    m_pendingHeight = h;
    m_hasPendingPlacement = true;

    if (m_window.isNull()) {
        resolveWindow();
    }
    if (m_window.isNull()) {
        qDebug() << "textpik: placement queued until popup window is mapped"
                 << "revision" << revision;
        return;
    }
    applyPendingPlacement();
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
    // Once the optional plugin is installed, placement next to the cursor is a
    // core product behaviour, not an opt-in enhancement.
    return true;
}

KWin::Effect *TextPikPlacementEffectFactory::createEffect() const
{
    return new TextPikPlacementEffect;
}

} // namespace TextPik
