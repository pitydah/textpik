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


class QtDBusAsyncTransportTest(unittest.TestCase):
    """The real transport must defer its reply instead of blocking the caller.

    The service is registered for the duration of the test on purpose. Without
    an owner the interface is invalid and the transport answers from its early
    return, which would pass a timing assertion without ever exercising the
    asynchronous path.
    """

    def setUp(self):
        try:
            from PySide6.QtCore import QObject
            from PySide6.QtDBus import QDBusConnection
        except ImportError:  # pragma: no cover - depends on Qt install
            self.skipTest("QtDBus no disponible")

        self.bus = QDBusConnection.sessionBus()
        if not self.bus.isConnected():
            self.skipTest("sin bus de sesion")

        self.owned_service = bool(self.bus.registerService(SERVICE_NAME))
        self.holder = QObject()
        self.bus.registerObject(
            OBJECT_PATH, self.holder, QDBusConnection.ExportAllSlots
        )

    def tearDown(self):
        if getattr(self, "holder", None) is not None:
            self.bus.unregisterObject(OBJECT_PATH)
            self.holder = None
        if getattr(self, "owned_service", False):
            self.bus.unregisterService(SERVICE_NAME)

    def test_async_call_defers_the_reply_instead_of_blocking(self):
        from time import monotonic

        from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

        from src.textpik_core.placement_client import QtDBusPlacementTransport

        app = QCoreApplication.instance() or QCoreApplication([])
        transport = QtDBusPlacementTransport(timeout_ms=200)
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

        loop = QEventLoop()
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(2000)
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if delivered else None)
        poll.start(20)
        loop.exec()

        self.assertTrue(delivered, "el callback asincrono nunca llego")
        self.assertIsInstance(delivered[0], bool)
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
