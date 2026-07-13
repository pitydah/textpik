import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src.textpik import (
    ActionPalette,
    BaseSelectionMonitor,
    TextPikApp,
    FunctionWorker,
    build_command_argv,
    classify_text,
    desktop_environment,
    is_kde,
    normalize_settings,
    normalize_url,
    validate_actions,
)


class CoreHelpersTest(unittest.TestCase):
    def test_popup_hot_path_avoids_desktop_subprocess_probes(self):
        source = inspect.getsource(TextPikApp.show_popup)
        self.assertNotIn("hyprland_cursor_anchor(", source)
        self.assertNotIn("sway_cursor_anchor(", source)
        self.assertNotIn("get_cursor_pos(", source)
        self.assertNotIn("is_foreground_process_game(", source)

    def test_boolean_strings_are_normalized(self):
        settings = normalize_settings({"sticky_popup": "false", "context_aware": "yes"})
        self.assertFalse(settings["sticky_popup"])
        self.assertTrue(settings["context_aware"])

    def test_popup_limit_is_clamped(self):
        self.assertEqual(
            normalize_settings({"max_popup_actions": 1})["max_popup_actions"], 3
        )
        self.assertEqual(
            normalize_settings({"max_popup_actions": 99})["max_popup_actions"], 20
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


if __name__ == "__main__":
    unittest.main()
