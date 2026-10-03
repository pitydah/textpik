import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "textpik.py"
ACTIONS_DIR = ROOT / "assets" / "actions"


def default_actions():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_ACTIONS"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("DEFAULT_ACTIONS not found")


class ActionAssetsTest(unittest.TestCase):
    def test_ai_actions_use_dedicated_brand_masters_without_backgrounds(self):
        expected = {
            "Preguntar a Claude": "claude.svg",
            "Preguntar a Gemini": "gemini.svg",
        }
        icons = {
            action["name"]: action["icon"]
            for action in default_actions()
            if action["name"] in expected
        }
        self.assertEqual(icons, expected)
        for icon in expected.values():
            source = (ACTIONS_DIR / icon).read_text(encoding="utf-8").lower()
            with self.subTest(icon=icon):
                self.assertNotIn("<rect", source)
                self.assertNotIn("gradient", source)
                self.assertNotIn("filter", source)

    def test_semantic_actions_use_distinct_pictograms(self):
        expected = {
            "count": "count-words.svg",
            "insight": "calculator.svg",
            "grammar": "grammar.svg",
            "undo": "undo.svg",
            "textpik-history": "history.svg",
            "ocr-image": "ocr-image.svg",
            "ocr-region": "ocr-region.svg",
            "format-json": "json.svg",
            "extract-entities": "extract-entities.svg",
            "color-details": "color-picker.svg",
            "slugify": "slug.svg",
            "clean-terminal": "terminal-clean.svg",
            "compare-clipboard": "compare.svg",
            "speak": "speak.svg",
            "open-magnet": "magnet.svg",
            "send-magnet": "torrent-server.svg",
            "open-media-player": "media-player.svg",
        }
        icons = {
            action["cmd"]: action["icon"]
            for action in default_actions()
            if action["cmd"] in expected
        }
        self.assertEqual(icons, expected)
        self.assertEqual(len(set(icons.values())), len(expected))

    def test_every_default_action_has_a_master_svg(self):
        missing = [
            action["icon"]
            for action in default_actions()
            if not (ACTIONS_DIR / action["icon"]).is_file()
        ]
        self.assertEqual(missing, [])

    def test_svg_masters_are_self_contained_and_square(self):
        for action in default_actions():
            path = ACTIONS_DIR / action["icon"]
            with self.subTest(icon=path.name):
                root = ET.parse(path).getroot()
                view_box = root.attrib.get("viewBox", "").split()
                self.assertEqual(len(view_box), 4)
                self.assertEqual(float(view_box[2]), float(view_box[3]))
                source = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("<image", source)
                self.assertNotIn("<text", source)
                self.assertNotIn(
                    "http://", source.replace("http://www.w3.org/2000/svg", "")
                )


if __name__ == "__main__":
    unittest.main()
