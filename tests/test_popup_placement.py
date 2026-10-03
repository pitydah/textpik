"""Tests for the popup placement authority wiring.

These pin the rule that broke placement on Plasma Wayland: the popup may never
report a verified position unless a compositor-side authority confirmed it, and
a confirmation that no longer belongs to the current request must be dropped.
"""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.textpik import (
    DEFAULT_ACTIONS,
    DEFAULT_SETTINGS,
    PLACEMENT_PROBE_TTL,
    PLACEMENT_REVEAL_DEADLINE_MS,
    PopupWindow,
)
from src.textpik_core.models import PlacementBackend, Point
from src.textpik_core.placement import PlacementBackendChoice
from src.textpik_core.placement_client import KWinPlacementClient


class FakeTransport:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = dict(replies or {})
        self.error = ""

    def call(self, method, *args):
        self.calls.append((method, args))
        reply = self.replies.get(method, (True, []))
        if isinstance(reply, Exception):
            self.error = str(reply)
            return False, []
        return reply

    def call_async(self, method, *args, on_done):
        """Deliver immediately so the popup flow keeps its shape in tests."""
        ok, arguments = self.call(method, *args)
        on_done(ok, arguments)


class PopupPlacementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_popup(self):
        popup = PopupWindow(DEFAULT_ACTIONS[:4], None, dict(DEFAULT_SETTINGS))
        popup.resize(240, 33)
        return popup

    def force_backend(self, popup, backend, authoritative=False):
        popup._placement_choice = PlacementBackendChoice(
            backend, authoritative, reason="test-forced"
        )
        # Relative future stamp: the cache check subtracts ``now``, so an
        # absolute constant would depend on the monotonic clock's base.
        popup._placement_probed_at = time.monotonic() + 3600.0

    # -- backend selection -------------------------------------------------

    def test_offscreen_session_is_not_authoritative(self):
        popup = self.make_popup()
        choice = popup._placement_backend_choice()
        self.assertFalse(choice.authoritative)
        self.assertEqual(choice.backend.value, "unavailable")

    def test_backend_choice_is_cached_within_the_ttl(self):
        popup = self.make_popup()
        first = popup._placement_backend_choice()
        popup._placement_probed_at = 0.0
        popup._placement_choice = None
        second = popup._placement_backend_choice()
        self.assertEqual(first.backend, second.backend)

    def test_probe_ttl_is_short_enough_to_notice_a_late_effect(self):
        self.assertLessEqual(PLACEMENT_PROBE_TTL, 5.0)

    # -- unverified backends ----------------------------------------------

    def test_unverified_backend_never_claims_an_observed_position(self):
        popup = self.make_popup()
        self.force_backend(
            popup, PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED, authoritative=False
        )
        popup._report_placement(Point(1, 2), Point(1, 2), 240, 33)

        result = popup.last_placement_result
        self.assertIsNotNone(result)
        self.assertFalse(result.verified)
        self.assertIsNone(result.observed)
        self.assertEqual(result.backend.value, "qt-xdg-toplevel-unverified")

    def test_toolkit_position_is_not_evidence_even_when_it_matches(self):
        """The popup can report its own move, and it still must not verify."""
        popup = self.make_popup()
        self.force_backend(
            popup, PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED, authoritative=False
        )
        popup.move(700, 460)
        popup._report_placement(Point(700, 460), Point(700, 460), 240, 33)

        result = popup.last_placement_result
        self.assertFalse(result.verified)
        self.assertIsNone(result.observed)

    def test_x11_backend_reports_the_post_map_position(self):
        popup = self.make_popup()
        self.force_backend(popup, PlacementBackend.X11, authoritative=True)
        popup.move(120, 90)
        popup.show()
        self.app.processEvents()
        popup._report_placement(Point(120, 90), Point(120, 90), 240, 33)

        result = popup.last_placement_result
        self.assertIsNotNone(result)
        self.assertEqual(result.observed.as_tuple(), (120, 90))
        popup.hide()

    # -- compositor authority ---------------------------------------------

    def test_confirmed_placement_is_verified(self):
        popup = self.make_popup()
        client = KWinPlacementClient(
            FakeTransport(
                {
                    "requestPlacement": (True, []),
                    "readback": (True, ["1,1,700,460,240,33,DP-2"]),
                }
            )
        )
        popup._placement_client = client
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)
        popup.show()
        popup._report_placement(Point(700, 460), Point(700, 460), 240, 33)

        result = popup.last_placement_result
        self.assertTrue(result.verified)
        self.assertEqual(result.observed.as_tuple(), (700, 460))
        self.assertEqual(result.output, "DP-2")
        popup.hide()

    def test_mismatched_compositor_position_is_not_verified(self):
        popup = self.make_popup()
        client = KWinPlacementClient(
            FakeTransport(
                {
                    "requestPlacement": (True, []),
                    "readback": (True, ["1,1,960,540,240,33,DP-2"]),
                }
            )
        )
        popup._placement_client = client
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)
        popup.show()
        popup._report_placement(Point(700, 460), Point(700, 460), 240, 33)

        result = popup.last_placement_result
        self.assertFalse(result.verified)
        self.assertEqual(result.error, "position-mismatch")
        popup.hide()

    def test_unreachable_effect_is_recorded_honestly(self):
        popup = self.make_popup()
        client = KWinPlacementClient(
            FakeTransport({"requestPlacement": RuntimeError("no servicio")})
        )
        popup._placement_client = client
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)
        popup.show()
        popup._report_placement(Point(700, 460), Point(700, 460), 240, 33)

        result = popup.last_placement_result
        self.assertFalse(result.verified)
        self.assertEqual(result.error, "effect-unreachable")
        popup.hide()

    def test_hiding_the_popup_drops_pending_confirmations(self):
        popup = self.make_popup()
        client = KWinPlacementClient(
            FakeTransport(
                {
                    "requestPlacement": (True, []),
                    "readback": (True, ["1,1,700,460,240,33,DP-2"]),
                }
            )
        )
        popup._placement_client = client
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)
        popup.show()

        revision = popup._placement_lease.begin()
        popup.hide()
        self.assertFalse(popup._placement_lease.accept(revision))

    def test_backend_from_another_module_instance_is_still_understood(self):
        """Placement must compare backend values, not enum object identity.

        CI installs the project editable, so ``textpik_core`` and
        ``src.textpik_core`` become two module objects holding two enum classes
        for the same values. An identity comparison would silently fall back to
        the unverified path and this test would fail.
        """
        from src.textpik_core.models import PlacementBackend as other_module

        popup = self.make_popup()
        popup._placement_client = KWinPlacementClient(
            FakeTransport(
                {
                    "requestPlacement": (True, []),
                    "readback": (True, ["1,1,700,460,240,33,DP-2"]),
                }
            )
        )
        popup._placement_choice = PlacementBackendChoice(
            other_module.KWIN_EFFECT, True, reason="other-module"
        )
        popup._placement_probed_at = time.monotonic() + 3600.0
        popup.show()
        popup._report_placement(Point(700, 460), Point(700, 460), 240, 33)

        result = popup.last_placement_result
        self.assertTrue(result.verified, f"backend no reconocido: {result.error}")
        self.assertEqual(result.observed.as_tuple(), (700, 460))
        popup.hide()

    def test_a_lost_reply_never_leaves_the_popup_invisible(self):
        """Asynchronous replies can be lost; the cloak must still lift.

        With blocking calls the D-Bus timeout guaranteed progress. Now that the
        placement calls return immediately, a reply that never arrives would
        leave the popup cloaked forever without its own deadline.
        """
        from PySide6.QtCore import QEventLoop, QTimer

        class SilentTransport:
            error = ""

            def call(self, method, *args):
                return False, []

            def call_async(self, method, *args, on_done):
                return None  # la respuesta nunca llega

        popup = self.make_popup()
        popup._placement_client = KWinPlacementClient(SilentTransport())
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)

        # The real path: show_at_cursor decides to cloak and owns the deadline.
        popup.show_at_cursor()
        self.assertTrue(
            popup._placement_hidden_for_authority,
            "el popup deberia estar oculto esperando al compositor",
        )

        loop = QEventLoop()
        QTimer.singleShot(PLACEMENT_REVEAL_DEADLINE_MS + 120, loop.quit)
        loop.exec()

        self.assertFalse(
            popup._placement_hidden_for_authority,
            "el popup quedo invisible esperando una respuesta que nunca llego",
        )
        # A lost reply skips the retry ladder, so the deadline is the only place
        # that can leave the diagnostic with an honest answer.
        result = popup.last_placement_result
        self.assertIsNotNone(result, "el diagnostico quedo sin resultado")
        self.assertFalse(result.verified)
        self.assertEqual(result.error, "effect-timeout")
        self.assertIsNone(result.observed)
        popup.hide()

    def test_late_confirmation_for_a_newer_selection_is_dropped(self):
        popup = self.make_popup()
        client = KWinPlacementClient(
            FakeTransport(
                {
                    "requestPlacement": (True, []),
                    "readback": (True, ["1,1,700,460,240,33,DP-2"]),
                }
            )
        )
        popup._placement_client = client
        self.force_backend(popup, PlacementBackend.KWIN_EFFECT, authoritative=True)
        popup.show()

        first = popup._placement_lease.begin()
        popup._placement_lease.begin()  # the user selected again
        popup._store_placement_result(
            Point(1, 1),
            Point(1, 1),
            240,
            33,
            first,
            client.readback(first),
            None,
        )

        result = popup.last_placement_result
        self.assertFalse(result.verified)
        self.assertIsNone(result.observed)
        popup.hide()


if __name__ == "__main__":
    unittest.main()
