from __future__ import annotations

from internal.core.tasks.task_types import CompletionDecision, TaskKind, VerificationResult, WorkerResult


def needs_verification(input_data: dict[str, object]) -> bool:
    task_kind = input_data.get("taskKind")
    files_changed = input_data.get("filesChanged") or []
    commands_executed = input_data.get("commandsExecuted") or []

    if task_kind in {"implementation", "bugfix", "infra"}:
        return True
    if isinstance(files_changed, list) and len(files_changed) >= 3:
        return True
    if isinstance(files_changed, list) and isinstance(commands_executed, list):
        if commands_executed and files_changed:
            return True
    return False


def decide_completion(
    worker: WorkerResult,
    verification: VerificationResult | None = None,
    task_kind: TaskKind | None = None,
) -> CompletionDecision:
    if worker.status != "completed":
        return CompletionDecision(
            done=False,
            reason="worker did not complete successfully",
            nextAction="retry-worker",
        )

    if worker.unresolvedIssues:
        return CompletionDecision(
            done=False,
            reason="worker reported unresolved issues",
            nextAction="retry-worker",
        )

    inferred_task_kind: TaskKind = task_kind or ("implementation" if worker.filesChanged else "research")
    verification_required = needs_verification(
        {
            "taskKind": inferred_task_kind,
            "filesChanged": worker.filesChanged,
            "commandsExecuted": worker.commandsExecuted,
        }
    )

    if verification_required and not verification:
        return CompletionDecision(
            done=False,
            reason="verification required before completion",
            nextAction="run-verification",
        )

    if verification:
        if verification.verdict == "FAIL":
            return CompletionDecision(
                done=False,
                reason="verification failed",
                nextAction="retry-worker",
            )
        if verification.verdict == "PARTIAL":
            return CompletionDecision(
                done=False,
                reason="verification only partially passed",
                nextAction="retry-worker",
            )

    return CompletionDecision(
        done=True,
        reason="task completed and verification passed",
        nextAction="finalize",
    )
