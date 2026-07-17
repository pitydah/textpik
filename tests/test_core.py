import inspect
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from src.textpik import (
    ActionPalette,
    AutomationEditDialog,
    APP_VERSION,
    BaseSelectionMonitor,
    DEFAULT_ACTIONS,
    DEFAULT_SETTINGS,
    InformationPopup,
    PopupWindow,
    SettingsDialog,
    TextPikApp,
    X11Pointer,
    FunctionWorker,
    build_command_argv,
    clipboard_has_text,
    classify_text,
    desktop_environment,
    is_kde,
    load_settings,
    main,
    normalize_settings,
    normalize_url,
    validate_actions,
)
class CoreHelpersTest(unittest.TestCase):
    def test_version_and_runtime_self_check_do_not_start_gui(self):
        with patch("builtins.print") as output:
            self.assertEqual(main(["textpik", "--version"]), 0)
            self.assertIn(APP_VERSION, output.call_args.args[0])
        with patch("builtins.print") as output:
            self.assertEqual(main(["textpik", "--self-check"]), 0)
            payload = json.loads(output.call_args.args[0])
            self.assertTrue(payload["actions"])
            self.assertTrue(payload["application_icon"])
            self.assertNotIn("qt_platform", payload)

    def test_unchanged_settings_are_not_rewritten_on_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            config_dir = Path(temp)
            settings_file = config_dir / "settings.json"
            settings_file.write_text(
                json.dumps(DEFAULT_SETTINGS, ensure_ascii=False), encoding="utf-8"
            )
            with (
                patch("src.textpik.CONFIG_DIR", config_dir),
                patch("src.textpik.SETTINGS_FILE", settings_file),
                patch("src.textpik.write_json_atomic") as writer,
            ):
                loaded = load_settings()
            self.assertEqual(loaded, DEFAULT_SETTINGS)
            writer.assert_not_called()

    def test_headless_clipboard_without_mime_data_is_empty(self):
        clipboard = SimpleNamespace(mimeData=lambda: None)
        self.assertFalse(clipboard_has_text(clipboard))

    def test_popup_hot_path_avoids_desktop_subprocess_probes(self):
        source = inspect.getsource(TextPikApp.show_popup)
        self.assertNotIn("hyprland_cursor_anchor(", source)
        self.assertNotIn("sway_cursor_anchor(", source)
        self.assertNotIn("get_cursor_pos(", source)
        self.assertNotIn("is_foreground_process_game(", source)
        self.assertNotIn("order_actions_for_popup", source)
        self.assertNotIn("ranker.suggest", source)

    def test_boolean_strings_are_normalized(self):
        settings = normalize_settings({"sticky_popup": "false", "context_aware": "yes"})
        self.assertFalse(settings["sticky_popup"])
        self.assertTrue(settings["context_aware"])

    def test_popup_limit_is_clamped(self):
        self.assertEqual(
            normalize_settings({"max_popup_actions": 1})["max_popup_actions"], 8
        )
        self.assertEqual(
            normalize_settings({"max_popup_actions": 99})["max_popup_actions"], 40
        )

    def test_url_detection_accepts_bare_domains(self):
        self.assertEqual(normalize_url("example.com/path"), "https://example.com/path")
        self.assertIn("url", classify_text("example.com/path"))

    def test_url_detection_rejects_regular_text(self):
        self.assertEqual(normalize_url("hello world"), "")
        self.assertNotIn("url", classify_text("hello world"))

    def test_url_detection_does_not_treat_email_or_decimal_as_url(self):
        self.assertEqual(normalize_url("person@example.com"), "")
        self.assertEqual(normalize_url("1.2"), "")
        self.assertNotIn("url", classify_text("person@example.com"))

    def test_worker_is_not_auto_deleted_in_its_thread(self):
        worker = FunctionWorker(lambda: "ok")
        self.assertFalse(worker.autoDelete())

    def test_diagnostic_report_does_not_include_selected_text(self):
        controller = SimpleNamespace(
            app=SimpleNamespace(platformName=lambda: "wayland"),
            monitor=BaseSelectionMonitor(),
            atspi=SimpleNamespace(available=True),
            atspi_events_active=True,
            _desktop_dbus_services=lambda: {"org.kde.klipper"},
            _selection_session=7,
            popup_state=SimpleNamespace(
                phase=SimpleNamespace(value="visible"),
                reason="",
            ),
        )
        controller.monitor._last_text = "private selected text"
        with (
            patch("src.textpik.desktop_environment", return_value="kde"),
            patch("src.textpik.check_command", return_value=False),
        ):
            report = TextPikApp.diagnostic_report(controller)
        self.assertNotIn("private selected text", report)
        self.assertIn('"selection_session": 7', report)

    def test_context_classification(self):
        self.assertIn("word", classify_text("precisión"))
        self.assertNotIn("word", classify_text("dos palabras"))
        self.assertIn("email", classify_text("person@example.com"))
        self.assertIn("ip", classify_text("192.168.1.20"))
        self.assertNotIn("ip", classify_text("999.1.1.1"))
        self.assertIn("code", classify_text("def hello():\n    return 1"))

    def test_command_substitution_keeps_argument_boundaries(self):
        argv = build_command_argv("tool --query {url} --text '{}'", "a b&c")
        self.assertEqual(argv, ["tool", "--query", "a+b%26c", "--text", "a b&c"])

    def test_old_search_context_is_migrated(self):
        actions = validate_actions(
            [
                {
                    "name": "Buscar",
                    "icon": "search.svg",
                    "cmd": "xdg-open 'https://www.google.com/search?q={url}'",
                    "context": ["url"],
                }
            ]
        )
        self.assertEqual(actions[0]["context"], ["text"])

    def test_desktop_detection_distinguishes_kde_and_gnome(self):
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}, clear=True):
            self.assertTrue(is_kde())
            self.assertEqual(desktop_environment(), "kde")
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=True):
            self.assertFalse(is_kde())
            self.assertEqual(desktop_environment(), "gnome")


class SelectionStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_oversized_selection_clears_previous_state(self):
        class Monitor(BaseSelectionMonitor):
            text = ""

            def _read_selection_text(self):
                return self.text

        monitor = Monitor({"max_selection_length": 3, "popup_delay_ms": 0})
        monitor._last_text = "old"
        monitor.text = "too long"
        cleared = []
        monitor.selection_cleared.connect(lambda: cleared.append(True))
        monitor._debounce_expired()
        self.assertEqual(monitor.get_last_text(), "")
        self.assertEqual(cleared, [True])

    def test_secondary_click_does_not_schedule_popup(self):
        class Monitor(BaseSelectionMonitor):
            pass

        monitor = Monitor()
        with patch.object(monitor, "_secondary_button_pressed", return_value=True):
            monitor._selection_event()
        self.assertFalse(monitor.timer_debounce.isActive())

    def test_selection_clear_does_not_preempt_popup_lifetime(self):
        controller = SimpleNamespace(
            _begin_selection_session=Mock(),
            popup=SimpleNamespace(
                isVisible=lambda: True,
                is_interacting=lambda: False,
                pointer_inside=lambda: False,
            ),
            pointer=SimpleNamespace(state=lambda: None),
            _selection_released=True,
            _last_popup_at=time.monotonic(),
            hide_popup=Mock(),
        )
        TextPikApp._monitor_selection_cleared(controller)
        controller.hide_popup.assert_not_called()

    def test_selection_clear_with_primary_press_is_an_external_click(self):
        controller = SimpleNamespace(
            _begin_selection_session=Mock(),
            popup=SimpleNamespace(
                isVisible=lambda: True,
                is_interacting=lambda: False,
                pointer_inside=lambda: False,
            ),
            pointer=SimpleNamespace(
                state=lambda: (100, 100, X11Pointer.PRIMARY_MASK)
            ),
            _selection_released=True,
            _last_popup_at=time.monotonic(),
            hide_popup=Mock(),
        )
        TextPikApp._monitor_selection_cleared(controller)
        controller.hide_popup.assert_called_once_with(invalidate_session=False)

    def test_stable_empty_selection_is_same_window_external_click_fallback(self):
        controller = SimpleNamespace(
            _begin_selection_session=Mock(),
            popup=SimpleNamespace(
                isVisible=lambda: True,
                is_interacting=lambda: False,
                pointer_inside=lambda: False,
            ),
            pointer=SimpleNamespace(state=lambda: None),
            _selection_released=True,
            _last_popup_at=time.monotonic() - 1,
            hide_popup=Mock(),
        )
        TextPikApp._monitor_selection_cleared(controller)
        controller.hide_popup.assert_called_once_with(invalidate_session=False)

    def test_primary_click_outside_beats_initial_popup_immunity(self):
        popup = SimpleNamespace(
            isVisible=lambda: True,
            is_interacting=lambda: False,
            mapFromGlobal=lambda _point: object(),
            rect=lambda: SimpleNamespace(contains=lambda _point: False),
        )
        controller = SimpleNamespace(
            popup=popup,
            pointer=SimpleNamespace(
                state=lambda: (100, 100, X11Pointer.PRIMARY_MASK)
            ),
            monitor=SimpleNamespace(suppress_secondary_interaction=Mock()),
            hide_popup=Mock(),
            hide_check_timer=Mock(),
            _popup_immunity_until=float("inf"),
            _selection_released=True,
        )
        TextPikApp.hide_popup_on_external_click(controller)
        controller.hide_popup.assert_called_once()

    def test_hover_does_not_extend_eight_second_lifetime(self):
        controller = SimpleNamespace(
            popup=SimpleNamespace(
                isVisible=lambda: True,
                is_interacting=lambda: False,
                pointer_inside=lambda: True,
            ),
            auto_hide_timer=Mock(),
            hide_popup=Mock(),
        )
        TextPikApp._auto_hide_popup(controller)
        controller.hide_popup.assert_called_once()
        controller.auto_hide_timer.start.assert_not_called()

    def test_wayland_followup_selection_fragments_are_coalesced(self):
        monitor = BaseSelectionMonitor(dict(DEFAULT_SETTINGS))
        monitor._last_emit_at = time.monotonic()
        with patch("src.textpik.is_wayland", return_value=True):
            monitor._schedule_read()
        self.assertGreaterEqual(monitor.timer_debounce.interval(), 180)

    def test_wayland_initial_selection_waits_for_a_stable_drag_edge(self):
        monitor = BaseSelectionMonitor(dict(DEFAULT_SETTINGS))
        with patch("src.textpik.is_wayland", return_value=True):
            monitor._schedule_read()
        self.assertGreaterEqual(monitor.timer_debounce.interval(), 150)

    def test_kwin_external_activation_beats_popup_immunity(self):
        popup = SimpleNamespace(
            isVisible=lambda: True,
            is_interacting=lambda: False,
            pointer_inside=lambda: False,
        )
        controller = SimpleNamespace(
            popup=popup,
            _popup_immunity_until=float("inf"),
            hide_popup=Mock(),
        )
        TextPikApp._on_kwin_window_activated(controller)
        controller.hide_popup.assert_called_once()

    def test_secondary_click_guard_survives_button_release(self):
        monitor = BaseSelectionMonitor()
        with patch.object(monitor, "_secondary_button_pressed", return_value=True):
            self.assertTrue(monitor.secondary_interaction_active())
        with patch.object(monitor, "_secondary_button_pressed", return_value=False):
            self.assertTrue(monitor.secondary_interaction_active())
            monitor._secondary_guard_until = 0.0
            self.assertFalse(monitor.secondary_interaction_active())

    def test_secondary_click_closes_popup_even_during_immunity(self):
        controller = SimpleNamespace(
            popup=SimpleNamespace(isVisible=lambda: True),
            pointer=SimpleNamespace(
                state=lambda: (100, 100, X11Pointer.SECONDARY_MASK)
            ),
            monitor=SimpleNamespace(suppress_secondary_interaction=Mock()),
            hide_popup=Mock(),
            hide_check_timer=Mock(),
            _popup_immunity_until=float("inf"),
        )
        TextPikApp.hide_popup_on_external_click(controller)
        controller.monitor.suppress_secondary_interaction.assert_called_once()
        controller.hide_popup.assert_called_once()

    def test_base_selection_backend_is_explicitly_abstract(self):
        with self.assertRaises(NotImplementedError):
            BaseSelectionMonitor()._read_selection_text()

    def test_selection_waits_until_primary_button_is_released(self):
        class Monitor(BaseSelectionMonitor):
            reads = 0

            def _read_selection_text(self):
                self.reads += 1
                return "selected"

        monitor = Monitor()
        with patch.object(monitor, "_primary_button_pressed", return_value=True):
            monitor._debounce_expired()
        self.assertEqual(monitor.reads, 0)
        self.assertTrue(monitor.timer_debounce.isActive())

    def test_stale_selection_result_is_discarded(self):
        class Monitor(BaseSelectionMonitor):
            pass

        monitor = Monitor()
        old_revision = monitor._next_revision()
        monitor._next_revision()
        changed = []
        monitor.selection_changed.connect(lambda: changed.append(True))
        self.assertFalse(monitor._accept_selection_text("old", old_revision))
        self.assertEqual(monitor.get_last_text(), "")
        self.assertEqual(changed, [])

    def test_paste_keeps_existing_clipboard_contents(self):
        clipboard = self.app.clipboard()
        clipboard.setText("clipboard value")
        controller = SimpleNamespace(_show_toast=lambda _message: None)
        loop = QEventLoop()
        with (
            patch("src.textpik.is_qt_wayland", return_value=False),
            patch("src.textpik.check_command", side_effect=lambda name: name == "xdotool"),
            patch("src.textpik.subprocess.Popen") as popen,
        ):
            TextPikApp.paste_clipboard(controller)
            QTimer.singleShot(150, loop.quit)
            loop.exec()
        self.assertEqual(clipboard.text(), "clipboard value")
        popen.assert_called_once_with(["xdotool", "key", "ctrl+v"])


class PopupCompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_more_actions_surface_is_visibly_opaque(self):
        palette = ActionPalette()
        palette.resize(300, 240)
        palette.apply_theme(
            {
                "popup_background_color": "#202124",
                "popup_border_color": "#45474c",
            }
        )
        palette.show()
        self.app.processEvents()
        image = palette.grab().toImage()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        palette.hide()
        self.assertEqual(center.alpha(), 255)
        self.assertGreater(center.lightness(), 0)

    def test_information_result_uses_an_independent_popup(self):
        toolbar = PopupWindow(DEFAULT_ACTIONS[:8], None, dict(DEFAULT_SETTINGS))
        toolbar.resize(240, 33)
        toolbar.move(100, 100)
        toolbar.hide()
        toolbar.show_inline_result(
            "Estadísticas del texto",
            "12 palabras · 80 caracteres",
            "2 oraciones · menos de 1 min de lectura",
        )
        self.app.processEvents()
        result = toolbar.result_popup
        self.assertIsInstance(result, InformationPopup)
        self.assertTrue(result.isVisible())
        self.assertFalse(toolbar.isVisible())
        self.assertEqual(result.title.text(), "Estadísticas del texto")
        self.assertIn("12 palabras", result.content.toPlainText())
        self.assertNotEqual(result.geometry(), toolbar.geometry())
        result._copy_result()
        self.assertIn("12 palabras", self.app.clipboard().text())
        result.close()

    def test_popup_theme_does_not_compact_palette_controls(self):
        popup = PopupWindow(DEFAULT_ACTIONS, None, dict(DEFAULT_SETTINGS))
        popup.show()
        self.app.processEvents()
        popup._open_palette(DEFAULT_ACTIONS, popup._action_buttons[-1])
        self.app.processEvents()
        self.assertGreater(popup.palette.pin.width(), 100)
        self.assertGreater(
            popup.palette.pin.width(), popup._action_buttons[0].width()
        )
        popup.palette.hide()
        popup.hide()

    def test_visible_limit_counts_direct_actions_not_more_button(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 12
        actions = DEFAULT_ACTIONS[:15]
        popup = PopupWindow(actions, None, settings)
        popup.show()
        self.app.processEvents()

        self.assertEqual(len(popup.visible_actions), 12)
        self.assertEqual(len(popup._action_buttons), 12)
        self.assertIsNotNone(popup._more_button)
        popup._more_button.click()
        self.app.processEvents()
        self.assertEqual(popup.palette.list.count(), 3)

        popup.palette.hide()
        popup.hide()

    def test_more_actions_contains_every_catalog_action_not_on_the_bar(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 8
        catalog = DEFAULT_ACTIONS[:15]
        direct = [catalog[index] for index in (0, 3, 6, 9, 12)]
        popup = PopupWindow(direct, None, settings)
        popup.set_actions(direct, palette_actions=catalog)
        popup.show()
        self.app.processEvents()

        self.assertEqual(
            [action["cmd"] for action in popup.visible_actions],
            [action["cmd"] for action in direct],
        )
        self.assertIsNotNone(popup._more_button)
        popup._more_button.click()
        self.app.processEvents()
        expected = [
            action["cmd"] for action in catalog if action not in direct
        ]
        actual = [
            popup.palette.list.item(index).data(Qt.UserRole)
            for index in range(popup.palette.list.count())
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(popup.palette.title.text(), "Más acciones")
        self.assertIn("10 no fijadas", popup.palette.subtitle.text())
        popup.palette.hide()
        popup.hide()

    def test_closing_more_actions_also_closes_its_toolbar(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 8
        popup = PopupWindow(DEFAULT_ACTIONS[:12], None, settings)
        popup.show()
        self.app.processEvents()
        popup._more_button.click()
        self.app.processEvents()
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup.palette.isVisible())

        popup.palette.hide()
        self.app.processEvents()

        self.assertFalse(popup.palette.isVisible())
        self.assertFalse(popup.isVisible())

    def test_bar_and_overflow_keep_the_configured_order(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 8
        order = [7, 1, 10, 0, 5, 3, 9, 2, 11, 4]
        actions = [DEFAULT_ACTIONS[index] for index in order]
        popup = PopupWindow(actions, None, settings)
        popup.show()
        self.app.processEvents()
        self.assertEqual(
            [action["cmd"] for action in popup.visible_actions],
            [action["cmd"] for action in actions[:8]],
        )
        popup._more_button.click()
        self.app.processEvents()
        self.assertEqual(
            [
                popup.palette.list.item(index).data(Qt.UserRole)
                for index in range(popup.palette.list.count())
            ],
            [action["cmd"] for action in actions[8:]],
        )
        popup.palette.hide()
        popup.hide()

    def test_popup_width_tracks_the_number_of_integrated_actions(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 12
        settings["popup_compact_actions"] = 8
        popup = PopupWindow(DEFAULT_ACTIONS[:4], None, settings)
        popup.show()
        self.app.processEvents()
        compact_width = popup.width()

        popup.set_actions(DEFAULT_ACTIONS[:12])
        self.app.processEvents()
        expanded_width = popup.width()
        self.assertGreater(expanded_width, compact_width)

        popup.set_actions(DEFAULT_ACTIONS[:6])
        self.app.processEvents()
        self.assertLess(popup.width(), expanded_width)
        popup.hide()

    def test_repeated_recomposition_never_collapses_to_an_empty_wayland_size(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 8
        popup = PopupWindow(DEFAULT_ACTIONS[:8], None, settings)
        popup.show()
        for count in (12, 8, 15, 9, 14, 8) * 5:
            popup._actions_key = None
            popup.set_actions(DEFAULT_ACTIONS[:count])
            self.app.processEvents()
            self.assertGreaterEqual(popup.width(), 8 * 25)
            self.assertGreaterEqual(popup.height(), 25)
        popup.hide()

    def test_nonactivating_popup_ignores_focus_loss(self):
        popup = PopupWindow(DEFAULT_ACTIONS[:8], None, dict(DEFAULT_SETTINGS))
        self.assertTrue(popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        popup.show()
        self.app.processEvents()
        popup.keyboard_mode = False
        popup.hide_if_focus_outside()
        self.assertTrue(popup.isVisible())
        popup.hide()

    def test_action_uses_selection_snapshot_if_primary_clears_on_press(self):
        monitor = SimpleNamespace(get_last_text=lambda: "")
        popup = PopupWindow(DEFAULT_ACTIONS[:1], monitor, dict(DEFAULT_SETTINGS))
        popup.set_context(SimpleNamespace(text="texto capturado", application="Editor"))
        triggered = []
        popup.action_triggered.connect(
            lambda command, text: triggered.append((command, text))
        )
        popup._on_click(DEFAULT_ACTIONS[0])
        self.assertEqual(triggered, [("copy", "texto capturado")])

    def test_show_all_mode_places_every_action_on_the_bar(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["show_all_popup_actions"] = True
        actions = DEFAULT_ACTIONS[:15]
        popup = PopupWindow(actions, None, settings)
        popup.show()
        self.app.processEvents()

        self.assertEqual(len(popup.visible_actions), len(actions))
        self.assertEqual(len(popup._action_buttons), len(actions))
        self.assertIsNone(popup._more_button)
        popup.hide()

    def test_adaptive_mode_uses_compact_direct_action_limit(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["max_popup_actions"] = 12
        settings["popup_compact_actions"] = 8
        actions = DEFAULT_ACTIONS[:15]
        popup = PopupWindow(actions, None, settings)
        popup.set_actions(actions, compact=True)
        popup.show()
        self.app.processEvents()

        self.assertEqual(len(popup.visible_actions), 8)
        self.assertEqual(len(popup._action_buttons), 8)
        self.assertIsNotNone(popup._more_button)
        self.assertEqual(
            popup._action_buttons[0].accessibleName(), actions[0]["name"]
        )
        self.assertEqual(popup._more_button.accessibleName(), "Más acciones")
        more_index = popup.buttons_layout.indexOf(popup._more_button)
        row, column, _row_span, _column_span = (
            popup.buttons_layout.getItemPosition(more_index)
        )
        self.assertEqual((row, column), (0, 8))
        popup.hide()


class SettingsAboutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _controller():
        availability = SimpleNamespace(
            available=True,
            degraded=False,
            label="Disponible",
        )
        return SimpleNamespace(
            atspi=SimpleNamespace(available=True),
            actions=list(DEFAULT_ACTIONS),
            popup=SimpleNamespace(set_actions=lambda _actions: None),
            build_diagnostics=lambda: "OK",
            action_integration_status=lambda _action: availability,
            save_actions=lambda: None,
            update_settings=lambda _settings: None,
            test_popup=lambda: None,
        )

    def test_about_tab_exposes_version_description_and_github_actions(self):
        dialog = SettingsDialog(
            dict(DEFAULT_SETTINGS), DEFAULT_ACTIONS, self._controller()
        )
        tabs = dialog.findChild(QTabWidget)
        labels = [tabs.tabText(index).strip() for index in range(tabs.count())]
        self.assertIn("Acerca de", labels)
        self.assertIn(APP_VERSION, dialog.about_version_label.text())
        self.assertIn("Linux", dialog.about_description_label.text())

        with patch("src.textpik.QDesktopServices.openUrl", return_value=True) as opener:
            dialog.github_profile_button.click()
            self.assertEqual(opener.call_args.args[0].toString(), "https://github.com/pitydah")
            dialog.sponsor_button.click()
            self.assertEqual(
                opener.call_args.args[0].toString(),
                "https://github.com/sponsors/pitydah",
            )
            dialog.close()

    def test_action_editor_persists_the_exact_manual_order(self):
        actions = list(DEFAULT_ACTIONS[:4])
        dialog = SettingsDialog(
            dict(DEFAULT_SETTINGS), actions, self._controller()
        )
        moved = dialog.action_list.takeItem(3)
        dialog.action_list.insertItem(0, moved)
        _settings, collected = dialog.collect_settings()
        self.assertEqual(
            [action["cmd"] for action in collected],
            [actions[3]["cmd"], actions[0]["cmd"], actions[1]["cmd"], actions[2]["cmd"]],
        )
        dialog.close()

    def test_about_links_reject_non_github_targets(self):
        with patch("src.textpik.QDesktopServices.openUrl") as opener:
            self.assertFalse(SettingsDialog._open_external_url("http://example.com"))
            opener.assert_not_called()

    def test_context_profiles_round_trip_through_settings_ui(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["context_profiles_enabled"] = True
        settings["context_profiles"] = [
            {
                "name": "Navegador",
                "application": "firefox",
                "text_types": ["url"],
                "action_ids": ["copy"],
            }
        ]
        dialog = SettingsDialog(settings, DEFAULT_ACTIONS, self._controller())
        self.assertTrue(dialog.context_profiles_enabled.isChecked())
        self.assertEqual(dialog.context_profiles_list.count(), 1)
        collected, _actions = dialog.collect_settings()
        self.assertEqual(collected["context_profiles"], settings["context_profiles"])
        dialog.close()

    def test_visual_automation_editor_builds_declarative_flow(self):
        dialog = AutomationEditDialog()
        dialog.name_edit.setText("Limpiar error")
        dialog.application_edit.setText("terminal")
        dialog.types_edit.setText("error, code")
        dialog.operation_combo.setCurrentText("replace")
        dialog.source_edit.setText("ERROR:")
        dialog.value_edit.setText("")
        dialog._add_step()
        flow = dialog.get_flow()
        self.assertEqual(flow["conditions"]["application"], "terminal")
        self.assertEqual(flow["conditions"]["text_types"], ["error", "code"])
        self.assertEqual(flow["steps"][0]["operation"], "replace")
        dialog.close()

    def test_visual_automation_editor_applies_and_reorders_templates(self):
        dialog = AutomationEditDialog()
        dialog.template_combo.setCurrentIndex(
            dialog.template_combo.findData("quote")
        )
        dialog._apply_template()
        self.assertEqual(dialog.steps_list.count(), 2)
        self.assertEqual(dialog.name_edit.text(), "Entre comillas")
        dialog.steps_list.setCurrentRow(1)
        dialog._move_step(-1)
        operations = [step["operation"] for step in dialog.get_flow()["steps"]]
        self.assertEqual(operations, ["suffix", "prefix"])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
