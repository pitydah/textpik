/*
 * Verifica que el .so del effect sea ABI-compatible con la libkwin instalada y
 * que su superficie D-Bus sea alcanzable de extremo a extremo.
 *
 * Esto NO prueba que KWin lo descubra (eso exige reiniciar el compositor), pero
 * sí que:
 *   1. el plugin compila, enlaza y su factory satisface EffectPluginFactory,
 *   2. la interface publicada es `org.textpik.KWinPlacement` y no el nombre de
 *      la clase (que D-Bus rechaza por no tener puntos),
 *   3. los métodos aceptan la aridad y los tipos que el cliente Python envía,
 *   4. `readback` responde con el protocolo documentado.
 */

#include <QCoreApplication>
#include <QEventLoop>
#include <QTimer>
#include <QPluginLoader>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusReply>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QStringList>

#include <cstdio>

#include <effect/effect.h>
#include <effect/effecthandler.h>

namespace
{

const char *const kService = "org.textpik.KWinPlacement";
const char *const kPath = "/KWinPlacement";
const char *const kInterface = "org.textpik.KWinPlacement";

int g_failures = 0;

void check(bool condition, const char *what)
{
    std::printf("%-56s %s\n", what, condition ? "ok" : "FALLA");
    if (!condition) {
        ++g_failures;
    }
}

} // namespace

namespace
{

/// Lets the bus connection flush queued registrations.
void spinEventLoop(int milliseconds)
{
    QEventLoop loop;
    QTimer::singleShot(milliseconds, &loop, &QEventLoop::quit);
    loop.exec();
}

} // namespace

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);

    if (argc < 2) {
        std::fprintf(stderr, "uso: verify_effect <ruta.so>\n");
        return 2;
    }

    const QString path = QString::fromLocal8Bit(argv[1]);

    QPluginLoader loader(path);
    // QPluginLoader nests the plugin's own JSON under "MetaData".
    const QJsonObject meta = loader.metaData().value("MetaData").toObject();
    if (meta.isEmpty()) {
        std::fprintf(stderr, "FALLA: sin metadata de plugin: %s\n",
                     qPrintable(loader.errorString()));
        return 1;
    }

    const QJsonObject plugin = meta.value("KPlugin").toObject();
    const QString id = plugin.value("Id").toString();
    const QJsonArray serviceTypes = plugin.value("ServiceTypes").toArray();
    QStringList serviceTypeNames;
    for (const QJsonValue &value : serviceTypes) {
        serviceTypeNames << value.toString();
    }

    std::printf("plugin id        : %s\n", qPrintable(id));
    std::printf("ServiceTypes     : %s\n", qPrintable(serviceTypeNames.join(',')));
    check(id == QLatin1String("textpik-placement"), "el plugin declara el id esperado");
    check(serviceTypeNames.contains(QLatin1String("KWin/Effect")),
          "el plugin declara ServiceTypes KWin/Effect");

    QObject *instance = loader.instance();
    if (!instance) {
        std::fprintf(stderr, "FALLA: no se pudo instanciar: %s\n",
                     qPrintable(loader.errorString()));
        return 1;
    }

    auto *factory = qobject_cast<KWin::EffectPluginFactory *>(instance);
    if (!factory) {
        std::fprintf(stderr, "FALLA: no es un KWin::EffectPluginFactory\n");
        return 1;
    }

    std::printf("isSupported      : %s\n", factory->isSupported() ? "true" : "false");
    std::printf("enabledByDefault : %s\n", factory->enabledByDefault() ? "true" : "false");

    KWin::Effect *effect = factory->createEffect();
    if (!effect) {
        std::fprintf(stderr, "FALLA: createEffect() devolvio null\n");
        return 1;
    }
    std::printf("effect creado    : %s\n", effect->metaObject()->className());

    // La construcción registra el objeto y el adaptor en el bus de sesión.
    if (!QDBusConnection::sessionBus().isConnected()) {
        std::printf("\n(sin bus de sesion: se omite la verificacion D-Bus)\n");
        delete effect;
        loader.unload();
        return g_failures == 0 ? 0 : 1;
    }

    std::printf("\n--- verificacion D-Bus ---\n");

    // registerObject()/registerService() are queued on the connection, so the
    // name and the object are not callable until the event loop has run.
    spinEventLoop(300);

    QDBusInterface iface(QLatin1String(kService), QLatin1String(kPath),
                         QLatin1String(kInterface), QDBusConnection::sessionBus());
    check(iface.isValid(), "la interface org.textpik.KWinPlacement es valida");

    const QDBusReply<QString> before = iface.call(QLatin1String("readback"));
    if (!before.isValid()) {
        std::printf("  error de readback(): %s\n", qPrintable(before.error().message()));
    }
    check(before.isValid(), "readback() responde sin error");

    const QStringList fields = before.value().split(QLatin1Char(','));
    check(fields.size() >= 7, "readback() devuelve el protocolo de 7 campos");
    if (fields.size() >= 7) {
        check(fields.at(1) == QLatin1String("0"),
              "readback() marca has_window=0 sin popup registrado");
    }

    QDBusReply<void> placement = iface.call(QLatin1String("requestPlacement"), 41, 1440, 720, 320, 90);
    check(placement.isValid(), "requestPlacement(int,int,int,int,int) acepta enteros");

    QDBusReply<void> registered = iface.call(QLatin1String("registerTextPikWindow"),
                                            QStringLiteral(""));
    check(registered.isValid(), "registerTextPikWindow(QString) es alcanzable");

    const QDBusReply<QString> after = iface.call(QLatin1String("readback"));
    check(after.isValid(), "readback() sigue respondiendo tras las llamadas");
    if (after.isValid()) {
        const QStringList afterFields = after.value().split(QLatin1Char(','));
        check(!afterFields.isEmpty() && afterFields.first() == QLatin1String("41"),
              "readback() refleja la ultima revision procesada");
    }

    QDBusReply<void> unregistered = iface.call(QLatin1String("unregisterTextPikWindow"));
    check(unregistered.isValid(), "unregisterTextPikWindow() es alcanzable");

    delete effect;
    loader.unload();

    std::printf("\n%s\n", g_failures == 0
                    ? "OK: plugin y superficie D-Bus verificados"
                    : "FALLA: hay verificaciones sin cumplir");
    return g_failures == 0 ? 0 : 1;
}
