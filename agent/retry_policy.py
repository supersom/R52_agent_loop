from dataclasses import dataclass
from typing import Literal

from agent.prompting import (
    build_compile_failure_full_source_prompt,
    build_compile_failure_patch_issue,
    build_output_mismatch_full_source_prompt,
    build_output_mismatch_patch_issue,
    build_patch_apply_issue_prompt,
    build_patch_context_mismatch_full_source_prompt,
    build_patch_retry_prompt,
    build_source_validation_issue_prompt,
    build_timeout_full_source_prompt,
    build_timeout_patch_issue,
)

ResponseMode = Literal["full_source", "patch"]
RetryOutcome = Literal[
    "patch_apply_failed",
    "source_validation_failed",
    "compile_failed",
    "run_timed_out",
    "run_output_mismatch",
    "run_failed",
]


@dataclass(frozen=True)
class RetryDecision:
    next_prompt: str
    next_mode: ResponseMode
    note: str | None = None


def decide_next_retry(
    *,
    outcome: RetryOutcome,
    current_mode: ResponseMode,
    incremental: bool,
    current_source: str,
    expected_output: str,
    board_name: str,
    compile_error: str | None = None,
    run_output: str | None = None,
    validation_error: str | None = None,
    patch_apply_error: str | None = None,
    last_attempt_feedback: str = "",
) -> RetryDecision:
    if outcome == "patch_apply_failed":
        if not patch_apply_error:
            raise ValueError("patch_apply_error is required for patch_apply_failed")
        patch_apply_issue = build_patch_apply_issue_prompt(patch_apply_error, last_attempt_feedback)
        if "Patch context does not match current source" in patch_apply_error:
            return RetryDecision(
                next_prompt=build_patch_context_mismatch_full_source_prompt(current_source, patch_apply_issue),
                next_mode="full_source",
                note="Switching next retry to full source mode due to patch context mismatch.",
            )
        return RetryDecision(
            next_prompt=build_patch_retry_prompt(
                current_source,
                patch_apply_issue + "Return a valid unified diff patch against the current `agent_code.s`.",
            ),
            next_mode="patch",
        )

    if outcome == "source_validation_failed":
        if not validation_error:
            raise ValueError("validation_error is required for source_validation_failed")
        validation_issue = build_source_validation_issue_prompt(validation_error)
        if current_mode == "patch":
            return RetryDecision(
                next_prompt=build_patch_retry_prompt(current_source, validation_issue),
                next_mode="patch",
            )
        return RetryDecision(
            next_prompt=validation_issue,
            next_mode="full_source",
        )

    if outcome == "compile_failed":
        if not compile_error:
            raise ValueError("compile_error is required for compile_failed")
        if incremental:
            return RetryDecision(
                next_prompt=build_patch_retry_prompt(
                    current_source,
                    build_compile_failure_patch_issue(compile_error),
                ),
                next_mode="patch",
            )
        return RetryDecision(
            next_prompt=build_compile_failure_full_source_prompt(compile_error),
            next_mode="full_source",
        )

    if outcome == "run_timed_out":
        if run_output is None:
            raise ValueError("run_output is required for run_timed_out")
        if incremental:
            return RetryDecision(
                next_prompt=build_patch_retry_prompt(
                    current_source,
                    build_timeout_patch_issue(board_name, run_output),
                ),
                next_mode="patch",
            )
        return RetryDecision(
            next_prompt=build_timeout_full_source_prompt(board_name, run_output),
            next_mode="full_source",
        )

    if outcome in ("run_output_mismatch", "run_failed"):
        if run_output is None:
            raise ValueError("run_output is required for run_output_mismatch/run_failed")
        if incremental:
            return RetryDecision(
                next_prompt=build_patch_retry_prompt(
                    current_source,
                    build_output_mismatch_patch_issue(expected_output, run_output),
                ),
                next_mode="patch",
            )
        return RetryDecision(
            next_prompt=build_output_mismatch_full_source_prompt(expected_output, run_output),
            next_mode="full_source",
        )

    raise ValueError(f"Unsupported retry outcome: {outcome}")
