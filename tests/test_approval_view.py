"""
Approval view tests. Run with: python -m unittest tests.test_approval_view -v

Display helpers only, with made-up items. Never reads docs/ or chat_history.json.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import approval_view as av  # noqa: E402
from provenance import EVIDENCE_NOTE, REQUEST_LABELS  # noqa: E402

INJECTION = '<img src=x onerror=alert(1)>.md'

ITEM = {
    "name": "pwned.md", "content": "x",
    "provenance": {"tool": "save_note", "target": "pwned.md", "files_read": ["ideas.md"],
                   "files_retrieved": ["trip.md"], "files_listed": True,
                   "files_named_in_answer": ["ideas.md"], "request_intent": "read_only",
                   "note": EVIDENCE_NOTE},
    "warnings": [{"code": "not_mentioned_in_answer", "message": "The answer never mentions this proposal."},
                 {"code": "request_no_change", "message": "The request said not to change anything."}],
}


class Warnings(unittest.TestCase):
    def test_strongest_first(self):
        self.assertEqual([w["code"] for w in av.warnings_of(ITEM)],
                         ["request_no_change", "not_mentioned_in_answer"])

    def test_box_lists_every_message(self):
        out = av.warnings_html(ITEM)
        self.assertIn("Check before approving", out)
        self.assertLess(out.index("not to change"), out.index("never mentions"))

    def test_absent_empty_or_malformed_gives_nothing(self):
        for item in ({"name": "a.md"}, {"warnings": []}, {"warnings": None}, {"warnings": "oops"},
                     {"warnings": [None, 3, {}]}, None):
            with self.subTest(item=item):
                self.assertEqual(av.warnings_html(item), "")

    def test_target_not_in_request_sits_after_read_only(self):
        item = {"warnings": [{"code": "not_mentioned_in_answer", "message": "a"},
                             {"code": "target_not_in_request", "message": "b"},
                             {"code": "request_read_only", "message": "c"}]}
        self.assertEqual([w["code"] for w in av.warnings_of(item)],
                         ["request_read_only", "target_not_in_request", "not_mentioned_in_answer"])

    def test_unknown_code_still_shown_last(self):
        item = {"warnings": [{"code": "new_kind", "message": "Something new."},
                             {"code": "answer_claims_done", "message": "Claims done."}]}
        self.assertEqual([w["code"] for w in av.warnings_of(item)], ["answer_claims_done", "new_kind"])

    def test_messages_are_escaped(self):
        out = av.warnings_html({"warnings": [{"code": "x", "message": INJECTION}]})
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)


class Provenance(unittest.TestCase):
    def test_rows_use_separate_labels(self):
        rows = dict(av.provenance_rows(ITEM))
        self.assertEqual(rows["Proposed by tool"], "save_note")
        self.assertEqual(rows["Request type"], REQUEST_LABELS["read_only"])
        self.assertEqual(rows["Files read"], "ideas.md")
        self.assertEqual(rows["Files retrieved (search)"], "trip.md")
        self.assertEqual(rows["File names listed"], "yes (names only, no file text)")
        self.assertEqual(rows["Files named in the answer"], "ideas.md")

    def test_note_is_shown(self):
        self.assertIn(EVIDENCE_NOTE.split(".")[0], av.provenance_html(ITEM))

    def test_missing_provenance_gives_nothing(self):
        self.assertEqual(av.provenance_rows({"name": "a.md"}), [])
        self.assertEqual(av.provenance_html({"name": "a.md"}), "")
        self.assertEqual(av.provenance_html(None), "")

    def test_partial_provenance(self):
        rows = dict(av.provenance_rows({"provenance": {"tool": "add_task"}}))
        self.assertEqual(rows["Files read"], "none")
        self.assertEqual(rows["File names listed"], "not recorded")
        self.assertEqual(rows["Request type"], "not recorded")
        self.assertIn(EVIDENCE_NOTE.split(".")[0], av.provenance_html({"provenance": {"tool": "add_task"}}))

    def test_file_names_are_escaped(self):
        item = {"provenance": {"tool": INJECTION, "files_read": [INJECTION], "note": INJECTION}}
        out = av.provenance_html(item)
        self.assertNotIn("<img", out)

    def test_helpers_do_not_change_the_item(self):
        import copy
        before = copy.deepcopy(ITEM)
        av.warnings_html(ITEM)
        av.provenance_html(ITEM)
        self.assertEqual(ITEM, before)


class RendersInStreamlit(unittest.TestCase):
    """The same calls app.py makes, run headless: a warned item opens its provenance; an old item shows none."""

    def test_render(self):
        from streamlit.testing.v1 import AppTest

        def script(root, items):
            import sys
            sys.path.insert(0, root)
            import streamlit as st
            import approval_view
            for w in items:
                box = approval_view.warnings_html(w)
                if box:
                    st.markdown(box, unsafe_allow_html=True)
                seen = approval_view.provenance_html(w)
                if seen:
                    with st.expander("What the agent saw before this proposal", expanded=bool(box)):
                        st.markdown(seen, unsafe_allow_html=True)

        root = str(Path(__file__).resolve().parent.parent)
        at = AppTest.from_function(script, args=(root, [ITEM, {"name": "old.md", "content": "y"}])).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(len(at.expander), 1)
        self.assertTrue(any("Check before approving" in m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
