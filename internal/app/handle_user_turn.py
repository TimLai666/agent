from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Callable

from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.core.agents.agent_types import SpawnVerificationInput, SpawnWorkerInput
from internal.core.coordinator.coordinator_loop import CoordinatorPlan, CoordinatorTurnContext
from internal.core.tasks.task_types import VerificationResult, WorkerResult


@dataclass
class OrchestrationRuntime:
    main_agent: object
    on_todo_update: Callable[[str], None] | None = None

    def _build_planning_instruction(self, user_request: str) -> str:
        return self.main_agent._build_planning_instruction(user_request)

    async def handle_user_turn(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        return await self.main_agent.coordinator_handle_user_turn(
            user_prompt,
            message_history=message_history,
            on_todo_update=self.on_todo_update,
        )

    async def handle_user_turn_stream(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> AsyncIterator[str]:
        task = asyncio.create_task(
            self.handle_user_turn(user_prompt, message_history=message_history)
        )
        while not task.done():
            await asyncio.sleep(2)

        result = await task
        if result:
            yield result

    async def _make_or_update_plan(self, ctx: CoordinatorTurnContext) -> CoordinatorPlan:
        return await self.main_agent._coordinator_make_or_update_plan(ctx)

    async def _spawn_worker(self, spec: SpawnWorkerInput) -> WorkerResult:
        return await self.main_agent._coordinator_spawn_worker(spec)

    def _find_task_notification(self, task_id: str) -> str | None:
        return self.main_agent._coordinator_find_task_notification(task_id)

    async def _spawn_verification(self, input_data: SpawnVerificationInput) -> VerificationResult:
        return await self.main_agent._coordinator_spawn_verification(input_data)

    def _augment_context_with_failure(
        self,
        ctx: CoordinatorTurnContext,
        worker: WorkerResult,
        verification: VerificationResult | None,
    ) -> CoordinatorTurnContext:
        return self.main_agent._coordinator_augment_context_with_failure(
            ctx,
            worker,
            verification,
        )

    def _infer_task_kind(self, prompt: str) -> str:
        return self.main_agent._coordinator_infer_task_kind(prompt)

    def _looks_like_direct_question(self, prompt: str) -> bool:
        return self.main_agent._coordinator_looks_like_direct_question(prompt)

    def _should_run_background(self, prompt: str) -> bool:
        return self.main_agent._coordinator_should_run_background(prompt)


def create_runtime(
    main_agent: object,
    on_todo_update: Callable[[str], None] | None = None,
) -> OrchestrationRuntime:
    fork_runtime = getattr(main_agent, "fork_coordinator_runtime", None)
    if callable(fork_runtime):
        runtime = fork_runtime(on_todo_update=on_todo_update)
        if isinstance(runtime, OrchestrationRuntime):
            return runtime
    return OrchestrationRuntime(main_agent=main_agent, on_todo_update=on_todo_update)


async def handle_user_turn(
    user_prompt: str,
    main_agent: object,
    message_history: list[ModelRequest | ModelResponse] | None = None,
) -> str:
    runtime = create_runtime(main_agent)
    return await runtime.handle_user_turn(user_prompt, message_history=message_history)
