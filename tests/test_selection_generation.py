"""Regression tests for selection generations and AT-SPI arbitration.

Two P0 defects made TextPik skip a placement the user had clearly asked for:

* re-selecting the same text somewhere else produced the same popup signature,
  so the duplicate guard swallowed it and the popup stayed next to the old
  cursor position;
* an AT-SPI payload that described a *different* selection reached the visible
  popup as an enrichment, so the popup kept its old anchor and old placement
  while its context silently changed.

Both are about causal identity, not about text: the same text selected again is
a new gesture, and a payload that contradicts the current selection is a new
selection.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from time import monotonic
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.textpik import SelectionContext, TextPikApp
from src.textpik_core.popup_state import PopupPhase, PopupStateMachine


class PopupGenerationTest(unittest.TestCase):
    """The duplicate guard must know which gesture the popup belongs to."""

    def test_same_signature_in_a_new_generation_is_not_duplicate(self):
        machine = PopupStateMachine()
        signature = ("hola", "Editor", "text", None)
        self.assertTrue(machine.begin(signature, generation=10))
        machine.visible()
        # The user selected the same text again: a new gesture, so the popup
        # must be allowed to re-anchor even though the signature is identical.
        self.assertTrue(machine.begin(signature, generation=11))

    def test_same_signature_in_the_same_generation_is_duplicate(self):
        machine = PopupStateMachine()
        signature = ("hola", "Editor", "text", None)
        self.assertTrue(machine.begin(signature, generation=10))
        machine.visible()
        self.assertFalse(machine.begin(signature, generation=10))

    def test_a_new_signature_is_never_duplicate(self):
        machine = PopupStateMachine()
        self.assertTrue(machine.begin(("uno", "Editor", "text", None), generation=10))
        machine.visible()
        self.assertTrue(machine.begin(("dos", "Editor", "text", None), generation=10))

    def test_generation_is_stored_and_cleared_with_the_state(self):
        machine = PopupStateMachine()
        machine.begin(("hola", "Editor", "text", None), generation=7)
        self.assertEqual(machine.generation, 7)
        machine.reset()
        self.assertIsNone(machine.generation)
        self.assertIsNone(machine.signature)
        self.assertEqual(machine.phase, PopupPhase.IDLE)

    def test_callers_without_a_generation_keep_the_old_behaviour(self):
        """A caller that passes no generation cannot claim a new gesture."""
        machine = PopupStateMachine()
        signature = ("hola", "Editor", "text", None)
        self.assertTrue(machine.begin(signature))
        machine.visible()
        self.assertFalse(machine.begin(signature))


class SameTextReselectionTest(unittest.TestCase):
    """End-to-end: the popup must be re-placed for a same-text re-selection."""

    def test_reselecting_the_same_text_repeats_the_placement(self):
        program = textwrap.dedent(
            """
            import src.textpik as textpik

            class SmokeSelectionMonitor(textpik.BaseSelectionMonitor):
                pass

            textpik.X11SelectionMonitor = SmokeSelectionMonitor
            textpik.WaylandSelectionMonitor = SmokeSelectionMonitor

            controller = textpik.TextPikApp()
            context = textpik.SelectionContext(
                text="hola",
                application="Editor",
                role="text",
            )

            first_session = controller._begin_selection_session("test")
            controller.monitor._last_text = context.text
            controller.show_popup(context=context, session_id=first_session)
            first = controller.popup.last_placement_result
            if first is None:
                raise SystemExit("el primer popup no paso por placement")

            # The user selects the very same text somewhere else. The monitor
            # reports it as a forced re-emission, so it must claim a new
            # generation and re-place the popup where the cursor is now.
            second_session = controller._begin_selection_session("test")
            controller.show_popup(context=context, session_id=second_session)
            second = controller.popup.last_placement_result

            if second is first:
                raise SystemExit(
                    "la reseleccion del mismo texto fue descartada como duplicada"
                )
            print("SAME_TEXT_REPLACED")
            controller.quit()
            """
        )
        with tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env.update(
                {
                    "HOME": home,
                    "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                    "XDG_CACHE_HOME": os.path.join(home, ".cache"),
                    "QT_QPA_PLATFORM": "offscreen",
                    "PYTHONPATH": os.pathsep.join(sys.path),
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                env=env,
                timeout=120,
            )
        self.assertEqual(
            result.returncode, 0, f"{result.stdout}\n{result.stderr}"
        )
        self.assertIn("SAME_TEXT_REPLACED", result.stdout)


class AtspiEnrichmentArbitrationTest(unittest.TestCase):
    """A contradicting AT-SPI payload is a new selection, not an enrichment."""

    def _run_consume(self, *, popup_visible, current_text, new_text,
                     current_rect=None, new_rect=None,
                     current_application="Editor", new_application="Editor"):
        enriched = []
        shown = []
        app = SimpleNamespace(
            atspi=SimpleNamespace(context_menu_active=lambda: False),
            monitor=SimpleNamespace(
                secondary_interaction_active=lambda: False,
                selection_input_ready=lambda: True,
                _last_text="",
            ),
            popup=SimpleNamespace(
                isVisible=lambda: popup_visible,
                set_context=lambda context: enriched.append(context),
            ),
            settings={"adaptive_delay_enabled": False},
            selection_context=SelectionContext(
                text=current_text,
                application=current_application,
                role="text",
                selection_rect=current_rect,
            ),
            _selection_session=20,
            _pending_atspi_node=(
                SelectionContext(
                    text=new_text,
                    application=new_application,
                    role="text",
                    selection_rect=new_rect,
                ),
                20,
                monotonic(),
            ),
            _begin_selection_session=lambda source: 21,
            show_popup=lambda **kwargs: shown.append(kwargs),
            _describes_same_selection=TextPikApp._describes_same_selection,
        )
        TextPikApp._consume_atspi_selection(app)
        return enriched, shown

    def test_a_different_selection_starts_a_new_generation(self):
        enriched, shown = self._run_consume(
            popup_visible=True, current_text="primera", new_text="segunda"
        )
        self.assertEqual(enriched, [], "no debe enriquecer el popup viejo")
        self.assertEqual(len(shown), 1, "debe crear un popup nuevo")
        self.assertEqual(shown[0]["session_id"], 21)
        self.assertEqual(shown[0]["context"].text, "segunda")

    def test_the_same_selection_still_enriches(self):
        enriched, shown = self._run_consume(
            popup_visible=True, current_text="hola", new_text="hola"
        )
        self.assertEqual(len(enriched), 1, "el mismo texto debe enriquecerse")
        self.assertEqual(shown, [])

    def test_same_text_selected_elsewhere_is_not_enrichment(self):
        enriched, shown = self._run_consume(
            popup_visible=True,
            current_text="hola",
            new_text="hola",
            current_rect=(300, 300, 40, 12),
            new_rect=(1400, 700, 40, 12),
        )
        self.assertEqual(enriched, [], "otra geometria es otra seleccion")
        self.assertEqual(len(shown), 1)

    def test_clipboard_context_without_geometry_is_enriched(self):
        """The enrichment exists because clipboard contexts lack rect/handle."""
        enriched, shown = self._run_consume(
            popup_visible=True,
            current_text="hola",
            new_text="hola",
            current_rect=None,
            new_rect=(1400, 700, 40, 12),
        )
        self.assertEqual(len(enriched), 1)
        self.assertEqual(shown, [])

    def test_a_differing_application_name_alone_still_enriches(self):
        """Sources name the same window differently, so that is not a gesture.

        Blocking on the application name would re-show the popup for the
        selection it is already presenting, every time.
        """
        enriched, shown = self._run_consume(
            popup_visible=True,
            current_text="hola",
            new_text="hola",
            current_rect=(1400, 700, 40, 12),
            new_rect=(1400, 700, 40, 12),
            current_application="Terminal",
            new_application="konsole",
        )
        self.assertEqual(len(enriched), 1)
        self.assertEqual(shown, [])

    def test_hidden_popup_always_starts_a_new_generation(self):
        enriched, shown = self._run_consume(
            popup_visible=False, current_text="primera", new_text="segunda"
        )
        self.assertEqual(enriched, [])
        self.assertEqual(len(shown), 1)


if __name__ == "__main__":
    unittest.main()
