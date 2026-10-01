"""Contract tests for the compositor-side placement client.

The client sits between TextPik and the KWin effect. These tests pin the
protocol rules that make ``verified`` trustworthy: a confirmation must belong
to the revision we asked about, it must carry a real window, and any transport
failure has to degrade to "not verified" instead of raising into the selection
hot path.
"""

from src.textpik_core.models import Point
from src.textpik_core.placement_client import (
    INTERFACE_NAME,
    OBJECT_PATH,
    SERVICE_NAME,
    PlacementConfirmation,
    KWinPlacementClient,
)


class FakeTransport:
    """Records calls and replays scripted replies."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = dict(replies or {})
        self.error = ""

    def call(self, method, *args):
        self.calls.append((method, args))
        reply = self.replies.get(method, (True, []))
        if callable(reply):
            return reply(args)
        if isinstance(reply, Exception):
            self.error = str(reply)
            return False, []
        return reply

    def methods(self):
        return [name for name, _ in self.calls]


class TestContract:
    def test_service_contract_matches_the_effect(self):
        assert SERVICE_NAME == "org.textpik.KWinPlacement"
        assert INTERFACE_NAME == "org.textpik.KWinPlacement"
        assert OBJECT_PATH == "/KWinPlacement"


class TestAvailability:
    def test_available_when_readback_answers(self):
        client = KWinPlacementClient(FakeTransport({"readback": (True, ["7,0,0,0,0,0,"])}))
        assert client.available() is True

    def test_unavailable_when_transport_fails(self):
        transport = FakeTransport({"readback": RuntimeError("no such service")})
        client = KWinPlacementClient(transport)
        assert client.available() is False
        assert client.last_error

    def test_available_probes_without_arguments(self):
        transport = FakeTransport({"readback": (True, ["0,0,0,0,0,0,"])})
        KWinPlacementClient(transport).available()
        assert transport.calls == [("readback", ())]


class TestRequests:
    def test_request_sends_ints_in_protocol_order(self):
        transport = FakeTransport({"requestPlacement": (True, [])})
        client = KWinPlacementClient(transport)
        assert client.request(41, 1440, 720, 320, 90) is True
        assert transport.calls == [
            ("requestPlacement", (41, 1440, 720, 320, 90)),
        ]

    def test_request_reports_transport_failure(self):
        transport = FakeTransport({"requestPlacement": RuntimeError("stalled")})
        assert KWinPlacementClient(transport).request(1, 0, 0, 10, 10) is False

    def test_register_window_sends_identifier(self):
        transport = FakeTransport({"registerTextPikWindow": (True, [])})
        KWinPlacementClient(transport).register_window("abc")
        assert transport.calls == [("registerTextPikWindow", ("abc",))]

    def test_register_window_without_identifier_sends_empty_string(self):
        transport = FakeTransport({"registerTextPikWindow": (True, [])})
        KWinPlacementClient(transport).register_window()
        assert transport.calls == [("registerTextPikWindow", ("",))]

    def test_unregister_window_is_reachable(self):
        transport = FakeTransport({"unregisterTextPikWindow": (True, [])})
        assert KWinPlacementClient(transport).unregister_window() is True
        assert transport.methods() == ["unregisterTextPikWindow"]


class TestReadback:
    def _client(self, payload):
        return KWinPlacementClient(FakeTransport({"readback": (True, [payload])}))

    def test_parses_a_matching_confirmation(self):
        result = self._client("41,1,1440,720,320,90,DP-2").readback(41)
        assert result == PlacementConfirmation(
            revision=41, position=Point(1440, 720), size=(320, 90), output="DP-2"
        )

    def test_missing_window_is_not_a_position(self):
        assert self._client("41,0,0,0,0,0,").readback(41) is None

    def test_superseded_revision_is_rejected(self):
        """The effect replies with the revision it processed, not an echo."""
        assert self._client("42,1,1440,720,320,90,DP-2").readback(41) is None

    def test_empty_output_name_is_accepted(self):
        result = self._client("3,1,10,20,30,40,").readback(3)
        assert result is not None
        assert result.output == ""

    def test_output_name_containing_commas_is_kept_whole(self):
        result = self._client("3,1,10,20,30,40,HDMI,A-1").readback(3)
        assert result is not None
        assert result.output == "HDMI,A-1"

    def test_malformed_payload_is_rejected(self):
        assert self._client("garbage").readback(1) is None
        assert self._client("1,1,not,int,3,4,DP-2").readback(1) is None
        assert self._client("").readback(1) is None

    def test_transport_failure_yields_none(self):
        client = KWinPlacementClient(FakeTransport({"readback": RuntimeError("down")}))
        assert client.readback(7) is None

    def test_confirmation_serializes_for_logging(self):
        confirmation = PlacementConfirmation(
            revision=9, position=Point(1, 2), size=(3, 4), output="DP-2"
        )
        assert confirmation.as_dict() == {
            "revision": 9,
            "position": (1, 2),
            "size": (3, 4),
            "output": "DP-2",
        }
