import os
import tempfile
import unittest

from agent.toolchain import run_repo_verification


class RepoVerificationTests(unittest.TestCase):
    def test_build_only_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_verification(
                repo_dir=tmp,
                build_cmd="printf build-ok",
                test_cmd=None,
                timeout_sec=5,
            )
            self.assertTrue(result.success)
            self.assertEqual(result.stage, "build")
            self.assertFalse(result.timed_out)
            self.assertIn("build-ok", result.output)

    def test_test_stage_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "marker.txt")
            with open(marker, "w") as f:
                f.write("ok")
            result = run_repo_verification(
                repo_dir=tmp,
                build_cmd="test -f marker.txt",
                test_cmd="false",
                timeout_sec=5,
            )
            self.assertFalse(result.success)
            self.assertEqual(result.stage, "test")
            self.assertFalse(result.timed_out)


if __name__ == "__main__":
    unittest.main()
