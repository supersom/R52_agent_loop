import os
import tempfile
import unittest

from agent.repo_context import build_repo_attempt_context


class RepoContextTests(unittest.TestCase):
    def test_selects_entry_file_and_related_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "tests"), exist_ok=True)
            with open(os.path.join(tmp, "src", "app.py"), "w") as f:
                f.write("def run():\n    return 1\n")
            with open(os.path.join(tmp, "src", "checksum.py"), "w") as f:
                f.write("def checksum(x):\n    return x\n")
            with open(os.path.join(tmp, "tests", "test_app.py"), "w") as f:
                f.write("def test_run():\n    assert True\n")

            context, selected = build_repo_attempt_context(
                repo_dir=tmp,
                entry_file_rel="src/app.py",
                query_text="fix checksum in app and tests",
                max_files=3,
            )

            self.assertIn("Entry file: src/app.py", context)
            self.assertIn("src/app.py", selected)
            self.assertLessEqual(len(selected), 3)

    def test_respects_total_char_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "agent_code.s"), "w") as f:
                f.write("A" * 5000)

            context, selected = build_repo_attempt_context(
                repo_dir=tmp,
                entry_file_rel="agent_code.s",
                query_text="update output",
                max_files=3,
                max_file_chars=4000,
                max_total_chars=1200,
            )

            self.assertIn("agent_code.s", selected)
            self.assertLessEqual(len(context), 1200 + 2000)

    def test_ignores_agent_internal_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".agent_loop"), exist_ok=True)
            with open(os.path.join(tmp, ".agent_loop", "run_history.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmp, "agent_code.s"), "w") as f:
                f.write(".cpu cortex-r52\n")

            context, _ = build_repo_attempt_context(
                repo_dir=tmp,
                entry_file_rel="agent_code.s",
                query_text="fix compile",
            )

            self.assertNotIn(".agent_loop/run_history.json", context)


if __name__ == "__main__":
    unittest.main()
