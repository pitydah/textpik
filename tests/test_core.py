import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.textpik import (
    ActionPalette,
    BaseSelectionMonitor,
    build_command_argv,
    classify_text,
    desktop_environment,
    is_kde,
    normalize_settings,
    normalize_url,
    validate_actions,
)


class CoreHelpersTest(unittest.TestCase):
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
