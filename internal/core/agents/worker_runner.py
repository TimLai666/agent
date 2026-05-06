from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from internal.core.agents.agent_runner import AgentRunner
from internal.core.agents.agent_types import SpawnWorkerInput
from internal.core.tasks.task_store import TaskStore
from internal.core.tasks.task_types import TaskRecord, WorkerResult


class WorkerRunner:
    def __init__(
        self,
        task_store: TaskStore,
        run_callable: Callable[[str], Awaitable[str]],
    ) -> None:
        self._task_store = task_store
        self._runner = AgentRunner(run_callable)
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def spawn_worker(self, input_data: SpawnWorkerInput) -> TaskRecord:
        task = self._task_store.create_task(
            agent_type=input_data.agentType,
            title=input_data.title,
            original_user_request=input_data.originalUserRequest,
            worker_instruction=input_data.instruction,
            run_in_background=input_data.runInBackground,
            model=input_data.model,
        )
        if input_data.runInBackground:
            # Actually schedule the background task instead of returning a
            # never-started record — otherwise the caller has no way to ever
            # observe its completion.
            t = asyncio.create_task(self._run_background(task.id, input_data.instruction))
            self._background_tasks.add(t)
            t.add_done_callback(self._background_tasks.discard)
            return task

        self._task_store.start_task(task.id)
        try:
            result = await self._runner.run(task.id, input_data.instruction)
            self._task_store.complete_task(
                task.id,
                final_text=result.result,
                summary=result.summary,
                files_changed=result.filesChanged,
                commands_executed=result.commandsExecuted,
                evidence=result.evidence,
                unresolved_issues=result.unresolvedIssues,
                usage=result.usage,
            )
        except Exception as exc:
            try:
                self._task_store.fail_task(task.id, str(exc))
            except Exception:
                # Never let a failure in fail_task mask the original exception.
                pass
        return self._task_store.get_task(task.id) or task

    async def _run_background(self, task_id: str, instruction: str) -> None:
        self._task_store.start_task(task_id)
        try:
            result = await self._runner.run(task_id, instruction)
            self._task_store.complete_task(
                task_id,
                final_text=result.result,
                summary=result.summary,
                files_changed=result.filesChanged,
                commands_executed=result.commandsExecuted,
                evidence=result.evidence,
                unresolved_issues=result.unresolvedIssues,
                usage=result.usage,
            )
        except Exception as exc:
            try:
                self._task_store.fail_task(task_id, str(exc))
            except Exception:
                pass

    async def run_existing_task_once(self, task_id: str, instruction: str) -> WorkerResult:
        self._task_store.start_task(task_id)
        try:
            result = await self._runner.run(task_id, instruction)
        except Exception as exc:
            # Ensure the task is finalised even on failure so it doesn't get
            # stuck in the `running` state and block subsequent transitions.
            try:
                self._task_store.fail_task(task_id, str(exc))
            except Exception:
                # Best-effort finalisation; never mask the real error.
                pass
            raise
        self._task_store.complete_task(
            task_id,
            final_text=result.result,
            summary=result.summary,
            files_changed=result.filesChanged,
            commands_executed=result.commandsExecuted,
            evidence=result.evidence,
            unresolved_issues=result.unresolvedIssues,
            usage=result.usage,
        )
        return result
