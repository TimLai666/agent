from __future__ import annotations

import time

from internal.core.tasks.task_types import TaskRecord, TaskStatus, TaskUsage


class TaskStateError(RuntimeError):
    pass


def create_pending(task: TaskRecord) -> TaskRecord:
    task.status = "pending"
    return task


def start_task(task: TaskRecord) -> TaskRecord:
    if task.status != "pending":
        raise TaskStateError(f"start_task expects pending, got {task.status}")
    task.status = "running"
    task.startedAt = int(time.time() * 1000)
    return task


def complete_task(
    task: TaskRecord,
    *,
    final_text: str,
    summary: str,
    files_changed: list[str],
    commands_executed: list[str],
    usage: TaskUsage | None,
    evidence: list[str],
    unresolved_issues: list[str],
) -> TaskRecord:
    if task.status != "running":
        raise TaskStateError(f"complete_task expects running, got {task.status}")
    task.status = "completed"
    task.finishedAt = int(time.time() * 1000)
    task.finalTextResponse = final_text
    task.summary = summary
    task.filesChanged = list(files_changed)
    task.commandsExecuted = list(commands_executed)
    task.usage = usage
    task.evidence = list(evidence)
    task.unresolvedIssues = list(unresolved_issues)
    return task


def fail_task(task: TaskRecord, error: str) -> TaskRecord:
    if task.status != "running":
        raise TaskStateError(f"fail_task expects running, got {task.status}")
    task.status = "failed"
    task.finishedAt = int(time.time() * 1000)
    task.error = error
    task.summary = error
    return task


def kill_task(task: TaskRecord) -> TaskRecord:
    if task.status not in {"pending", "running"}:
        raise TaskStateError(f"kill_task expects pending/running, got {task.status}")
    task.status = "killed"
    task.finishedAt = int(time.time() * 1000)
    task.summary = "Task killed"
    return task


def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    allowed = {
        "pending": {"running", "killed"},
        "running": {"completed", "failed", "killed"},
        "completed": set(),
        "failed": set(),
        "killed": set(),
    }
    return to_status in allowed[from_status]
