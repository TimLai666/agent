from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

from internal.core.tasks.task_types import TaskUsage, WorkerResult


_FILES_PATTERN = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|json|md|yml|yaml|toml|ini|cfg)\b")
_COMMAND_PATTERN = re.compile(r"^\s*(?:\$\s*)?(uv|python|pytest|npm|pnpm|yarn|make|git)\b.*$", re.IGNORECASE)


def _extract_files(text: str) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for match in _FILES_PATTERN.finditer(text):
        value = match.group(0)
        if value not in seen:
            seen.add(value)
            files.append(value)
    return files


def _extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        if _COMMAND_PATTERN.match(line):
            commands.append(line.strip().removeprefix("$ "))
    return commands


def _extract_unresolved_issues(text: str) -> list[str]:
    issues: list[str] = []
    for line in text.splitlines():
        lowered = line.lower()
        if "unresolved" in lowered or "todo" in lowered or "not run" in lowered:
            issues.append(line.strip())
    return issues


class AgentRunner:
    def __init__(self, run_callable: Callable[[str], Awaitable[str]]) -> None:
        self._run_callable = run_callable

    async def run(self, task_id: str, prompt: str) -> WorkerResult:
        started_at = time.time()
        output = await self._run_callable(prompt)
        duration_ms = int((time.time() - started_at) * 1000)
        summary = output.strip().splitlines()[0] if output.strip() else ""

        return WorkerResult(
            taskId=task_id,
            status="completed",
            summary=summary,
            result=output,
            filesChanged=_extract_files(output),
            commandsExecuted=_extract_commands(output),
            evidence=[line.strip() for line in output.splitlines() if line.strip().startswith("$ ")],
            unresolvedIssues=_extract_unresolved_issues(output),
            usage=TaskUsage(durationMs=duration_ms),
        )
