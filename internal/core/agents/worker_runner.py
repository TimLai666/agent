from __future__ import annotations

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
            self._task_store.fail_task(task.id, str(exc))
        return self._task_store.get_task(task.id) or task

    async def run_existing_task_once(self, task_id: str, instruction: str) -> WorkerResult:
        self._task_store.start_task(task_id)
        return await self._runner.run(task_id, instruction)
