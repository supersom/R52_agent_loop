from dataclasses import dataclass
from typing import Literal

from agent.prompting import (
    build_compile_failure_full_source_prompt,
    build_compile_failure_edit_issue,
    build_edit_apply_fallback_full_source_prompt,
    build_edit_apply_issue_prompt,
    build_edit_retry_prompt,
    build_output_mismatch_full_source_prompt,
    build_output_mismatch_edit_issue,
    build_source_validation_issue_prompt,
    build_verification_failure_full_source_prompt,
    build_verification_failure_issue,
    build_timeout_full_source_prompt,
    build_timeout_edit_issue,
)

ResponseMode = Literal["full_source", "edits"]
RetryOutcome = Literal[
    "edit_apply_failed",
    "source_validation_failed",
    "compile_failed",
    "verification_failed",
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
    incremental_strict: bool = False,
    current_source: str,
    expected_output: str,
    board_name: str,
    compile_error: str | None = None,
    verification_error: str | None = None,
    verification_stage: str | None = None,
    verification_timed_out: bool = False,
    run_output: str | None = None,
    validation_error: str | None = None,
    edit_apply_error: str | None = None,
    last_attempt_feedback: str = "",
) -> RetryDecision:
    if outcome == "edit_apply_failed":
        if not edit_apply_error:
            raise ValueError("edit_apply_error is required for edit_apply_failed")
        edit_apply_issue = build_edit_apply_issue_prompt(edit_apply_error, last_attempt_feedback)
        if any(
            token in edit_apply_error
            for token in ("not found in current source", "matched", "out of range")
        ):
            if incremental and incremental_strict:
                return RetryDecision(
                    next_prompt=build_edit_retry_prompt(
                        current_source,
                        edit_apply_issue
                        + "Strict incremental mode is enabled. Stay in JSON edits mode and "
                        "provide corrected, unambiguous edit instructions for the current source.",
                    ),
                    next_mode="edits",
                    note="Strict incremental mode: keeping next retry in edits mode despite edit/source mismatch.",
                )
            return RetryDecision(
                next_prompt=build_edit_apply_fallback_full_source_prompt(current_source, edit_apply_issue),
                next_mode="full_source",
                note="Switching next retry to full source mode due to edit/source mismatch.",
            )
        return RetryDecision(
            next_prompt=build_edit_retry_prompt(
                current_source,
                edit_apply_issue + "Return valid JSON edit instructions against the current `agent_code.s`.",
            ),
            next_mode="edits",
        )

    if outcome == "source_validation_failed":
        if not validation_error:
            raise ValueError("validation_error is required for source_validation_failed")
        validation_issue = build_source_validation_issue_prompt(validation_error)
        if current_mode == "edits":
            return RetryDecision(
                next_prompt=build_edit_retry_prompt(current_source, validation_issue),
                next_mode="edits",
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
                next_prompt=build_edit_retry_prompt(
                    current_source,
                    build_compile_failure_edit_issue(compile_error),
                ),
                next_mode="edits",
            )
        return RetryDecision(
            next_prompt=build_compile_failure_full_source_prompt(compile_error),
            next_mode="full_source",
        )

    if outcome == "verification_failed":
        if verification_error is None:
            raise ValueError("verification_error is required for verification_failed")
        if incremental:
            return RetryDecision(
                next_prompt=build_edit_retry_prompt(
                    current_source,
                    build_verification_failure_issue(
                        verification_stage,
                        verification_error,
                        verification_timed_out,
                    ),
                ),
                next_mode="edits",
            )
        return RetryDecision(
            next_prompt=build_verification_failure_full_source_prompt(
                verification_stage,
                verification_error,
                verification_timed_out,
            ),
            next_mode="full_source",
        )

    if outcome == "run_timed_out":
        if run_output is None:
            raise ValueError("run_output is required for run_timed_out")
        if incremental:
            return RetryDecision(
                next_prompt=build_edit_retry_prompt(
                    current_source,
                    build_timeout_edit_issue(board_name, run_output),
                ),
                next_mode="edits",
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
                next_prompt=build_edit_retry_prompt(
                    current_source,
                    build_output_mismatch_edit_issue(expected_output, run_output),
                ),
                next_mode="edits",
            )
        return RetryDecision(
            next_prompt=build_output_mismatch_full_source_prompt(expected_output, run_output),
            next_mode="full_source",
        )

    raise ValueError(f"Unsupported retry outcome: {outcome}")
