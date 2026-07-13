import json
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from src.textpik_core.actions import fuzzy_score, migrate_action, transform_text
from src.textpik_core.anchors import AnchorResolver, hyprland_cursor_anchor, place_popup
from src.textpik_core.extensions import load_local_extensions
from src.textpik_core.atspi import AtspiSelectionBackend
from src.textpik_core.models import AnchorSource, PopupAnchor, SelectionContext
from src.textpik_core.selection import is_file_workspace_selection
from src.textpik_core.integration import action_availability
from src.textpik_core.popup_state import PopupPhase, PopupStateMachine


class ActionContractTest(unittest.TestCase):
    def test_legacy_transform_gets_typed_contract(self):
        action = migrate_action(
            {"name": "Mayúsculas", "icon": "uppercase.svg", "cmd": "uppercase"}
        )
        self.assertEqual(action["operation"], "transform")
        self.assertEqual(action["result"], "replace-selection")
        self.assertTrue(action["id"].startswith("may-sculas-"))

    def test_transform_behavior(self):
        self.assertEqual(transform_text("remove-breaks", "a\n  b"), "a b")
        self.assertEqual(transform_text("capitalize", "hola. mundo"), "Hola. Mundo")

    def test_fuzzy_action_search(self):
        self.assertIsNotNone(fuzzy_score("trgoogle", "Traducir con Google"))
        self.assertLess(
            fuzzy_score("google", "Buscar en Google"),
            fuzzy_score("google", "Traducir con Google"),
        )
        self.assertIsNone(fuzzy_score("youtube", "Guardar en Klipper"))
        self.assertIsNotNone(fuzzy_score("mayusculas", "MAYÚSCULAS"))


class AnchorTest(unittest.TestCase):
    def test_resolver_prefers_confidence(self):
        resolver = AnchorResolver()
        low = PopupAnchor(1, 2, AnchorSource.QT_POINTER, 0.2)
        high = PopupAnchor(8, 9, AnchorSource.ATSPI_SELECTION, 1.0)
        self.assertEqual(resolver.resolve([low, high]), high)

    @patch("src.textpik_core.anchors.shutil.which", return_value="/usr/bin/hyprctl")
    @patch("src.textpik_core.anchors._run_json", return_value={"x": 12.4, "y": 33.8})
    def test_hyprland_adapter(self, _run, _which):
        anchor = hyprland_cursor_anchor()
        self.assertEqual((anchor.x, anchor.y), (12, 34))

    def test_popup_avoids_selected_text(self):
        selection = (100, 100, 180, 24)
        x, y = place_popup((280, 124), (160, 40), (0, 0, 800, 600), selection, 6)
        self.assertFalse(100 < x + 160 and x < 280 and 100 < y + 40 and y < 124)


class SelectionPolicyTest(unittest.TestCase):
    def test_file_item_is_ignored_but_file_manager_text_is_allowed(self):
        file_item = SelectionContext(
            "report.pdf", application="Dolphin", role="list item"
        )
        location = SelectionContext(
            "/home/user", application="Dolphin", role="text entry"
        )
        self.assertTrue(is_file_workspace_selection(file_item, file_item.text))
        self.assertFalse(is_file_workspace_selection(location, location.text))


class IntegrationPolicyTest(unittest.TestCase):
    @patch("src.textpik_core.integration.which", return_value=None)
    def test_paste_degrades_to_clipboard_without_injection_tool(self, _which):
        status = action_availability(
            "paste", wayland=True, kde=False, dbus_services=set()
        )
        self.assertTrue(status.available)
        self.assertTrue(status.degraded)

    @patch("src.textpik_core.integration.which", return_value=None)
    def test_print_reports_missing_cups(self, _which):
        status = action_availability(
            "print", wayland=False, kde=False, dbus_services=set()
        )
        self.assertFalse(status.available)
        self.assertIn("CUPS", status.label)


class ExtensionTest(unittest.TestCase):
    def test_loads_only_versioned_valid_local_manifests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "sample"
            folder.mkdir()
            (folder / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "action": {
                            "name": "Local",
                            "icon": "copy.svg",
                            "cmd": "copy",
                            "permissions": ["clipboard"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            actions = load_local_extensions(root)
            self.assertEqual(actions[0]["extension"], "sample")


class AtspiTest(unittest.TestCase):
    def test_replaces_selection_through_editable_interface(self):
        calls = []

        class Editable:
            def delete_text(self, start, end):
                calls.append(("delete", start, end))

            def insert_text(self, start, text, length):
                calls.append(("insert", start, text, length))

        class Node:
            def get_editable_text_iface(self):
                return Editable()

        backend = AtspiSelectionBackend(atspi=object())
        context = SelectionContext(
            text="old",
            editable=True,
            backend="atspi",
            selection_start=2,
            selection_end=5,
            native_handle=Node(),
        )
        self.assertTrue(backend.replace_selection(context, "new"))
        self.assertEqual(
            calls,
            [("delete", 2, 5), ("insert", 2, "new", 3)],
        )

    def test_selection_event_subscription_forwards_source(self):
        listeners = []

        class Listener:
            def __init__(self, callback):
                self.callback = callback
                self.registered = []

            def register(self, event):
                self.registered.append(event)

            def deregister(self, event):
                self.registered.remove(event)

        class EventListener:
            @staticmethod
            def new(callback, _data):
                listener = Listener(callback)
                listeners.append(listener)
                return listener

        class Atspi:
            pass

        Atspi.EventListener = EventListener

        backend = AtspiSelectionBackend(atspi=Atspi())
        sources = []
        self.assertTrue(backend.subscribe_selection_changes(sources.append))
        selection_listener = listeners[-1]
        source = object()
        selection_listener.callback(type("Event", (), {"source": source})())
        self.assertEqual(sources, [source])
        backend.close()

    def test_protected_state_is_sensitive_before_reading_text(self):
        protected = object()

        class StateType:
            pass

        StateType.PROTECTED = protected

        class Atspi:
            pass

        Atspi.StateType = StateType

        class States:
            def contains(self, state):
                return state is protected

        class Node:
            def get_state_set(self):
                return States()

        backend = AtspiSelectionBackend(atspi=Atspi())
        self.assertTrue(backend._is_protected(Node(), "entry"))


class PopupStateTest(unittest.TestCase):
    def test_state_machine_supports_qt_weak_references(self):
        state = PopupStateMachine()
        self.assertIs(weakref.ref(state)(), state)

    def test_popup_lifecycle_and_duplicate_guard(self):
        state = PopupStateMachine()
        signature = ("text", "app")
        self.assertTrue(state.begin(signature))
        self.assertEqual(state.phase, PopupPhase.STABILIZING)
        state.visible()
        self.assertFalse(state.begin(signature))
        state.reset()
        self.assertTrue(state.begin(signature))

    def test_suppression_records_reason(self):
        state = PopupStateMachine()
        state.suppress("sensitive")
        self.assertEqual(state.phase, PopupPhase.SUPPRESSED)
        self.assertEqual(state.reason, "sensitive")


if __name__ == "__main__":
    unittest.main()
