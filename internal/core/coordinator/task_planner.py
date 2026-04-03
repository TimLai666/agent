from __future__ import annotations

from internal.core.agents.agent_types import SpawnWorkerInput
from internal.core.coordinator.coordinator_loop import CoordinatorPlan, CoordinatorTurnContext


def make_basic_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
    return CoordinatorPlan(
        type="spawn-worker",
        workerSpec=SpawnWorkerInput(
            agentType="general-purpose",
            title="worker-task",
            originalUserRequest=ctx.userRequest,
            instruction=ctx.userRequest,
            runInBackground=False,
        ),
    )
