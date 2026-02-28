import os
import tempfile
import unittest

from agent.edits import (
    apply_edit_instructions,
    apply_workspace_edit_instructions,
    parse_edit_instructions,
)


class EditProtocolTests(unittest.TestCase):
    def test_parse_plain_json(self):
        edits, sanitized = parse_edit_instructions(
            '{"edits":[{"op":"replace_snippet","old":"abc","new":"xyz"}]}'
        )
        self.assertFalse(sanitized)
        self.assertEqual(edits[0]["op"], "replace_snippet")

    def test_parse_json_with_wrapper_text(self):
        edits, sanitized = parse_edit_instructions(
            'Here are edits:\n{"edits":[{"op":"append_text","text":"\\n@done"}]}\nthanks'
        )
        self.assertTrue(sanitized)
        self.assertEqual(edits[0]["op"], "append_text")

    def test_replace_snippet_unique(self):
        source = "line1\nline2\n"
        result = apply_edit_instructions(
            source, [{"op": "replace_snippet", "old": "line2", "new": "lineX"}]
        )
        self.assertEqual(result, "line1\nlineX\n")

    def test_replace_snippet_requires_occurrence_when_ambiguous(self):
        source = "x\nx\n"
        with self.assertRaisesRegex(ValueError, "matched 2 locations"):
            apply_edit_instructions(
                source, [{"op": "replace_snippet", "old": "x", "new": "y"}]
            )

    def test_replace_snippet_with_occurrence(self):
        source = "x\nx\n"
        result = apply_edit_instructions(
            source, [{"op": "replace_snippet", "old": "x", "new": "y", "occurrence": 2}]
        )
        self.assertEqual(result, "x\ny\n")

    def test_insert_after(self):
        source = "a\nb\n"
        result = apply_edit_instructions(
            source, [{"op": "insert_after", "anchor": "a\n", "text": "x\n"}]
        )
        self.assertEqual(result, "a\nx\nb\n")

    def test_replace_entire_file(self):
        source = "old"
        result = apply_edit_instructions(
            source, [{"op": "replace_entire_file", "content": "new"}]
        )
        self.assertEqual(result, "new")

    def test_workspace_apply_default_path_for_text_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_file = os.path.join(tmp, "agent_code.s")
            with open(source_file, "w") as f:
                f.write("A\nB\n")

            changed = apply_workspace_edit_instructions(
                tmp,
                [{"op": "replace_snippet", "old": "B", "new": "C"}],
                default_path="agent_code.s",
            )

            self.assertEqual(changed, ["agent_code.s"])
            with open(source_file, "r") as f:
                self.assertEqual(f.read(), "A\nC\n")

    def test_workspace_apply_multifile_text_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            main_file = os.path.join(tmp, "agent_code.s")
            helper_file = os.path.join(tmp, "lib", "helper.s")
            os.makedirs(os.path.dirname(helper_file), exist_ok=True)
            with open(main_file, "w") as f:
                f.write("MAIN\n")
            with open(helper_file, "w") as f:
                f.write("HELPER_OLD\n")

            changed = apply_workspace_edit_instructions(
                tmp,
                [
                    {
                        "op": "replace_snippet",
                        "path": "lib/helper.s",
                        "old": "HELPER_OLD",
                        "new": "HELPER_NEW",
                    }
                ],
                default_path="agent_code.s",
            )

            self.assertEqual(changed, ["lib/helper.s"])
            with open(helper_file, "r") as f:
                self.assertEqual(f.read(), "HELPER_NEW\n")
            with open(main_file, "r") as f:
                self.assertEqual(f.read(), "MAIN\n")

    def test_workspace_create_move_delete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = apply_workspace_edit_instructions(
                tmp,
                [
                    {"op": "create_file", "path": "a.txt", "content": "hello"},
                    {"op": "move_file", "path": "a.txt", "new_path": "nested/b.txt"},
                    {"op": "delete_file", "path": "nested/b.txt"},
                ],
            )

            self.assertEqual(changed, ["a.txt", "nested/b.txt"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "a.txt")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "nested", "b.txt")))

    def test_workspace_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                apply_workspace_edit_instructions(
                    tmp,
                    [{"op": "create_file", "path": "../outside.txt", "content": "nope"}],
                )


if __name__ == "__main__":
    unittest.main()
