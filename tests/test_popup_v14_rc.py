import inspect
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.textpik import BaseSelectionMonitor, CursorBridge, SettingsDialog, TextPikApp
from src.textpik_core.integration import (
    GRAMMAR_ENDPOINT_INSECURE_REMOTE,
    GRAMMAR_ENDPOINT_INVALID,
    GRAMMAR_ENDPOINT_LOCAL,
    GRAMMAR_ENDPOINT_REMOTE_BLOCKED,
    GRAMMAR_ENDPOINT_REMOTE_OPT_IN,
    GRAMMAR_ENDPOINT_UNREACHABLE,
    _local_http_endpoint,
    grammar_endpoint_verdict,
    probe_runtime_capabilities,
)
from src.textpik_core.settings import DEFAULT_SETTINGS, normalize_settings
from src.textpik_core.wayland import CapabilityTruth, build_wayland_profile


def code_only(func):
    """Source of func with '#' comments stripped.

    Source-text assertions stay readable for code that needs a live AT-SPI bus
    or a full QApplication, but they must not be satisfiable by prose: an
    earlier version of this file failed because it matched a phrase that only
    existed inside a comment.
    """
    return "\n".join(
        line.split("#", 1)[0] for line in inspect.getsource(func).splitlines()
    )


class RuntimeProbeV14Test(unittest.TestCase):
    def test_ollama_probe_is_loopback_only_even_before_settings_normalization(self):
        self.assertTrue(_local_http_endpoint("http://127.0.0.1:11434/api/generate"))
        self.assertTrue(_local_http_endpoint("http://localhost:11434/api/generate"))
        self.assertTrue(_local_http_endpoint("http://[::1]:11434/api/generate"))
        self.assertFalse(_local_http_endpoint("https://example.com/api/generate"))

        with patch("src.textpik_core.integration.urllib.request.urlopen") as open_url:
            probe_runtime_capabilities(
                ollama_endpoint="https://example.com/api/generate",
                grammar_endpoint="invalid://disabled",
            )
        open_url.assert_not_called()

    def test_malformed_provider_payloads_do_not_crash_the_probe(self):
        # A local service or proxy can answer with an error object or a bare
        # scalar. The probe must degrade to "not available", never raise.
        cases = (
            ("[]", '{"languages": []}'),
            ('"oops"', '{"languages": []}'),
            ('{"models": 5}', '{"languages": []}'),
            ('{"models": []}', "{}"),
            ('{"models": []}', '"hola"'),
        )
        for tags, languages in cases:
            with self.subTest(tags=tags, languages=languages):
                payloads = iter((tags, languages))

                class _Response(io.BytesIO):
                    def __enter__(self):
                        return self

                    def __exit__(self, *_exc):
                        return False

                def fake_urlopen(_url, timeout=None):
                    return _Response(next(payloads).encode())

                with patch(
                    "src.textpik_core.integration.urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):
                    caps = probe_runtime_capabilities()
                self.assertEqual(caps.ollama_models, ())
                self.assertFalse(caps.grammar_ready)
                self.assertEqual(caps.grammar_languages, ())

    def test_grammar_probe_refuses_non_loopback_endpoint(self):
        # languagetool_endpoint is free-form user input; a remote host must not
        # be contacted during a capability probe.
        with patch(
            "src.textpik_core.integration.urllib.request.urlopen"
        ) as open_url:
            caps = probe_runtime_capabilities(
                grammar_endpoint="https://api.languagetool.org/v2/languages"
            )
        # The default Ollama endpoint is loopback, so a local probe is expected.
        # What must never happen is contacting the remote grammar host.
        contacted = [str(call.args[0]) for call in open_url.call_args_list]
        self.assertFalse(
            any("languagetool.org" in url for url in contacted),
            f"remote grammar host was contacted: {contacted}",
        )
        self.assertFalse(caps.grammar_ready)


class GrammarEndpointPolicyTest(unittest.TestCase):
    """LanguageTool remote access is an explicit opt-in, not a product invariant.

    Ollama is loopback-only by definition. LanguageTool is not: a NAS, a VPS or
    a deliberately chosen public service is a legitimate deployment. So the two
    services keep separate policies, and the default is fail-closed.
    """

    LANGUAGES_PAYLOAD = '[{"longCode": "en-US"}]'

    def _probe(self, endpoint: str, *, allow_remote: bool):
        """Probe with a recorded urlopen, returning (capabilities, contacted)."""
        with patch(
            "src.textpik_core.integration.urllib.request.urlopen"
        ) as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = (
                self.LANGUAGES_PAYLOAD.encode()
            )
            caps = probe_runtime_capabilities(
                grammar_endpoint=endpoint,
                grammar_allow_remote=allow_remote,
                ollama_endpoint="invalid://disabled",
            )
        return caps, [str(call.args[0]) for call in open_url.call_args_list]

    def test_loopback_is_allowed_without_the_opt_in(self):
        for endpoint in (
            "http://127.0.0.1:8010/v2/languages",
            "https://localhost:8010/v2/languages",
            "http://[::1]:8010/v2/languages",
        ):
            with self.subTest(endpoint=endpoint):
                caps, contacted = self._probe(endpoint, allow_remote=False)
                self.assertTrue(caps.grammar_ready)
                self.assertEqual(
                    caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_LOCAL
                )
                self.assertIn(endpoint, contacted)

    def test_remote_without_opt_in_receives_no_request_at_all(self):
        # The core privacy guarantee: not "blocked after contacting", but never
        # opened. api.languagetool.org is not enabled by default, but a user who
        # types that endpoint may still opt in.
        caps, contacted = self._probe(
            "https://api.languagetool.org/v2/languages", allow_remote=False
        )
        self.assertEqual(contacted, [], f"remote host was contacted: {contacted}")
        self.assertFalse(caps.grammar_ready)
        self.assertEqual(caps.grammar_languages, ())
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_REMOTE_BLOCKED
        )

    def test_https_remote_is_allowed_once_opted_in(self):
        caps, contacted = self._probe(
            "https://api.languagetool.org/v2/languages", allow_remote=True
        )
        self.assertTrue(caps.grammar_ready)
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_REMOTE_OPT_IN
        )
        self.assertEqual(
            contacted, ["https://api.languagetool.org/v2/languages"]
        )

    def test_private_lan_may_use_plain_http_when_opted_in(self):
        # A self-hosted LanguageTool on the LAN is the common remote case and
        # TLS is frequently not set up there.
        for endpoint in (
            "http://192.168.1.50:8012/v2/languages",
            "http://10.0.0.7:8012/v2/languages",
            "http://grammar.local:8012/v2/languages",
        ):
            with self.subTest(endpoint=endpoint):
                caps, contacted = self._probe(endpoint, allow_remote=True)
                self.assertTrue(caps.grammar_ready)
                self.assertEqual(
                    caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_REMOTE_OPT_IN
                )
                self.assertEqual(len(contacted), 1)

    def test_unreserved_name_over_plain_http_is_treated_as_public(self):
        # The HTTPS downgrade is only for hosts provably on the LAN. A made-up
        # private-looking suffix must not become a way to ship cleartext text.
        caps, contacted = self._probe(
            "http://grammar.lan:8012/v2/languages", allow_remote=True
        )
        self.assertEqual(contacted, [], f"cleartext was sent: {contacted}")
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_INSECURE_REMOTE
        )

    def test_private_lan_is_still_blocked_without_the_opt_in(self):
        caps, contacted = self._probe(
            "http://192.168.1.50:8010/v2/languages", allow_remote=False
        )
        self.assertEqual(contacted, [], f"LAN host was contacted: {contacted}")
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_REMOTE_BLOCKED
        )

    def test_public_host_requires_https_even_when_opted_in(self):
        # Opting in permits a remote server; it does not permit cleartext text
        # on the public internet.
        caps, contacted = self._probe(
            "http://api.languagetool.org/v2/languages", allow_remote=True
        )
        self.assertEqual(contacted, [], f"cleartext remote was contacted: {contacted}")
        self.assertFalse(caps.grammar_ready)
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_INSECURE_REMOTE
        )

    def test_opt_out_closes_the_remote_again(self):
        # Toggling the setting back off must restore the fail-closed state; the
        # opt-in is read per probe, not cached from a previous success.
        endpoint = "https://grammar.example.internal/v2/languages"
        caps_on, _ = self._probe(endpoint, allow_remote=True)
        self.assertTrue(caps_on.grammar_ready)
        caps_off, contacted_off = self._probe(endpoint, allow_remote=False)
        self.assertEqual(contacted_off, [])
        self.assertFalse(caps_off.grammar_ready)
        self.assertEqual(
            caps_off.grammar_endpoint_state, GRAMMAR_ENDPOINT_REMOTE_BLOCKED
        )

    def test_unreachable_is_distinguished_from_blocked(self):
        # "no request because policy" and "request sent, server down" need
        # different words, or the user debugs the wrong thing.
        with patch(
            "src.textpik_core.integration.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            caps = probe_runtime_capabilities(
                grammar_endpoint="http://127.0.0.1:8010/v2/languages",
                ollama_endpoint="invalid://disabled",
            )
        self.assertFalse(caps.grammar_ready)
        self.assertEqual(
            caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_UNREACHABLE
        )

    def test_invalid_endpoint_is_reported_as_invalid(self):
        for endpoint in ("", "   ", "ftp://host/x", "not a url"):
            with self.subTest(endpoint=endpoint):
                caps, contacted = self._probe(endpoint, allow_remote=True)
                self.assertEqual(contacted, [])
                self.assertEqual(
                    caps.grammar_endpoint_state, GRAMMAR_ENDPOINT_INVALID
                )


class GrammarOptInSettingsTest(unittest.TestCase):
    """The opt-in must be fail-closed and must never be inferred on upgrade."""

    def test_default_settings_block_remote(self):
        self.assertIs(DEFAULT_SETTINGS["grammar_allow_remote"], False)
        self.assertEqual(
            normalize_settings({})["grammar_allow_remote"], False
        )

    def test_migration_does_not_infer_opt_in_from_a_remote_endpoint(self):
        # An existing user with a remote endpoint configured must not start
        # shipping text off-box merely by upgrading.
        migrated = normalize_settings(
            {
                "languagetool_endpoint": "https://api.languagetool.org/v2/check",
            }
        )
        self.assertIs(migrated["grammar_allow_remote"], False)
        # The endpoint itself is preserved so the UI can explain the block
        # instead of silently rewriting the user's configuration.
        self.assertEqual(
            migrated["languagetool_endpoint"],
            "https://api.languagetool.org/v2/check",
        )

    def test_explicit_opt_in_survives_normalization(self):
        self.assertIs(
            normalize_settings({"grammar_allow_remote": True})[
                "grammar_allow_remote"
            ],
            True,
        )

    def test_ollama_and_grammar_policies_are_not_the_same_contract(self):
        # Regression guard for collapsing both services into one function:
        # Ollama has no opt-in path at all, LanguageTool has one.
        self.assertFalse(_local_http_endpoint("https://api.example.com/x"))
        self.assertEqual(
            grammar_endpoint_verdict(
                "https://api.example.com/x", allow_remote=True
            ),
            (True, GRAMMAR_ENDPOINT_REMOTE_OPT_IN),
        )

    def test_status_text_names_the_cause_instead_of_saying_offline(self):
        # A blocked endpoint never opened a socket, so "sin conexión" would
        # send the user to debug a server that was never contacted.
        def status(state, ready=False, languages=()):
            caps = SimpleNamespace(
                grammar_ready=ready,
                grammar_languages=tuple(languages),
                grammar_endpoint_state=state,
            )
            return SettingsDialog._grammar_status_text(None, caps)

        self.assertIn("idioma(s)", status(GRAMMAR_ENDPOINT_LOCAL, True, ["en"]))
        self.assertIn("remoto autorizado", status(GRAMMAR_ENDPOINT_REMOTE_OPT_IN, True, ["en"]))
        self.assertIn("Permitir servidor", status(GRAMMAR_ENDPOINT_REMOTE_BLOCKED))
        self.assertIn("HTTPS", status(GRAMMAR_ENDPOINT_INSECURE_REMOTE))
        self.assertIn("inválido", status(GRAMMAR_ENDPOINT_INVALID))
        self.assertIn("sin conexión", status(GRAMMAR_ENDPOINT_UNREACHABLE))
        for state in (
            GRAMMAR_ENDPOINT_REMOTE_BLOCKED,
            GRAMMAR_ENDPOINT_INSECURE_REMOTE,
            GRAMMAR_ENDPOINT_INVALID,
        ):
            with self.subTest(state=state):
                self.assertNotIn("sin conexión", status(state))


class WaylandTruthV14Test(unittest.TestCase):
    def test_generic_wayland_never_claims_global_pointer_authority(self):
        profile = build_wayland_profile(
            platform_name="wayland",
            desktop="GNOME",
        )
        self.assertEqual(
            profile.global_pointer_buttons,
            CapabilityTruth.UNAVAILABLE,
        )
        self.assertEqual(profile.outside_click, CapabilityTruth.UNAVAILABLE)
        self.assertEqual(profile.positioning, CapabilityTruth.DEGRADED)
        self.assertEqual(
            profile.required_backend,
            "gnome-shell-presentation-integration",
        )

    def test_plasma_cursor_bridge_does_not_claim_placement(self):
        profile = build_wayland_profile(
            platform_name="wayland",
            desktop="KDE",
            kwin_cursor_bridge=True,
            kwin_activation_bridge=True,
        )
        self.assertEqual(profile.pointer_position, CapabilityTruth.VERIFIED)
        self.assertEqual(profile.positioning, CapabilityTruth.DEGRADED)
        self.assertEqual(profile.outside_click, CapabilityTruth.DEGRADED)
        self.assertIn("kwin-effect", profile.required_backend)

    def test_monitor_does_not_use_qt_buttons_as_wayland_global_state(self):
        # Behavioural: on Wayland the pointer state is UNKNOWN, so even a Qt
        # report of "left button down" must not become a global truth. Asserting
        # on source text previously matched the phrase inside a comment.
        monitor = BaseSelectionMonitor()
        with patch("src.textpik.is_wayland", return_value=True), patch.object(
            QApplication, "mouseButtons", return_value=Qt.LeftButton
        ):
            self.assertIsNone(monitor._primary_button_state())
            self.assertFalse(monitor._primary_button_pressed())
            # UNKNOWN must not be treated as "released" either: with no
            # recorded activity the quiet period has not elapsed yet.
            self.assertFalse(monitor.selection_input_ready())

    def test_wayland_quiet_period_elapses_only_after_recorded_activity(self):
        monitor = BaseSelectionMonitor()
        with patch("src.textpik.is_wayland", return_value=True):
            self.assertFalse(monitor.selection_input_ready())
            monitor.note_selection_activity()
            self.assertFalse(monitor.selection_input_ready())
            monitor._last_selection_activity_at -= 0.2
            self.assertTrue(monitor.selection_input_ready())

    def test_primary_button_pressed_override_still_controls_the_guard(self):
        # _primary_button_pressed stays the overridable seam; the quiet-period
        # helper must not bypass it.
        monitor = BaseSelectionMonitor()
        with patch.object(monitor, "_primary_button_pressed", return_value=True):
            self.assertFalse(monitor.selection_input_ready())

    def test_outside_click_does_not_fabricate_wayland_pointer_state(self):
        source = code_only(TextPikApp.hide_popup_on_external_click)
        self.assertIn("if is_qt_wayland():", source)
        # The Wayland branch must bail out before any Qt button/pos read.
        branch = source.split("if is_qt_wayland():", 1)[1]
        self.assertLess(branch.index("return"), branch.index("QApplication.mouseButtons()"))

    def test_kwin_activation_is_not_named_raw_click_in_primary_path(self):
        bridge = CursorBridge()
        activated = []
        bridge._on_window_activated = lambda: activated.append("activated")
        bridge.notify_window_activated()
        self.assertEqual(activated, ["activated"])
        # The 1.1 compatibility alias must reach activation, not a raw click.
        bridge.notify_click_outside()
        self.assertEqual(activated, ["activated", "activated"])


class AtspiV14Test(unittest.TestCase):
    def test_cached_focus_is_revalidated(self):
        from src.textpik_core.atspi import AtspiSelectionBackend
        source = code_only(AtspiSelectionBackend._focused)
        self.assertIn("StateType.FOCUSED", source)
        self.assertIn("self._focused_node = None", source)

    def test_degenerate_geometry_is_not_promoted_to_high_confidence_anchor(self):
        from src.textpik_core.atspi import AtspiSelectionBackend
        source = code_only(AtspiSelectionBackend.read_selection)
        self.assertIn("geometry_valid", source)
        self.assertIn("selection_rect=rect_values if geometry_valid else None", source)

    def test_empty_atspi_result_does_not_clear_clipboard_authority(self):
        source = code_only(TextPikApp._consume_atspi_selection)
        # A real newline: the previous needle used a literal backslash-n, so the
        # assertion could never match and passed unconditionally.
        self.assertNotIn(
            "context is None or not context.text.strip():\n"
            "            self._monitor_selection_cleared()",
            source,
        )
        self.assertIn("if context.sensitive:", source)

    def test_atspi_path_records_selection_activity(self):
        # Regression for the Wayland quiet period: AT-SPI never routed through
        # _selection_event, so the timestamp stayed zeroed and the guard read
        # `monotonic() - 0.0`, which is always past the period.
        monitor = BaseSelectionMonitor()
        app = SimpleNamespace(
            monitor=monitor,
            popup=SimpleNamespace(is_interacting=lambda: False),
            atspi=SimpleNamespace(context_menu_active=lambda: False),
            settings={"popup_delay_ms": 0, "adaptive_delay_enabled": False},
            popup_state=Mock(),
            atspi_event_timer=Mock(),
            _begin_selection_session=lambda source: 1,
            _pending_atspi_node=None,
        )
        self.assertEqual(monitor._last_selection_activity_at, 0.0)
        with patch("src.textpik.is_wayland", return_value=True):
            TextPikApp._queue_atspi_selection(app, None)
        self.assertGreater(monitor._last_selection_activity_at, 0.0)
        # Activity just recorded, so the quiet period has not elapsed.
        self.assertFalse(monitor.selection_input_ready())


if __name__ == "__main__":
    unittest.main()
