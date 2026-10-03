"""Contract tests for the compositor-side placement client.

The client sits between TextPik and the KWin effect. These tests pin the
protocol rules that make ``verified`` trustworthy: a confirmation must belong
to the revision we asked about, it must carry a real window, and any transport
failure has to degrade to "not verified" instead of raising into the selection
hot path.
"""

import unittest

from src.textpik_core.models import Point
from src.textpik_core.placement_client import (
    INTERFACE_NAME,
    OBJECT_PATH,
    SERVICE_NAME,
    PlacementConfirmation,
    KWinPlacementClient,
)


class FakeTransport:
    """Records calls and replays scripted replies.

    Blocking and asynchronous calls are recorded separately so a test can prove
    which one a code path used.
    """

    def __init__(self, replies=None):
        self.calls = []
        self.async_calls = []
        self.replies = dict(replies or {})
        self.error = ""

    def _reply_for(self, method):
        reply = self.replies.get(method, (True, []))
        if isinstance(reply, Exception):
            self.error = str(reply)
            return False, []
        return reply

    def call(self, method, *args):
        self.calls.append((method, args))
        return self._reply_for(method)

    def call_async(self, method, *args, on_done):
        self.async_calls.append((method, args))
        on_done(*self._reply_for(method))

    def methods(self):
        return [name for name, _ in self.calls]

    def async_methods(self):
        return [name for name, _ in self.async_calls]


class ContractTest(unittest.TestCase):
    def test_service_contract_matches_the_effect(self):
        self.assertEqual(SERVICE_NAME, "org.textpik.KWinPlacement")
        self.assertEqual(INTERFACE_NAME, "org.textpik.KWinPlacement")
        self.assertEqual(OBJECT_PATH, "/KWinPlacement")


class AvailabilityTest(unittest.TestCase):
    def test_available_when_readback_answers(self):
        client = KWinPlacementClient(
            FakeTransport({"readback": (True, ["7,0,0,0,0,0,"])})
        )
        self.assertTrue(client.available())

    def test_unavailable_when_transport_fails(self):
        transport = FakeTransport({"readback": RuntimeError("no such service")})
        client = KWinPlacementClient(transport)
        self.assertFalse(client.available())
        self.assertTrue(client.last_error)

    def test_available_probes_without_arguments(self):
        transport = FakeTransport({"readback": (True, ["0,0,0,0,0,0,"])})
        KWinPlacementClient(transport).available()
        self.assertEqual(transport.calls, [("readback", ())])


class RequestsTest(unittest.TestCase):
    def test_request_sends_ints_in_protocol_order(self):
        transport = FakeTransport({"requestPlacement": (True, [])})
        client = KWinPlacementClient(transport)
        self.assertTrue(client.request(41, 1440, 720, 320, 90))
        self.assertEqual(
            transport.calls, [("requestPlacement", (41, 1440, 720, 320, 90))]
        )

    def test_request_reports_transport_failure(self):
        transport = FakeTransport({"requestPlacement": RuntimeError("stalled")})
        self.assertFalse(KWinPlacementClient(transport).request(1, 0, 0, 10, 10))

    def test_register_window_sends_identifier(self):
        transport = FakeTransport({"registerTextPikWindow": (True, [])})
        KWinPlacementClient(transport).register_window("abc")
        self.assertEqual(transport.calls, [("registerTextPikWindow", ("abc",))])

    def test_register_window_without_identifier_sends_empty_string(self):
        transport = FakeTransport({"registerTextPikWindow": (True, [])})
        KWinPlacementClient(transport).register_window()
        self.assertEqual(transport.calls, [("registerTextPikWindow", ("",))])

    def test_unregister_window_is_reachable(self):
        transport = FakeTransport({"unregisterTextPikWindow": (True, [])})
        self.assertTrue(KWinPlacementClient(transport).unregister_window())
        self.assertEqual(transport.methods(), ["unregisterTextPikWindow"])


class AsyncPlacementTest(unittest.TestCase):
    """Placement calls must not block the interface thread.

    A blocking call holds the caller for the D-Bus timeout, and the popup
    retries, so a stalled compositor used to freeze the interface for up to a
    second. These pin that the placement path goes through the asynchronous
    transport and that the blocking one stays for probes only.
    """

    def test_request_uses_the_async_transport(self):
        transport = FakeTransport({"requestPlacement": (True, [])})
        results = []
        KWinPlacementClient(transport).request_async(
            41, 1440, 720, 320, 90, on_done=results.append
        )
        self.assertEqual(results, [True])
        self.assertEqual(transport.async_methods(), ["requestPlacement"])
        self.assertEqual(transport.calls, [], "no debe usar la llamada bloqueante")

    def test_request_async_reports_failure(self):
        transport = FakeTransport({"requestPlacement": RuntimeError("stalled")})
        results = []
        KWinPlacementClient(transport).request_async(
            1, 0, 0, 10, 10, on_done=results.append
        )
        self.assertEqual(results, [False])

    def test_readback_async_uses_the_async_transport(self):
        transport = FakeTransport({"readback": (True, ["41,1,1440,720,320,90,DP-2"])})
        results = []
        KWinPlacementClient(transport).readback_async(41, on_done=results.append)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].position.as_tuple(), (1440, 720))
        self.assertEqual(transport.async_methods(), ["readback"])
        self.assertEqual(transport.calls, [])

    def test_readback_async_rejects_a_superseded_revision(self):
        transport = FakeTransport({"readback": (True, ["42,1,1,2,3,4,DP-2"])})
        results = []
        KWinPlacementClient(transport).readback_async(41, on_done=results.append)
        self.assertEqual(results, [None])

    def test_readback_async_reports_none_on_transport_failure(self):
        transport = FakeTransport({"readback": RuntimeError("down")})
        results = []
        KWinPlacementClient(transport).readback_async(7, on_done=results.append)
        self.assertEqual(results, [None])

    def test_the_probe_still_answers_synchronously(self):
        """The backend choice decides the cloak before the popup is shown."""
        transport = FakeTransport({"readback": (True, ["7,0,0,0,0,0,"])})
        self.assertTrue(KWinPlacementClient(transport).available())
        self.assertEqual(transport.async_calls, [])


TEST_SERVICE_NAME = "org.textpik.KWinPlacementTest"


class QtDBusAsyncTransportTest(unittest.TestCase):
    """The real transport must defer its reply instead of blocking the caller.

    The service is registered for the duration of the test on purpose. Without
    an owner the interface is invalid and the transport answers from its early
    return, which would pass a timing assertion without ever exercising the
    asynchronous path.
    """

    def setUp(self):
        try:
            from PySide6.QtDBus import QDBusConnection
        except ImportError:  # pragma: no cover - depends on Qt install
            self.skipTest("QtDBus no disponible")

        self.bus = QDBusConnection.sessionBus()
        if not self.bus.isConnected():
            self.skipTest("sin bus de sesion")

        self.service_name = TEST_SERVICE_NAME
        self.owned_service = bool(self.bus.registerService(self.service_name))
        if not self.owned_service:
            self.skipTest(f"{self.service_name} ya esta tomado")
        # El objeto de cada test se registra en el propio test: uno cualquiera
        # alcanza para que la interface sea valida, y el que necesita una
        # respuesta real registra un adaptador.
        self.holder = None

    def _register_object(self, obj, flags):
        if not self.bus.registerObject(OBJECT_PATH, obj, flags):
            self.skipTest("no se pudo registrar el objeto de prueba")
        self.holder = obj

    def tearDown(self):
        if getattr(self, "holder", None) is not None:
            self.bus.unregisterObject(OBJECT_PATH)
            self.holder = None
        if getattr(self, "owned_service", False):
            self.bus.unregisterService(self.service_name)

    def _spin(self, app, predicate, timeout_ms=3000, step_ms=20):
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(timeout_ms)
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        poll.start(step_ms)
        loop.exec()

    def test_async_call_defers_the_reply_instead_of_blocking(self):
        from time import monotonic

        from PySide6.QtCore import QCoreApplication

        from src.textpik_core.placement_client import QtDBusPlacementTransport

        from PySide6.QtCore import QObject
        from PySide6.QtDBus import QDBusConnection

        app = QCoreApplication.instance() or QCoreApplication([])
        self._register_object(QObject(), QDBusConnection.ExportAllSlots)
        transport = QtDBusPlacementTransport(
            timeout_ms=200, service_name=self.service_name
        )
        delivered = []

        started = monotonic()
        transport.call_async(
            "readback", on_done=lambda ok, args: delivered.append(ok)
        )
        elapsed_ms = (monotonic() - started) * 1000

        self.assertLess(
            elapsed_ms,
            50,
            "call_async bloqueo al llamador en lugar de diferir la respuesta",
        )
        self.assertEqual(
            delivered,
            [],
            "el callback llego sin ceder el event loop: la llamada fue sincrona",
        )

        self._spin(app, lambda: bool(delivered))
        self.assertTrue(delivered, "el callback asincrono nunca llego")
        self.assertIsInstance(delivered[0], bool)
        self.assertIsNotNone(app)

    def test_async_request_succeeds_against_a_real_service(self):
        """A successful reply is the point; "the callback fired" is not enough.

        The first version of the asynchronous transport called
        ``QDBusInterface.asyncCall(method, *args)``, which PySide6 rejects with
        TypeError because it only accepts one argument. Every asynchronous
        placement failed while a test that only asserted "the callback ran"
        stayed green.
        """
        from PySide6.QtCore import ClassInfo, QCoreApplication, QObject, Slot
        from PySide6.QtDBus import QDBusAbstractAdaptor, QDBusConnection

        from src.textpik_core.placement_client import (
            KWinPlacementClient,
            QtDBusPlacementTransport,
        )

        app = QCoreApplication.instance() or QCoreApplication([])
        calls = []

        @ClassInfo({"D-Bus Interface": INTERFACE_NAME})
        class PlacementAdaptor(QDBusAbstractAdaptor):
            @Slot(int, int, int, int, int)
            def requestPlacement(self, revision, x, y, width, height):
                calls.append((revision, x, y, width, height))

            @Slot(result=str)
            def readback(self):
                return "9,1,1685,1020,116,33,DP-2"

        parent = QObject()
        adaptor = PlacementAdaptor(parent)  # noqa: F841 - debe seguir vivo
        self._register_object(parent, QDBusConnection.ExportAdaptors)

        transport = QtDBusPlacementTransport(
            timeout_ms=2000, service_name=self.service_name
        )
        result = []
        transport.call_async(
            "requestPlacement", 21, 120, 130, 116, 33,
            on_done=lambda ok, args: result.append(ok),
        )
        self._spin(app, lambda: bool(result))

        self.assertEqual(result, [True], f"la llamada fallo: {transport.error!r}")
        self.assertEqual(calls, [(21, 120, 130, 116, 33)])
        self.assertEqual(transport.error, "")

        # Una lectura real cubre ademas la rama de exito del parseo.
        client = KWinPlacementClient(transport)
        confirmations = []
        client.readback_async(9, on_done=confirmations.append)
        self._spin(app, lambda: bool(confirmations))

        self.assertEqual(len(confirmations), 1)
        self.assertIsNotNone(confirmations[0])
        self.assertEqual(confirmations[0].position.as_tuple(), (1685, 1020))
        self.assertEqual(confirmations[0].size, (116, 33))
        self.assertEqual(confirmations[0].output, "DP-2")
        self.assertIsNotNone(app)


class ReadbackTest(unittest.TestCase):
    def _client(self, payload):
        return KWinPlacementClient(FakeTransport({"readback": (True, [payload])}))

    def test_parses_a_matching_confirmation(self):
        result = self._client("41,1,1440,720,320,90,DP-2").readback(41)
        self.assertIsNotNone(result)
        self.assertEqual(result.revision, 41)
        self.assertEqual(result.position.as_tuple(), (1440, 720))
        self.assertEqual(result.size, (320, 90))
        self.assertEqual(result.output, "DP-2")

    def test_confirmation_matches_the_declared_type(self):
        result = self._client("41,1,1440,720,320,90,DP-2").readback(41)
        self.assertIsInstance(result, PlacementConfirmation)

    def test_missing_window_is_not_a_position(self):
        self.assertIsNone(self._client("41,0,0,0,0,0,").readback(41))

    def test_superseded_revision_is_rejected(self):
        """The effect replies with the revision it processed, not an echo."""
        self.assertIsNone(self._client("42,1,1440,720,320,90,DP-2").readback(41))

    def test_empty_output_name_is_accepted(self):
        result = self._client("3,1,10,20,30,40,").readback(3)
        self.assertIsNotNone(result)
        self.assertEqual(result.output, "")

    def test_output_name_containing_commas_is_kept_whole(self):
        result = self._client("3,1,10,20,30,40,HDMI,A-1").readback(3)
        self.assertIsNotNone(result)
        self.assertEqual(result.output, "HDMI,A-1")

    def test_malformed_payload_is_rejected(self):
        self.assertIsNone(self._client("garbage").readback(1))
        self.assertIsNone(self._client("1,1,not,int,3,4,DP-2").readback(1))
        self.assertIsNone(self._client("").readback(1))

    def test_transport_failure_yields_none(self):
        client = KWinPlacementClient(FakeTransport({"readback": RuntimeError("down")}))
        self.assertIsNone(client.readback(7))

    def test_confirmation_serializes_for_logging(self):
        confirmation = PlacementConfirmation(
            revision=9, position=Point(1, 2), size=(3, 4), output="DP-2"
        )
        self.assertEqual(
            confirmation.as_dict(),
            {
                "revision": 9,
                "position": (1, 2),
                "size": (3, 4),
                "output": "DP-2",
            },
        )


if __name__ == "__main__":
    unittest.main()
