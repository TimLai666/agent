from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

from internal.core.tasks.task_types import TaskUsage, WorkerResult


_FILES_PATTERN = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|json|md|yml|yaml|toml|ini|cfg)\b")
_COMMAND_PATTERN = re.compile(r"^\s*(?:\$\s*)?(uv|python|pytest|npm|pnpm|yarn|make|git)\b.*$", re.IGNORECASE)
_EVIDENCE_PATTERN = re.compile(r"^\s*(?:[-*]\s+)?\$\s+(.+)$")
_UNRESOLVED_PATTERN = re.compile(r"\b(?:UNRESOLVED|TODO|FIXME|XXX|NOT[\s_-]?RUN)\b")


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
            commands.append(re.sub(r"^\s*\$\s*", "", line.strip()))
    return commands


def _extract_unresolved_issues(text: str) -> list[str]:
    issues: list[str] = []
    for line in text.splitlines():
        if _UNRESOLVED_PATTERN.search(line):
            issues.append(line.strip())
    return issues


def _extract_evidence(text: str) -> list[str]:
    evidence: list[str] = []
    for line in text.splitlines():
        match = _EVIDENCE_PATTERN.match(line)
        if match:
            evidence.append("$ " + match.group(1).strip())
    return evidence


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
            evidence=_extract_evidence(output),
            unresolvedIssues=_extract_unresolved_issues(output),
            usage=TaskUsage(durationMs=duration_ms),
        )
