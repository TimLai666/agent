from __future__ import annotations

import time
import uuid
from dataclasses import replace
from threading import RLock
from typing import Callable

from internal.core.protocol.task_notification import to_task_notification_xml
from internal.core.tasks.task_state_machine import complete_task, create_pending, fail_task, kill_task, start_task
from internal.core.tasks.task_types import AgentType, TaskRecord, TaskUsage, WorkerResult


class TaskStore:
    def __init__(self, enqueue_notification: Callable[[str], None] | None = None) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = RLock()
        self._enqueue_notification = enqueue_notification

    def create_task(
        self,
        *,
        agent_type: AgentType,
        title: str,
        original_user_request: str,
        worker_instruction: str,
        run_in_background: bool,
        parent_task_id: str | None = None,
        model: str | None = None,
    ) -> TaskRecord:
        now = int(time.time() * 1000)
        task = TaskRecord(
            id=str(uuid.uuid4()),
            parentTaskId=parent_task_id,
            agentType=agent_type,
            status="pending",
            title=title,
            originalUserRequest=original_user_request,
            workerInstruction=worker_instruction,
            createdAt=now,
            runInBackground=run_in_background,
            model=model,
        )
        create_pending(task)
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks.values())

    def list_background_incomplete(self) -> list[TaskRecord]:
        with self._lock:
            return [
                task
                for task in self._tasks.values()
                if task.runInBackground and task.status in {"pending", "running"}
            ]

    def start_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            start_task(task)
            return task

    def complete_task(
        self,
        task_id: str,
        *,
        final_text: str,
        summary: str,
        files_changed: list[str],
        commands_executed: list[str],
        evidence: list[str],
        unresolved_issues: list[str],
        usage: TaskUsage | None = None,
        tool_use_id: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            complete_task(
                task,
                final_text=final_text,
                summary=summary,
                files_changed=files_changed,
                commands_executed=commands_executed,
                usage=usage,
                evidence=evidence,
                unresolved_issues=unresolved_issues,
            )
            worker = WorkerResult(
                taskId=task.id,
                status="completed",
                summary=task.summary or "",
                result=task.finalTextResponse or "",
                filesChanged=task.filesChanged,
                commandsExecuted=task.commandsExecuted,
                evidence=task.evidence,
                unresolvedIssues=task.unresolvedIssues,
                usage=task.usage,
            )
            if self._enqueue_notification:
                self._enqueue_notification(to_task_notification_xml(worker, tool_use_id=tool_use_id))
            return task

    def fail_task(self, task_id: str, error: str) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            fail_task(task, error)
            if self._enqueue_notification:
                worker = WorkerResult(
                    taskId=task.id,
                    status="failed",
                    summary=task.summary or error,
                    result=task.finalTextResponse or "",
                    filesChanged=task.filesChanged,
                    commandsExecuted=task.commandsExecuted,
                    evidence=task.evidence,
                    unresolvedIssues=task.unresolvedIssues,
                    usage=task.usage,
                )
                self._enqueue_notification(to_task_notification_xml(worker))
            return task

    def kill_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            kill_task(task)
            if self._enqueue_notification:
                worker = WorkerResult(
                    taskId=task.id,
                    status="killed",
                    summary=task.summary or "Task killed",
                    result=task.finalTextResponse or "",
                    filesChanged=task.filesChanged,
                    commandsExecuted=task.commandsExecuted,
                    evidence=task.evidence,
                    unresolvedIssues=task.unresolvedIssues,
                    usage=task.usage,
                )
                self._enqueue_notification(to_task_notification_xml(worker))
            return task

    def update_task(self, task_id: str, **kwargs: object) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            updated = replace(task, **kwargs)
            self._tasks[task_id] = updated
            return updated
