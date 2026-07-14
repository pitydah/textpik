import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def test_flatpak_identity_and_command_are_consistent(self):
        manifest = json.loads(
            (ROOT / "packaging/flatpak/io.github.pitydah.textpik.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["app-id"], "io.github.pitydah.textpik")
        self.assertEqual(manifest["command"], "textpik")
        self.assertIn("--share=network", manifest["finish-args"])
        self.assertIn("--talk-name=org.a11y.Bus", manifest["finish-args"])
        self.assertIn("--own-name=org.textpik.CursorBridge", manifest["finish-args"])

    def test_appimage_entrypoint_matches_pyinstaller_name(self):
        script = (ROOT / "packaging/appimage/build.sh").read_text(encoding="utf-8")
        self.assertIn('ln -sf TextPik "$APPDIR/AppRun"', script)

    def test_user_install_is_independent_from_checkout(self):
        script = (ROOT / "packaging/install.sh").read_text(encoding="utf-8")
        self.assertIn('APP_DIR="$HOME/.local/share/$APP_NAME"', script)
        self.assertIn('exec python3 "$APP_DIR/src/textpik.py"', script)
        self.assertIn('cp -a "$PROJECT_DIR/src/textpik_core"', script)
        for package_manager in ("apk", "xbps-install", "slackpkg"):
            self.assertIn(package_manager, script)

    def test_native_package_recipes_exist(self):
        self.assertTrue((ROOT / "packaging/debian/control").is_file())
        self.assertTrue((ROOT / "packaging/rpm/textpik.spec").is_file())
        self.assertTrue((ROOT / "pyproject.toml").is_file())

    def test_appstream_metadata_is_valid_xml(self):
        root = ET.parse(
            ROOT / "packaging/io.github.pitydah.textpik.metainfo.xml"
        ).getroot()
        self.assertEqual(root.findtext("id"), "io.github.pitydah.textpik")
        self.assertEqual(root.find("provides/binary").text, "textpik")

    def test_release_versions_are_consistent(self):
        result = subprocess.run(
            [sys.executable, "scripts/check_release.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
