import json
import inspect
import tempfile
import unittest
import weakref
from pathlib import Path
from time import perf_counter_ns
from unittest.mock import patch

from src.textpik_core.actions import (
    PermissionStore,
    fuzzy_score,
    migrate_action,
    transform_text,
)
from src.textpik_core.anchors import (
    AnchorResolver,
    hyprland_cursor_anchor,
    place_popup,
    sway_cursor_anchor,
    stabilize_popup_position,
)
from src.textpik_core.extensions import inspect_local_extensions, load_local_extensions
from src.textpik_core.atspi import AtspiSelectionBackend
from src.textpik_core.models import AnchorSource, PopupAnchor, SelectionContext
from src.textpik_core.selection import (
    evaluate_selection_intent,
    is_file_workspace_selection,
)
from src.textpik_core.integration import action_availability
from src.textpik_core.popup_state import PopupPhase, PopupStateMachine
from src.textpik_core.performance import PerformanceTracker
from src.textpik_core.execution import executable_name, is_terminal_execution
from src.textpik_core.platform import (
    command_exists,
    detect_desktop_environment,
    find_available_terminal,
    is_kde_desktop,
    is_wayland_session,
)
from src.textpik_core.planning import ContextSnapshot, plan_actions
from src.textpik_core.profiles import normalize_profiles, resolve_profile
from src.textpik_core.settings import (
    DEFAULT_SETTINGS as CORE_DEFAULT_SETTINGS,
    normalize_settings as normalize_core_settings,
)
from src.textpik_core.storage import read_json, write_json_atomic
from src.textpik_core.spelling import SpellingService
from src.textpik_core.text import build_command_argv, classify_text, normalize_url


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


class TextContractTest(unittest.TestCase):
    def test_classification_is_immutable_and_desktop_independent(self):
        kinds = classify_text("person@example.com")
        self.assertIsInstance(kinds, frozenset)
        self.assertEqual(kinds, frozenset({"text", "email"}))
        self.assertEqual(normalize_url("example.com/a"), "https://example.com/a")

    def test_command_contract_preserves_argument_boundaries(self):
        self.assertEqual(
            build_command_argv("tool --query {url} --text '{}'", "a b&c"),
            ["tool", "--query", "a+b%26c", "--text", "a b&c"],
        )


class ActionPlanningTest(unittest.TestCase):
    def test_snapshot_does_not_retain_selected_text(self):
        context = SelectionContext(
            "private text",
            application="Editor",
            role="text",
            editable=True,
        )
        snapshot = ContextSnapshot.from_selection(
            context,
            text_types={"text"},
            clipboard_has_text=True,
        )
        self.assertFalse(hasattr(snapshot, "text"))
        self.assertEqual(snapshot.application, "Editor")
        self.assertTrue(snapshot.editable)

    def test_planner_preserves_order_and_filters_context(self):
        actions = [
            {"name": "Disabled", "cmd": "disabled", "enabled": False},
            {"name": "Copy", "cmd": "copy", "context": ["text"]},
            {"name": "Paste", "cmd": "paste"},
            {"name": "Code", "cmd": "code", "context": ["code"]},
            {"name": "Unavailable", "cmd": "offline"},
        ]
        snapshot = ContextSnapshot(text_types=frozenset({"text"}))
        planned = plan_actions(
            actions,
            snapshot,
            is_available=lambda action: action["cmd"] != "offline",
        )
        self.assertEqual([action["name"] for action in planned], ["Copy"])

    def test_profile_filter_preserves_global_action_order(self):
        actions = [
            {"id": "copy", "name": "Copy", "cmd": "copy"},
            {"id": "search", "name": "Search", "cmd": "search"},
            {"id": "count", "name": "Count", "cmd": "count"},
        ]
        planned = plan_actions(
            actions,
            ContextSnapshot(clipboard_has_text=True),
            allowed_action_ids=frozenset({"count", "copy"}),
        )
        self.assertEqual([action["id"] for action in planned], ["copy", "count"])


class ContextProfileTest(unittest.TestCase):
    def test_normalization_discards_empty_and_bounds_profiles(self):
        profiles = normalize_profiles(
            [
                {"name": "", "application": "Firefox", "action_ids": ["copy"]},
                {
                    "name": "Web",
                    "application": " Firefox ",
                    "text_types": ["url", "url"],
                    "action_ids": ["copy", "search", "copy"],
                },
            ]
        )
        self.assertEqual(
            profiles,
            [
                {
                    "name": "Web",
                    "application": "Firefox",
                    "text_types": ["url"],
                    "action_ids": ["copy", "search"],
                }
            ],
        )

    def test_first_matching_profile_has_explicit_priority(self):
        profiles = [
            {
                "name": "Firefox URLs",
                "application": "firefox",
                "text_types": ["url"],
                "action_ids": ["open"],
            },
            {
                "name": "All URLs",
                "application": "",
                "text_types": ["url"],
                "action_ids": ["copy"],
            },
        ]
        snapshot = ContextSnapshot(
            application="org.mozilla.Firefox", text_types=frozenset({"text", "url"})
        )
        profile = resolve_profile(profiles, snapshot)
        self.assertEqual(profile.name, "Firefox URLs")
        self.assertEqual(profile.action_ids, frozenset({"open"}))

    def test_profile_never_retains_selected_text(self):
        profile = resolve_profile(
            [
                {
                    "name": "Editors",
                    "application": "code",
                    "text_types": [],
                    "action_ids": ["copy"],
                }
            ],
            ContextSnapshot(application="Code"),
        )
        self.assertFalse(hasattr(profile, "text"))


class PerformanceContractTest(unittest.TestCase):
    def test_tracker_keeps_aggregates_and_reports_budget_regressions(self):
        tracker = PerformanceTracker({"classification": 5.0})
        tracker.record_ns("classification", 2_000_000)
        tracker.record_ns("classification", 7_000_000)
        metric = tracker.snapshots()[0]
        self.assertEqual(metric.count, 2)
        self.assertEqual(metric.average_ms, 4.5)
        self.assertEqual(metric.maximum_ms, 7.0)
        self.assertEqual(metric.budget_exceeded, 1)

    def test_tracker_has_a_bounded_metric_cardinality(self):
        tracker = PerformanceTracker()
        for index in range(100):
            tracker.record_ns(f"metric-{index}", index)
        self.assertEqual(len(tracker.snapshots()), 16)

    def test_core_operations_stay_inside_hot_path_budgets(self):
        actions = [
            {"name": f"Action {index}", "cmd": f"action-{index}", "context": ["text"]}
            for index in range(40)
        ]
        snapshot = ContextSnapshot(text_types=frozenset({"text"}))
        iterations = 2_000

        started = perf_counter_ns()
        for _ in range(iterations):
            classify_text("def hello():\n    return 1")
        classification_average = (perf_counter_ns() - started) / iterations

        started = perf_counter_ns()
        for _ in range(iterations):
            plan_actions(actions, snapshot)
        planning_average = (perf_counter_ns() - started) / iterations

        self.assertLess(classification_average, 5_000_000)
        self.assertLess(planning_average, 5_000_000)

    def test_hot_path_core_has_no_qt_dependency(self):
        modules = (
            __import__("src.textpik_core.text", fromlist=["*"]),
            __import__("src.textpik_core.planning", fromlist=["*"]),
            __import__("src.textpik_core.performance", fromlist=["*"]),
            __import__("src.textpik_core.platform", fromlist=["*"]),
            __import__("src.textpik_core.execution", fromlist=["*"]),
            __import__("src.textpik_core.settings", fromlist=["*"]),
            __import__("src.textpik_core.storage", fromlist=["*"]),
        )
        for module in modules:
            self.assertNotIn("PySide6", inspect.getsource(module))


class PlatformContractTest(unittest.TestCase):
    def test_session_and_desktop_detection_use_explicit_environment(self):
        environment = {
            "XDG_SESSION_TYPE": "Wayland",
            "XDG_CURRENT_DESKTOP": "GNOME:KDE",
            "XDG_SESSION_DESKTOP": "plasma",
        }
        desktop = detect_desktop_environment(environment)
        self.assertTrue(is_wayland_session(environment))
        self.assertEqual(desktop, "gnome:kde:plasma")
        self.assertTrue(is_kde_desktop(desktop))

    def test_terminal_detection_is_ordered_and_injectable(self):
        checked = []

        def available(command):
            checked.append(command)
            return command in {"kgx", "xterm"}

        self.assertEqual(find_available_terminal(available=available), "kgx")
        self.assertEqual(checked, ["konsole", "gnome-terminal", "kgx"])
        self.assertTrue(command_exists("tool", which=lambda _name: "/usr/bin/tool"))
        self.assertFalse(command_exists("tool", which=lambda _name: None))


class ExecutionPolicyTest(unittest.TestCase):
    def test_terminal_confirmation_handles_paths_and_invalid_commands(self):
        self.assertEqual(executable_name("/usr/bin/kitty --hold"), "kitty")
        self.assertTrue(is_terminal_execution("/usr/bin/kitty --hold"))
        self.assertFalse(is_terminal_execution("xdg-open https://example.com"))
        self.assertFalse(is_terminal_execution("'unterminated"))


class SettingsContractTest(unittest.TestCase):
    def test_legacy_ui_defaults_migrate_without_overwriting_custom_values(self):
        migrated = normalize_core_settings(
            {
                "ui_version": 2,
                "popup_icon_size": 18,
                "popup_spacing": 1,
                "popup_background_color": "#123456",
            }
        )
        self.assertEqual(migrated["ui_version"], 3)
        self.assertEqual(migrated["popup_icon_size"], 17)
        self.assertEqual(migrated["popup_spacing"], 2)
        self.assertEqual(migrated["popup_background_color"], "#123456")

    def test_settings_schema_drops_unknown_keys_and_bounds_values(self):
        normalized = normalize_core_settings(
            {
                "unknown": "discard me",
                "max_popup_actions": 1000,
                "popup_opacity": 0,
                "blocked_apps": [" Firefox ", ""],
            }
        )
        self.assertNotIn("unknown", normalized)
        self.assertEqual(normalized["max_popup_actions"], 40)
        self.assertEqual(normalized["popup_opacity"], 0.25)
        self.assertEqual(normalized["blocked_apps"], ["firefox"])
        self.assertEqual(set(normalized), set(CORE_DEFAULT_SETTINGS))

    def test_adaptive_popup_settings_are_bounded(self):
        normalized = normalize_core_settings(
            {
                "adaptive_popup": "yes",
                "popup_min_confidence": 200,
                "popup_full_confidence": 1,
                "popup_compact_actions": 99,
            }
        )
        self.assertTrue(normalized["adaptive_popup"])
        self.assertFalse(normalized["spelling_action_migrated"])
        self.assertEqual(normalized["popup_min_confidence"], 90)
        self.assertEqual(normalized["popup_full_confidence"], 50)
        self.assertEqual(normalized["popup_compact_actions"], 8)

    def test_color_validation_stays_an_injected_ui_boundary(self):
        calls = []

        def normalize_color(value, fallback):
            calls.append((value, fallback))
            return str(value).lower()

        normalized = normalize_core_settings(
            {"popup_background_color": "#ABCDEF"},
            color_normalizer=normalize_color,
        )
        self.assertEqual(normalized["popup_background_color"], "#abcdef")
        self.assertEqual(len(calls), 5)


class StorageContractTest(unittest.TestCase):
    def test_atomic_json_round_trip_is_private_and_unicode_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            payload = {"saludo": "acción rápida", "enabled": True}
            write_json_atomic(path, payload)
            self.assertEqual(read_json(path), payload)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_serialization_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "actions.json"
            write_json_atomic(path, {"stable": True})
            with self.assertRaises(TypeError):
                write_json_atomic(path, {"invalid": object()})
            self.assertEqual(read_json(path), {"stable": True})
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_permission_store_uses_durable_shared_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "permissions.json"
            store = PermissionStore(path)
            store.grant("translate", "network")
            reloaded = PermissionStore(path)
            self.assertTrue(reloaded.allows("translate", "network"))


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

    @patch("src.textpik_core.anchors.shutil.which", return_value="/usr/bin/swaymsg")
    @patch(
        "src.textpik_core.anchors._run_json",
        return_value=[{"cursor": {"x": 44.6, "y": 70.2}}],
    )
    def test_sway_adapter(self, _run, _which):
        anchor = sway_cursor_anchor()
        self.assertEqual((anchor.x, anchor.y), (45, 70))

    def test_popup_avoids_selected_text(self):
        selection = (100, 100, 180, 24)
        x, y = place_popup((280, 124), (160, 40), (0, 0, 800, 600), selection, 6)
        self.assertFalse(100 < x + 160 and x < 280 and 100 < y + 40 and y < 124)

    def test_popup_stays_on_screen_near_bottom_right_edge(self):
        x, y = place_popup((795, 595), (160, 40), (0, 0, 800, 600), gap=6)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + 160, 800)
        self.assertLessEqual(y + 40, 600)

    def test_popup_position_ignores_tiny_anchor_jitter(self):
        position = stabilize_popup_position(
            (204, 106),
            (200, 100),
            (160, 40),
            threshold=14,
        )
        self.assertEqual(position, (200, 100))

    def test_popup_position_moves_if_previous_would_cover_selection(self):
        position = stabilize_popup_position(
            (214, 100),
            (200, 100),
            (160, 40),
            avoid_rect=(220, 100, 100, 30),
            threshold=14,
        )
        self.assertEqual(position, (214, 100))


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

    def test_intent_engine_rejects_controls_and_textpik_itself(self):
        control = SelectionContext("Copiar", application="Firefox", role="menu item")
        own_ui = SelectionContext("Más acciones", application="TextPik", role="text")
        self.assertEqual(
            evaluate_selection_intent(control, control.text).reason,
            "non-text-control",
        )
        self.assertEqual(
            evaluate_selection_intent(own_ui, own_ui.text).reason,
            "self",
        )

    def test_intent_engine_allows_real_file_manager_text(self):
        context = SelectionContext(
            "/home/user", application="Nautilus", role="text entry"
        )
        self.assertTrue(evaluate_selection_intent(context, context.text).allowed)

    def test_intent_confidence_rewards_accessible_text_context(self):
        bare = evaluate_selection_intent(SelectionContext("hola"), "hola")
        enriched_context = SelectionContext(
            "hola",
            application="Editor",
            role="text entry",
            editable=True,
            selection_rect=(10, 10, 40, 18),
            anchor=PopupAnchor(50, 28, AnchorSource.ATSPI_SELECTION, 1.0),
            backend="atspi",
        )
        enriched = evaluate_selection_intent(enriched_context, "hola")
        self.assertGreater(enriched.confidence, bare.confidence)
        self.assertEqual(enriched.confidence, 1.0)

    def test_rejected_intent_has_zero_confidence(self):
        context = SelectionContext("clave", role="menu item")
        intent = evaluate_selection_intent(context, context.text)
        self.assertFalse(intent.allowed)
        self.assertEqual(intent.confidence, 0.0)


class SpellingServiceTest(unittest.TestCase):
    class FakeDictionary:
        def check(self, word):
            return word == "correcto"

        def suggest(self, _word):
            return ["acción", "acción", "acorde", "actor", "extra"]

    def test_provider_is_lazy_cached_and_bounded(self):
        calls = []

        def factory(language):
            calls.append(language)
            return self.FakeDictionary()

        service = SpellingService(factory, max_suggestions=3)
        result = service.suggest("acsion", ["es_CL"])
        self.assertTrue(result.misspelled)
        self.assertEqual(result.suggestions, ("acción", "acorde", "actor"))
        service.suggest("correcto", ["es_CL"])
        self.assertEqual(calls, ["es_CL"])

    def test_provider_rejects_non_words_without_loading_dictionary(self):
        calls = []
        service = SpellingService(lambda language: calls.append(language))
        for value in ("a", "example.com", "1234", "two words"):
            self.assertIsNone(service.suggest(value, ["es_CL"]))
        self.assertEqual(calls, [])

    def test_provider_remembers_unavailable_dictionary(self):
        calls = []

        def unavailable(language):
            calls.append(language)
            raise ImportError

        service = SpellingService(unavailable)
        self.assertIsNone(service.suggest("acsion", ["es_CL"]))
        self.assertIsNone(service.suggest("acsion", ["es_CL"]))
        self.assertEqual(calls, ["es_CL"])


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

    def test_inspection_reports_rejected_permissions_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifests = [
                (
                    "unsafe",
                    {
                        "schema_version": 1,
                        "action": {
                            "id": "same",
                            "name": "Unsafe",
                            "icon": "copy.svg",
                            "cmd": "external-tool",
                            "permissions": [],
                        },
                    },
                ),
                (
                    "valid",
                    {
                        "schema_version": 1,
                        "action": {
                            "id": "same",
                            "name": "Valid",
                            "icon": "copy.svg",
                            "cmd": "external-tool",
                            "permissions": ["process"],
                        },
                    },
                ),
                (
                    "duplicate",
                    {
                        "schema_version": 1,
                        "action": {
                            "id": "same",
                            "name": "Duplicate",
                            "icon": "copy.svg",
                            "cmd": "copy",
                            "permissions": [],
                        },
                    },
                ),
            ]
            for name, payload in manifests:
                folder = root / name
                folder.mkdir()
                (folder / "manifest.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            actions, issues = inspect_local_extensions(root)
            self.assertEqual([action["extension"] for action in actions], ["duplicate"])
            reasons = {issue.reason for issue in issues}
            self.assertIn("missing-process-permission", reasons)
            self.assertIn("duplicate-action-id", reasons)


class AtspiTest(unittest.TestCase):
    def test_reads_typed_selection_context(self):
        class Rect:
            x = 10
            y = 20
            width = 80
            height = 18

        class Text:
            def get_selection(self, _index):
                return 2, 7

            def get_range_extents(self, _start, _end, _coord):
                return Rect()

            def get_text(self, start, end):
                return "hello" if (start, end) == (2, 7) else ""

        class Node:
            def get_text_iface(self):
                return Text()

        class CoordType:
            SCREEN = object()

        class Atspi:
            pass

        Atspi.CoordType = CoordType
        backend = AtspiSelectionBackend(atspi=Atspi())
        node = Node()
        with (
            patch.object(backend, "_focused", return_value=node),
            patch.object(backend, "_role_name", return_value="text entry"),
            patch.object(backend, "_application_name", return_value="Editor"),
            patch.object(backend, "_is_protected", return_value=False),
            patch.object(backend, "_editable", return_value=object()),
        ):
            context = backend.read_selection(node)
        self.assertEqual(context.text, "hello")
        self.assertEqual(context.selection_rect, (10, 20, 80, 18))
        self.assertEqual((context.anchor.x, context.anchor.y), (90, 38))
        self.assertTrue(context.editable)

    def test_never_reads_protected_text_contents(self):
        class Rect:
            x = y = width = height = 1

        class Text:
            def get_selection(self, _index):
                return 0, 4

            def get_range_extents(self, _start, _end, _coord):
                return Rect()

            def get_text(self, _start, _end):
                raise AssertionError("protected text must not be read")

        class Node:
            def get_text_iface(self):
                return Text()

        class CoordType:
            SCREEN = object()

        class Atspi:
            pass

        Atspi.CoordType = CoordType
        backend = AtspiSelectionBackend(atspi=Atspi())
        node = Node()
        with (
            patch.object(backend, "_focused", return_value=node),
            patch.object(backend, "_role_name", return_value="password text"),
            patch.object(backend, "_application_name", return_value="Login"),
            patch.object(backend, "_is_protected", return_value=True),
        ):
            context = backend.read_selection(node)
        self.assertTrue(context.sensitive)
        self.assertEqual(context.text, "")

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
