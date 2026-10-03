import inspect
import os
import unittest
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.textpik import PopupWindow, SelectionContext, TextPikApp
from src.textpik_core.anchors import AnchorResolver
from src.textpik_core.integration import _host_is_private
from src.textpik_core.models import AnchorSource, PopupAnchor
from src.textpik_core.wayland import CapabilityTruth, build_wayland_profile


class CursorFirstAnchorV15Test(unittest.TestCase):
    def test_fresh_kwin_cursor_outranks_atspi_geometry(self):
        now = monotonic()
        winner = AnchorResolver().resolve(
            (
                PopupAnchor(100, 100, AnchorSource.ATSPI_SELECTION, 1.0, now),
                PopupAnchor(120, 120, AnchorSource.KWIN, 0.98, now - 0.01),
            )
        )
        self.assertIsNotNone(winner)
        self.assertEqual(winner.source, AnchorSource.KWIN)

    def test_stale_cursor_falls_back_to_atspi(self):
        now = monotonic()
        winner = AnchorResolver().resolve(
            (
                PopupAnchor(100, 100, AnchorSource.ATSPI_SELECTION, 1.0, now),
                PopupAnchor(120, 120, AnchorSource.KWIN, 0.98, now - 10.0, 0.1),
            )
        )
        self.assertIsNotNone(winner)
        self.assertEqual(winner.source, AnchorSource.ATSPI_SELECTION)


class LanguageToolTransportV15Test(unittest.TestCase):
    def test_only_explicit_private_lan_ranges_get_http_downgrade(self):
        for host in (
            "10.2.3.4", "172.16.0.1", "172.31.255.254", "192.168.50.10",
            "169.254.10.2", "fc00::1", "fd12:3456::1", "fe80::1",
        ):
            with self.subTest(host=host):
                self.assertTrue(_host_is_private(host))

        for host in (
            "192.0.2.1", "198.51.100.1", "203.0.113.1",
            "198.18.0.1", "2001:db8::1", "grammar.lan",
        ):
            with self.subTest(host=host):
                self.assertFalse(_host_is_private(host))

    def test_private_host_policy_does_not_resolve_dns(self):
        with patch("socket.getaddrinfo") as getaddrinfo:
            self.assertTrue(_host_is_private("grammar.home.arpa"))
            self.assertFalse(_host_is_private("grammar.lan"))
        getaddrinfo.assert_not_called()


class WaylandPlacementTruthV15Test(unittest.TestCase):
    def test_loaded_kwin_effect_upgrades_only_positioning(self):
        profile = build_wayland_profile(
            platform_name="wayland",
            desktop="Plasma",
            kwin_cursor_bridge=True,
            kwin_activation_bridge=True,
            kwin_placement_effect=True,
        )
        self.assertEqual(profile.positioning, CapabilityTruth.VERIFIED)
        self.assertEqual(profile.positioning_backend, "kwin-effect")
        self.assertEqual(profile.global_pointer_buttons, CapabilityTruth.UNAVAILABLE)
        self.assertEqual(profile.outside_click, CapabilityTruth.DEGRADED)

    def test_popup_maps_cloaked_before_kwin_confirmation(self):
        source = inspect.getsource(PopupWindow.show_at_cursor)
        cloak = source.index("_set_placement_revealed(not cloak_for_compositor)")
        show = source.index("self.show()")
        report = source.index("self._report_placement(")
        self.assertLess(cloak, show)
        self.assertLess(show, report)


class SelectionAuthorityV15Test(unittest.TestCase):
    def test_raw_atspi_event_does_not_open_a_new_session(self):
        source = inspect.getsource(TextPikApp._queue_atspi_selection)
        self.assertNotIn('_begin_selection_session("atspi-event")', source)
        self.assertIn("base_session = self._selection_session", source)

    def test_automatic_show_does_not_traverse_atspi(self):
        source = inspect.getsource(TextPikApp.show_popup)
        self.assertIn("if force and atspi_context is None", source)
        automatic_prefix = source.split("if force and atspi_context is None", 1)[0]
        self.assertNotIn("self.atspi.read_selection()", automatic_prefix)

    def test_action_payload_contains_frozen_context(self):
        source = inspect.getsource(PopupWindow._on_click)
        self.assertIn("self._selection_context.action_snapshot()", source)
        self.assertIn("self.action_triggered.emit(cmd, text, context)", source)

    def test_snapshot_is_independent_from_later_context_replacement(self):
        context = SelectionContext(
            text="A",
            application="editor",
            editable=True,
            selection_start=1,
            selection_end=2,
            backend="atspi",
            selection_rect=(1, 2, 3, 4),
            native_handle=object(),
        )
        frozen = context.action_snapshot()
        context.text = "B"
        context.application = "other"
        self.assertEqual(frozen.text, "A")
        self.assertEqual(frozen.application, "editor")
        self.assertEqual(frozen.selection_rect, (1, 2, 3, 4))


class AtspiAdaptiveRequeueV15Test(unittest.TestCase):
    """Behavioural guard for the AT-SPI adaptive-delay re-queue path.

    Regression: that branch referenced a session id that is only assigned much
    later, so it raised NameError at runtime. No other test reached it because
    it needs the adaptive delay to still be pending when the payload arrives.
    """

    def test_requeue_keeps_the_session_the_event_arrived_in(self):
        now = monotonic()
        context = SelectionContext(
            text="hola mundo",
            application="editor",
            backend="atspi",
            selection_start=0,
            selection_end=10,
            native_handle=object(),
        )
        app = SimpleNamespace(
            atspi=SimpleNamespace(context_menu_active=lambda: False),
            monitor=SimpleNamespace(
                secondary_interaction_active=lambda: False,
                selection_input_ready=lambda: True,
            ),
            popup=SimpleNamespace(isVisible=lambda: False),
            popup_state=Mock(),
            atspi_event_timer=Mock(),
            settings={
                "adaptive_delay_enabled": True,
                "adaptive_delay_min_ms": 250,
                "adaptive_delay_max_ms": 250,
            },
            _selection_session=7,
            _pending_atspi_node=(context, 7, now),
        )

        TextPikApp._consume_atspi_selection(app)

        queued = app._pending_atspi_node
        self.assertIsNotNone(queued, "el evento debe re-encolarse, no descartarse")
        queued_context, queued_session, _ = queued
        self.assertIs(queued_context, context)
        self.assertEqual(
            queued_session, 7, "no debe reclamar una generacion nueva"
        )
        app.atspi_event_timer.start.assert_called_once()

    def test_requeue_is_dropped_when_another_source_moved_on(self):
        now = monotonic()
        context = SelectionContext(
            text="hola mundo",
            application="editor",
            backend="atspi",
            selection_start=0,
            selection_end=10,
            native_handle=object(),
        )
        app = SimpleNamespace(
            atspi=SimpleNamespace(context_menu_active=lambda: False),
            monitor=SimpleNamespace(
                secondary_interaction_active=lambda: False,
                selection_input_ready=lambda: True,
            ),
            popup=SimpleNamespace(isVisible=lambda: False),
            popup_state=Mock(),
            atspi_event_timer=Mock(),
            settings={
                "adaptive_delay_enabled": True,
                "adaptive_delay_min_ms": 250,
                "adaptive_delay_max_ms": 250,
            },
            # Clipboard already opened a newer session.
            _selection_session=8,
            _pending_atspi_node=(context, 7, now),
        )

        TextPikApp._consume_atspi_selection(app)

        self.assertIsNone(app._pending_atspi_node)
        app.atspi_event_timer.start.assert_not_called()


class KWinEffectSourceV15Test(unittest.TestCase):
    def test_pending_request_is_replayed_when_window_maps(self):
        source = Path("native/kwin-effect/effect.cpp").read_text(encoding="utf-8")
        self.assertIn("m_hasPendingPlacement = true", source)
        self.assertIn("applyPendingPlacement();", source)
        self.assertIn("placement queued until popup window is mapped", source)

    def test_effect_targets_only_main_popup(self):
        source = Path("native/kwin-effect/effect.cpp").read_text(encoding="utf-8")
        self.assertIn('s_windowCaption = "textpik-popup"', source)
        self.assertIn("isTextPikPopup", source)

    def test_installed_effect_is_enabled_by_default(self):
        metadata = Path("native/kwin-effect/metadata.json").read_text(encoding="utf-8")
        self.assertIn('"EnabledByDefault": true', metadata)


if __name__ == "__main__":
    unittest.main()
