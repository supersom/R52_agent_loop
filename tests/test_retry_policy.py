import unittest

from agent.retry_policy import decide_next_retry


class RetryPolicyTests(unittest.TestCase):
    def _kwargs(self, **overrides):
        kwargs = {
            "current_mode": "full_source",
            "incremental": False,
            "current_source": ".text\n_start:\n  b .\n",
            "expected_output": "FIB: 5",
            "board_name": "FVP_Corstone_SSE-300_Ethos-U55",
        }
        kwargs.update(overrides)
        return kwargs

    def test_patch_context_mismatch_switches_to_full_source(self):
        decision = decide_next_retry(
            outcome="patch_apply_failed",
            patch_apply_error="Patch context does not match current source",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "full_source")
        self.assertIn("do NOT return a patch", decision.next_prompt)
        self.assertIn("patch context mismatch", decision.note or "")

    def test_patch_apply_non_context_error_stays_patch_mode(self):
        decision = decide_next_retry(
            outcome="patch_apply_failed",
            patch_apply_error="Unsupported patch line prefix: C",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "patch")
        self.assertIn("Return ONLY a unified diff patch", decision.next_prompt)

    def test_source_validation_failure_in_patch_mode_stays_patch_mode(self):
        decision = decide_next_retry(
            outcome="source_validation_failed",
            validation_error="Line 1 looks like prose/log output",
            **self._kwargs(current_mode="patch"),
        )
        self.assertEqual(decision.next_mode, "patch")
        self.assertIn("Return ONLY a unified diff patch", decision.next_prompt)

    def test_compile_failed_non_incremental_uses_full_source(self):
        decision = decide_next_retry(
            outcome="compile_failed",
            compile_error="error: unknown directive",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "full_source")
        self.assertIn("failed to compile", decision.next_prompt)

    def test_run_output_mismatch_incremental_uses_patch(self):
        decision = decide_next_retry(
            outcome="run_output_mismatch",
            run_output="FIB: 8",
            **self._kwargs(incremental=True),
        )
        self.assertEqual(decision.next_mode, "patch")
        self.assertIn("expected output was not found", decision.next_prompt)
        self.assertIn("Return ONLY a unified diff patch", decision.next_prompt)


if __name__ == "__main__":
    unittest.main()
