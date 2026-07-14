import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


class ApplicationSmokeTest(unittest.TestCase):
    def test_offscreen_startup_popup_and_clean_shutdown(self):
        program = textwrap.dedent(
            """
            import sys
            from PySide6.QtCore import QTimer
            import src.textpik as textpik

            class SmokeSelectionMonitor(textpik.BaseSelectionMonitor):
                pass

            textpik.X11SelectionMonitor = SmokeSelectionMonitor
            textpik.WaylandSelectionMonitor = SmokeSelectionMonitor

            controller = textpik.TextPikApp()
            if "enchant" in sys.modules:
                raise SystemExit("optional spelling provider loaded during startup")
            first_action_id = controller.actions[0]["id"]
            controller.settings["context_profiles_enabled"] = True
            controller.settings["context_profiles"] = [{
                "name": "Smoke profile",
                "application": "Smoke Editor",
                "text_types": ["text"],
                "action_ids": [first_action_id],
            }]
            context = textpik.SelectionContext(
                text="release candidate smoke test",
                application="Smoke Editor",
                role="text",
            )
            session = controller._begin_selection_session("smoke-test")
            controller.monitor._last_text = context.text
            controller.show_popup(context=context, session_id=session)
            if not controller.popup.isVisible():
                raise SystemExit("popup did not become visible")
            if len(controller.popup.visible_actions) != 1:
                raise SystemExit("context profile was not applied")
            controller.hide_popup()
            QTimer.singleShot(0, controller.quit)
            exit_code = controller.app.exec()
            if exit_code != 0 or not controller._cleaned_up:
                raise SystemExit("application did not shut down cleanly")
            """
        )
        with tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env.update(
                {
                    "HOME": home,
                    "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                    "XDG_CACHE_HOME": os.path.join(home, ".cache"),
                    "QT_QPA_PLATFORM": os.environ.get(
                        "TEXTPIK_SMOKE_QPA", "offscreen"
                    ),
                    # Keep the interpreter's installed Qt bindings available
                    # while HOME is isolated from the user's real config.
                    "PYTHONPATH": os.pathsep.join(sys.path),
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
