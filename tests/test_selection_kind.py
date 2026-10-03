"""Selection intent: what the user highlighted, not what the string looks like.

A path inside an editor is text. The same path copied from Dolphin is a file
object. The string cannot tell them apart, so the classifier reads the MIME
flavours the selection publishes and the AT-SPI role of the node, and never the
content of the string itself.
"""

import unittest

from src.textpik_core.models import SelectionContext
from src.textpik_core.selection import (
    SelectionKind,
    SelectionMimeEvidence,
    classify_selection,
    evaluate_selection_intent,
)


def file_context(application="dolphin", role="icon", **kwargs):
    return SelectionContext(
        text=kwargs.pop("text", "informe.pdf"),
        application=application,
        role=role,
        **kwargs,
    )


class MimeEvidenceTest(unittest.TestCase):
    def test_uri_list_format_is_a_file_object(self):
        evidence = SelectionMimeEvidence(
            has_text=True,
            formats=("text/plain", "text/uri-list"),
        )
        self.assertTrue(evidence.is_file_object)

    def test_urls_flag_is_a_file_object_even_with_plain_text(self):
        evidence = SelectionMimeEvidence(has_text=True, has_urls=True)
        self.assertTrue(evidence.is_file_object)

    def test_plain_text_only_is_not_a_file_object(self):
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain", "text/plain;charset=utf-8")
        )
        self.assertFalse(evidence.is_file_object)


class ClassifySelectionTest(unittest.TestCase):
    def test_mime_uri_list_rejects_a_file(self):
        """The case the string-based heuristics could never get right."""
        context = SelectionContext(text="informe.pdf", backend="clipboard")
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain", "text/uri-list")
        )
        self.assertEqual(
            classify_selection(context, "informe.pdf", evidence),
            SelectionKind.FILE_OBJECT,
        )

    def test_has_urls_rejects_a_file(self):
        context = SelectionContext(text="file:///tmp/a.pdf", backend="clipboard")
        evidence = SelectionMimeEvidence(has_urls=True)
        self.assertEqual(
            classify_selection(context, "file:///tmp/a.pdf", evidence),
            SelectionKind.FILE_OBJECT,
        )

    def test_a_textual_url_in_a_browser_stays_text(self):
        """Selecting a URL in a page is text, and must keep working."""
        context = SelectionContext(
            text="https://example.com", application="firefox", role="text"
        )
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain", "text/html")
        )
        self.assertEqual(
            classify_selection(context, "https://example.com", evidence),
            SelectionKind.TEXT,
        )

    def test_plain_text_selection_without_metadata_is_unknown(self):
        context = SelectionContext(text="hola mundo", backend="clipboard")
        self.assertEqual(
            classify_selection(context, "hola mundo", None),
            SelectionKind.UNKNOWN,
        )

    def test_file_manager_icon_role_is_a_file_object(self):
        for role in ("icon", "list item", "tree item", "table cell"):
            with self.subTest(role=role):
                context = file_context(role=role)
                self.assertEqual(
                    classify_selection(context, "informe.pdf", None),
                    SelectionKind.FILE_OBJECT,
                )

    def test_file_manager_text_role_is_text(self):
        for role in ("text", "entry", "paragraph", "document"):
            with self.subTest(role=role):
                context = file_context(role=role, editable=True)
                self.assertEqual(
                    classify_selection(context, "informe.pdf", None),
                    SelectionKind.TEXT,
                )

    def test_file_manager_without_a_role_is_treated_as_the_file_name(self):
        """A bare string from a file manager is the selected item's name."""
        context = file_context(role="")
        self.assertEqual(
            classify_selection(context, "informe.pdf", None),
            SelectionKind.FILE_OBJECT,
        )

    def test_text_only_mime_rescues_a_file_manager_field_without_role(self):
        """AT-SPI can lag the clipboard; MIME says this is not a file object."""
        context = file_context(role="", text="informe")
        evidence = SelectionMimeEvidence(has_text=True, formats=("text/plain",))
        self.assertEqual(
            classify_selection(context, "informe", evidence),
            SelectionKind.TEXT,
        )

    def test_file_object_mime_still_wins_over_a_missing_role(self):
        context = file_context(role="", text="informe.pdf")
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain", "text/uri-list")
        )
        self.assertEqual(
            classify_selection(context, "informe.pdf", evidence),
            SelectionKind.FILE_OBJECT,
        )

    def test_path_like_text_in_an_editor_is_text(self):
        """The trap: /home/user/foo.pdf selected in an editor is text."""
        context = SelectionContext(
            text="/home/user/documento.pdf",
            application="code",
            role="text",
            backend="atspi",
        )
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain",)
        )
        self.assertEqual(
            classify_selection(context, "/home/user/documento.pdf", evidence),
            SelectionKind.TEXT,
        )
        intent = evaluate_selection_intent(
            context, "/home/user/documento.pdf", mime=evidence
        )
        self.assertTrue(intent.allowed)
        self.assertEqual(intent.kind, SelectionKind.TEXT)

    def test_sensitive_wins_over_everything(self):
        context = SelectionContext(text="hunter2", sensitive=True)
        evidence = SelectionMimeEvidence(has_urls=True)
        self.assertEqual(
            classify_selection(context, "hunter2", evidence),
            SelectionKind.SENSITIVE,
        )

    def test_non_text_control_role_is_rejected(self):
        for role in ("push button", "menu item", "check box"):
            with self.subTest(role=role):
                context = SelectionContext(text="Aceptar", role=role)
                self.assertEqual(
                    classify_selection(context, "Aceptar", None),
                    SelectionKind.NON_TEXT_CONTROL,
                )


class IntentPolicyTest(unittest.TestCase):
    def test_file_object_is_suppressed_by_default(self):
        context = SelectionContext(text="informe.pdf", backend="clipboard")
        evidence = SelectionMimeEvidence(has_urls=True)
        intent = evaluate_selection_intent(
            context, "informe.pdf", mime=evidence
        )
        self.assertFalse(intent.allowed)
        self.assertEqual(intent.reason, "file-selection")
        self.assertEqual(intent.kind, SelectionKind.FILE_OBJECT)

    def test_file_object_is_kept_when_the_user_disables_the_filter(self):
        context = SelectionContext(text="informe.pdf", backend="clipboard")
        evidence = SelectionMimeEvidence(has_urls=True)
        intent = evaluate_selection_intent(
            context, "informe.pdf", mime=evidence, ignore_files=False
        )
        self.assertTrue(intent.allowed)

    def test_unknown_evidence_still_allows_ordinary_text(self):
        context = SelectionContext(text="hola mundo", backend="clipboard")
        intent = evaluate_selection_intent(context, "hola mundo", mime=None)
        self.assertTrue(intent.allowed)
        self.assertEqual(intent.kind, SelectionKind.UNKNOWN)

    def test_dolphin_file_selection_end_to_end_is_suppressed(self):
        context = file_context(role="")
        evidence = SelectionMimeEvidence(
            has_text=True, formats=("text/plain", "text/uri-list")
        )
        intent = evaluate_selection_intent(
            context, "informe.pdf", mime=evidence
        )
        self.assertFalse(intent.allowed)

    def test_dolphin_rename_field_end_to_end_is_allowed(self):
        context = file_context(role="text", editable=True, text="informe.pdf")
        evidence = SelectionMimeEvidence(has_text=True, formats=("text/plain",))
        intent = evaluate_selection_intent(
            context, "informe.pdf", mime=evidence
        )
        self.assertTrue(intent.allowed)


if __name__ == "__main__":
    unittest.main()
