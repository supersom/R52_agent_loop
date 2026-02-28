import unittest

from agent.edits import apply_edit_instructions, parse_edit_instructions


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


if __name__ == "__main__":
    unittest.main()
