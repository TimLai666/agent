from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from internal.core.agents.agent_types import SpawnVerificationInput, SpawnWorkerInput
from internal.core.tasks.completion_gate import decide_completion
from internal.core.tasks.task_types import TaskKind, VerificationResult, WorkerResult


@dataclass
class CoordinatorTurnContext:
    userRequest: str
    taskKind: TaskKind = "research"


@dataclass
class CoordinatorPlan:
    type: str
    finalAnswer: str = ""
    workerSpec: SpawnWorkerInput | None = None


async def run_coordinator_turn(
    ctx: CoordinatorTurnContext,
    *,
    make_or_update_plan: Callable[[CoordinatorTurnContext], Awaitable[CoordinatorPlan]],
    spawn_worker: Callable[[SpawnWorkerInput], Awaitable[WorkerResult]],
    spawn_verification_worker: Callable[[SpawnVerificationInput], Awaitable[VerificationResult]],
    synthesize_final_answer: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], str],
    augment_context_with_failure: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], CoordinatorTurnContext],
) -> str:
    while True:
        plan = await make_or_update_plan(ctx)

        if plan.type == "answer-directly":
            return plan.finalAnswer

        if plan.type == "spawn-worker" and plan.workerSpec is not None:
            worker_result = await spawn_worker(plan.workerSpec)
            decision1 = decide_completion(worker_result, task_kind=ctx.taskKind)

            if decision1.nextAction == "run-verification":
                verification_result = await spawn_verification_worker(
                    SpawnVerificationInput(
                        originalUserRequest=ctx.userRequest,
                        workerResult=worker_result,
                        filesChanged=worker_result.filesChanged,
                    )
                )
                decision2 = decide_completion(worker_result, verification_result, task_kind=ctx.taskKind)
                if decision2.done:
                    return synthesize_final_answer(ctx, worker_result, verification_result)
                ctx = augment_context_with_failure(ctx, worker_result, verification_result)
                continue

            if decision1.done:
                return synthesize_final_answer(ctx, worker_result, None)

            ctx = augment_context_with_failure(ctx, worker_result, None)
            continue

        return "無法產生可執行計畫。"
