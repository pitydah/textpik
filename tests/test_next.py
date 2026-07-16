import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.textpik_core.automation import automation_matches, preview_automation
from src.textpik_core.grammar import LanguageToolService, apply_suggestions
from src.textpik_core.history import HistoryStore
from src.textpik_core.insights import convert_units, local_insight, safe_calculate
from src.textpik_core.models import SelectionContext
from src.textpik_core.ranking import LocalActionRanker
from src.textpik_core.performance import read_process_resources
from src.textpik_core.extensions import inspect_local_extensions
from src.textpik_core.providers import OllamaProvider, TesseractProvider
from src.textpik_core.spelling import SpellingService
from src.textpik_core.text import classify_text
from src.textpik_core.undo import UndoManager
from src.textpik_core.wasi import MAX_MEMORY_BYTES, run_wasi
from src.textpik_core.health import CrashSentinel
from src.textpik_core.interaction import (
    modifier_key,
    plan_popup_composition,
    resolve_action_command,
)
from src.textpik_core.utilities import (
    clean_terminal_text,
    color_details,
    compare_text,
    extract_entities,
    format_json,
    slugify,
)
from src.textpik_core.selection import adaptive_selection_delay


class InsightTest(unittest.TestCase):
    def test_safe_calculator_rejects_code_and_bounds_exponents(self):
        self.assertEqual(safe_calculate("2 + 3 * 4"), 14)
        with self.assertRaises(ValueError):
            safe_calculate("__import__('os')")
        with self.assertRaises(ValueError):
            safe_calculate("2 ** 999")

    def test_local_conversions_are_offline(self):
        self.assertEqual(convert_units("10 km a mi").value, "6.213712 mi")
        self.assertEqual(local_insight("(5 + 3) * 2").value, "16")

    def test_extended_classifier(self):
        self.assertIn("coordinates", classify_text("-33.45, -70.66"))
        self.assertIn("doi", classify_text("10.1000/xyz123"))
        self.assertIn("isbn", classify_text("978-3-16-148410-0"))
        self.assertIn("date", classify_text("2026-07-14"))
        self.assertIn("error", classify_text("RuntimeError: failed: test"))
        self.assertIn("json", classify_text('{"ok": true}'))
        self.assertIn("uuid", classify_text("550e8400-e29b-41d4-a716-446655440000"))
        self.assertIn("hash", classify_text("a" * 64))

    def test_lightweight_local_utilities(self):
        self.assertEqual(format_json('{"b":1,"a":2}'), '{\n  "a": 2,\n  "b": 1\n}')
        self.assertEqual(format_json('{"b":1}', compact=True), '{"b":1}')
        self.assertEqual(slugify("Acción rápida"), "accion-rapida")
        self.assertEqual(clean_terminal_text("\x1b[31mError\x1b[0m\r\n"), "Error\n")
        self.assertIn("RGB 255, 0, 170", color_details("#f0a"))
        self.assertIn("-uno", compare_text("uno", "dos"))
        entities = extract_entities("Visita https://example.com o escribe a hi@example.com")
        self.assertEqual(entities.urls, ("https://example.com",))
        self.assertEqual(entities.emails, ("hi@example.com",))


class WritingTest(unittest.TestCase):
    def test_spelling_language_order_ignore_and_add(self):
        class Dictionary:
            def __init__(self):
                self.added = []

            def add(self, word):
                self.added.append(word)

        dictionary = Dictionary()
        service = SpellingService(lambda _language: dictionary)
        self.assertEqual(service.language_candidates("el niño", "es-CL")[0], "es_CL")
        service.ignore("TextPik")
        self.assertIsNone(service.suggest("TextPik", ("es_CL",)))
        self.assertTrue(service.add("TextPik", "es_CL"))
        self.assertEqual(dictionary.added, ["TextPik"])

    def test_language_tool_is_bounded_and_applies_backwards(self):
        payload = json.dumps({"matches": [{
            "offset": 0, "length": 4, "message": "Mayúscula",
            "replacements": [{"value": "Hola"}], "rule": {"id": "UPPER"}
        }]}).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with patch("urllib.request.urlopen", return_value=response):
            matches = LanguageToolService().check("hola mundo", "es")
        self.assertEqual(apply_suggestions("hola mundo", matches), "Hola mundo")
        self.assertEqual(matches[0].rule_id, "UPPER")


class AutomationAndStateTest(unittest.TestCase):
    def test_popup_composition_and_modifier_variants(self):
        composition = plan_popup_composition(
            20, requested=12, row_capacity=6, allow_two_rows=True,
        )
        self.assertEqual((composition.direct_count, composition.rows), (11, 2))
        self.assertEqual(composition.overflow_count, 9)
        self.assertEqual(modifier_key(shift=True, control=True), "control+shift")
        action = {"cmd": "format-json", "variants": {"alt": "minify-json"}}
        self.assertEqual(resolve_action_command(action, "alt"), "minify-json")
        self.assertEqual(resolve_action_command(action, "shift"), "format-json")

    def test_adaptive_delay_is_bounded_and_respects_context(self):
        editor = SelectionContext("hola", application="Editor", role="text", editable=True)
        files = SelectionContext("hola", application="Dolphin", role="text")
        self.assertLess(
            adaptive_selection_delay(editor, editor.text),
            adaptive_selection_delay(files, files.text),
        )
        self.assertLessEqual(adaptive_selection_delay(files, "x", recent_changes=99), 250)

    def test_crash_sentinel_records_only_process_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "running.json"
            sentinel = CrashSentinel(path)
            self.assertFalse(sentinel.start("0.5").unclean)
            payload = json.loads(path.read_text())
            self.assertEqual(set(payload), {"pid", "started_at", "version"})
            self.assertTrue(sentinel.start("0.5").unclean)
            sentinel.clean()
            self.assertFalse(path.exists())
    def test_automation_is_declarative_and_transactional(self):
        context = SelectionContext("hola\nmundo", application="Firefox", editable=True)
        flow = {
            "conditions": {"application": "fire", "editable": True, "text_types": ["text"]},
            "steps": [{"operation": "remove-breaks"}, {"operation": "capitalize"}],
        }
        self.assertTrue(automation_matches(flow, context, {"text"}))
        preview = preview_automation(flow, context.text)
        self.assertEqual(preview.after, "Hola mundo")
        self.assertEqual(preview.before, context.text)

    def test_automation_conditions_fail_closed(self):
        context = SelectionContext("hola", application="Editor", editable=False)
        self.assertFalse(automation_matches({"conditions": {"editable": True}}, context, {"text"}))
        self.assertFalse(automation_matches({"conditions": {"min_length": 10}}, context, {"text"}))
        self.assertFalse(automation_matches({"conditions": {"text_types": ["url"]}}, context, {"text"}))
        self.assertFalse(automation_matches({"conditions": {"regex": "["}}, context, {"text"}))
        self.assertFalse(automation_matches({"conditions": {"regex": "x" * 257}}, context, {"text"}))
        self.assertFalse(automation_matches({"conditions": {"regex": "(a+)+$"}}, context, {"text"}))

    def test_automation_operations_are_bounded(self):
        preview = preview_automation({"steps": [
            {"operation": "prefix", "value": "["},
            {"operation": "replace", "source": "hola", "target": "mundo"},
            {"operation": "suffix", "value": "]"},
        ]}, "hola")
        self.assertEqual(preview.after, "[mundo]")
        with self.assertRaises(ValueError):
            preview_automation({"steps": "not-a-list"}, "hola")
        with self.assertRaises(ValueError):
            preview_automation({"steps": [{"operation": "shell"}]}, "hola")
        with self.assertRaises(ValueError):
            preview_automation({"steps": [{"operation": "replace", "source": ""}]}, "hola")

    def test_undo_is_bounded_and_content_is_never_persisted(self):
        manager = UndoManager(maximum=2)
        manager.remember("a", "A", "editor")
        self.assertEqual(manager.pop("editor").before, "a")
        self.assertIsNone(manager.pop())

    def test_ranker_serializes_context_but_not_selected_text(self):
        ranker = LocalActionRanker()
        ranker.record("copy", "Firefox", {"url"})
        self.assertEqual(ranker.suggest(["search", "copy"], "Firefox", {"url"}), ("copy",))
        payload = json.dumps(ranker.serialize())
        self.assertNotIn("secret selection", payload)

    def test_history_rejects_sensitive_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = HistoryStore(Path(temporary) / "history.json", maximum=2)
            self.assertFalse(store.add("password: hunter2", "editor"))
            self.assertTrue(store.add("one", "editor"))
            self.assertTrue(store.add("two", "editor"))
            self.assertTrue(store.add("three", "editor"))
            self.assertEqual([entry.text for entry in store.load()], ["three", "two"])

    def test_history_recovers_from_corrupt_or_malformed_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "history.json"
            path.write_text("not json")
            self.assertEqual(HistoryStore(path).load(), [])
            path.write_text(json.dumps({"entries": [{"text": "missing timestamp"}, {
                "text": "valid", "created_at": 9_999_999_999,
            }]}))
            self.assertEqual([entry.text for entry in HistoryStore(path).load()], ["valid"])

    def test_process_resources_use_proc_files_without_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "status").write_text("VmRSS:\t1234 kB\nThreads:\t3\n")
            (root / "smaps_rollup").write_text("Pss:\t987 kB\n")
            resources = read_process_resources(root)
        self.assertEqual((resources.rss_kib, resources.pss_kib, resources.threads), (1234, 987, 3))

    def test_v2_wasi_extension_requires_matching_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            extension = Path(temporary) / "clean"
            extension.mkdir()
            module = extension / "clean.wasm"
            module.write_bytes(b"\0asm")
            (extension / "manifest.json").write_text(json.dumps({
                "schema_version": 2,
                "runtime": "wasi",
                "module": "clean.wasm",
                "sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "action": {"id": "clean", "name": "Clean", "icon": "copy.svg", "permissions": []},
            }))
            actions, issues = inspect_local_extensions(Path(temporary))
        self.assertFalse(issues)
        self.assertEqual(actions[0]["cmd"], "wasi:clean/clean.wasm")
        self.assertIn("process", actions[0]["permissions"])

    def test_ollama_provider_rejects_non_local_endpoint(self):
        with self.assertRaises(ValueError):
            OllamaProvider("https://example.com/api")

    def test_ollama_provider_success_and_input_validation(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "response": json.dumps({"text": "Texto mejorado"}),
        }).encode()
        with patch("urllib.request.urlopen", return_value=response) as open_url:
            result = OllamaProvider(timeout=0).generate("texto", model="llama3.2:3b")
        self.assertEqual((result.text, result.provider), ("Texto mejorado", "ollama"))
        self.assertEqual(open_url.call_args.kwargs["timeout"], 1.0)
        with self.assertRaises(ValueError):
            OllamaProvider().generate("", model="llama3")
        with self.assertRaises(ValueError):
            OllamaProvider().generate("texto", model="--invalid model")

    def test_ollama_provider_cancellation_and_oversized_response(self):
        from threading import Event

        cancelled = Event()
        cancelled.set()
        with self.assertRaises(RuntimeError):
            OllamaProvider().generate("texto", cancelled=cancelled)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"x" * 2_000_001
        with patch("urllib.request.urlopen", return_value=response), self.assertRaises(RuntimeError):
            OllamaProvider().generate("texto")

    def test_tesseract_provider_success_failure_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "scan.png"
            image.write_bytes(b"png")
            completed = subprocess.CompletedProcess([], 0, " texto reconocido \n", "")
            with patch("subprocess.run", return_value=completed) as run:
                result = TesseractProvider(timeout=1).recognize(image)
            self.assertEqual(result.text, "texto reconocido")
            self.assertEqual(run.call_args.args[0][-2:], ["-l", "eng+spa"])
            with self.assertRaises(ValueError):
                TesseractProvider().recognize(image, "--bad language")
            failed = subprocess.CompletedProcess([], 1, "", "modelo ausente")
            with patch("subprocess.run", return_value=failed), self.assertRaisesRegex(RuntimeError, "modelo ausente"):
                TesseractProvider().recognize(image)

    def test_wasi_runner_is_bounded_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / "action.wasm"
            module.write_bytes(b"\\0asm")
            completed = subprocess.CompletedProcess([], 0, "resultado", "")
            with patch("shutil.which", return_value="/usr/bin/wasmtime"), patch(
                "subprocess.run", return_value=completed,
            ) as run:
                self.assertEqual(run_wasi(module, "entrada", timeout_ms=50_000), "resultado")
            command = run.call_args.args[0]
            self.assertIn(f"max-memory-size={MAX_MEMORY_BYTES}", " ".join(command))
            self.assertEqual(run.call_args.kwargs["timeout"], 10.0)
            failed = subprocess.CompletedProcess([], 2, "", "trap")
            with patch("shutil.which", return_value="wasmtime"), patch(
                "subprocess.run", return_value=failed,
            ), self.assertRaisesRegex(RuntimeError, "trap"):
                run_wasi(module, "entrada")
            with patch("shutil.which", return_value=None), self.assertRaisesRegex(RuntimeError, "not installed"):
                run_wasi(module, "entrada")
            with patch("shutil.which", return_value="wasmtime"), self.assertRaises(ValueError):
                run_wasi(module, "x" * 500_001)


if __name__ == "__main__":
    unittest.main()
