import unittest

from agent.retry_policy import decide_next_retry


class RetryPolicyTests(unittest.TestCase):
    def _kwargs(self, **overrides):
        kwargs = {
            "current_mode": "full_source",
            "incremental": False,
            "incremental_strict": False,
            "current_source": ".text\n_start:\n  b .\n",
            "expected_output": "FIB: 5",
            "board_name": "FVP_Corstone_SSE-300_Ethos-U55",
        }
        kwargs.update(overrides)
        return kwargs

    def test_edit_source_mismatch_switches_to_full_source(self):
        decision = decide_next_retry(
            outcome="edit_apply_failed",
            edit_apply_error="Edit #1: 'old' snippet not found in current source",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "full_source")
        self.assertIn("do NOT return JSON edits", decision.next_prompt)
        self.assertIn("edit/source mismatch", decision.note or "")

    def test_edit_apply_non_context_error_stays_edit_mode(self):
        decision = decide_next_retry(
            outcome="edit_apply_failed",
            edit_apply_error="Response is not valid JSON edit instructions",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "edits")
        self.assertIn("Return ONLY JSON", decision.next_prompt)

    def test_edit_source_mismatch_with_strict_stays_edit_mode(self):
        decision = decide_next_retry(
            outcome="edit_apply_failed",
            edit_apply_error="Edit #1: 'old' snippet not found in current source",
            **self._kwargs(incremental=True, incremental_strict=True),
        )
        self.assertEqual(decision.next_mode, "edits")
        self.assertIn("Strict incremental mode is enabled", decision.next_prompt)
        self.assertIn("Strict incremental mode", decision.note or "")

    def test_source_validation_failure_in_edit_mode_stays_edit_mode(self):
        decision = decide_next_retry(
            outcome="source_validation_failed",
            validation_error="Line 1 looks like prose/log output",
            **self._kwargs(current_mode="edits"),
        )
        self.assertEqual(decision.next_mode, "edits")
        self.assertIn("Return ONLY JSON", decision.next_prompt)

    def test_compile_failed_non_incremental_uses_full_source(self):
        decision = decide_next_retry(
            outcome="compile_failed",
            compile_error="error: unknown directive",
            **self._kwargs(),
        )
        self.assertEqual(decision.next_mode, "full_source")
        self.assertIn("failed to compile", decision.next_prompt)

    def test_run_output_mismatch_incremental_uses_edits(self):
        decision = decide_next_retry(
            outcome="run_output_mismatch",
            run_output="FIB: 8",
            **self._kwargs(incremental=True),
        )
        self.assertEqual(decision.next_mode, "edits")
        self.assertIn("expected output was not found", decision.next_prompt)
        self.assertIn("Return ONLY JSON", decision.next_prompt)


if __name__ == "__main__":
    unittest.main()
