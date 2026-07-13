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
