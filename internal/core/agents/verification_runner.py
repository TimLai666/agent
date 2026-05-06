from __future__ import annotations

from collections.abc import Awaitable, Callable

from internal.core.agents.agent_types import SpawnVerificationInput
from internal.core.protocol.verdict_parser import parse_verification_verdict
from internal.core.tasks.task_types import VerificationResult


class VerificationRunner:
    def __init__(self, run_callable: Callable[[str], Awaitable[str]]) -> None:
        self._run_callable = run_callable

    async def run(self, task_id: str, input_data: SpawnVerificationInput) -> VerificationResult:
        prompt = self._build_prompt(input_data)
        output = await self._run_callable(prompt)
        return parse_verification_verdict(output, task_id=task_id)

    def _build_prompt(self, input_data: SpawnVerificationInput) -> str:
        worker = input_data.workerResult
        files = worker.filesChanged or []
        commands = worker.commandsExecuted or []
        return (
            "ORIGINAL USER REQUEST:\n"
            f"{input_data.originalUserRequest}\n\n"
            "WORKER SUMMARY:\n"
            f"{worker.summary or ''}\n\n"
            "FILES CHANGED:\n"
            + ("\n".join(files) if files else "(none reported)")
            + "\n\n"
            "COMMANDS ALREADY RUN:\n"
            + ("\n".join(commands) if commands else "(none reported)")
            + "\n\n"
            "CLAIMS TO VERIFY:\n"
            + (worker.result or "(no result text provided)")
        )
