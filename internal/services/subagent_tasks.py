from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Awaitable, Callable, Literal, cast

from internal.core.protocol.task_notification import to_task_notification_xml
from internal.core.protocol.verdict_parser import parse_verification_verdict
from internal.core.tasks.completion_gate import decide_completion
from internal.core.tasks.task_types import TaskUsage, WorkerResult

TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]
TaskIsolation = Literal["none", "worktree", "remote"]
TaskMode = Literal["spawn", "fork"]

_FILES_PATTERN = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|json|md|yml|yaml|toml|ini|cfg)\b")
_COMMAND_PATTERN = re.compile(r"^\s*(?:\$\s*)?(uv|python|pytest|npm|pnpm|yarn|make|git)\b.*$", re.IGNORECASE)
_SECTION_PATTERN = re.compile(r"^\[(RESULT|FILES_CHANGED|COMMANDS|EVIDENCE|UNRESOLVED|NEEDED_INPUT)\]\s*$")
IDLE_WAIT_TIMEOUT_SECONDS = 90
MAX_REPAIR_ATTEMPTS = 3


@dataclass
class BaseTask:
    id: str
    createdAt: int
    updatedAt: int
    status: TaskStatus
    mode: TaskMode
    isolation: TaskIsolation
    coordinatorSessionId: str
    runInBackground: bool
    prompt: str
    pendingMessages: list[str] = field(default_factory=list)
    name: str | None = None
    parentTaskId: str | None = None
    result: str | None = None
    summary: str | None = None
    outputFile: str | None = None
    error: str | None = None
    notified: bool = False
    toolUseCount: int = 0
    totalTokens: int | None = None
    durationMs: int | None = None
    type: str = "local_agent"
    subagentType: str | None = None
    model: str | None = None
    worktreePath: str | None = None
    worktreeBranch: str | None = None
    filesChanged: list[str] = field(default_factory=list)
    commandsExecuted: list[str] = field(default_factory=list)
    verificationNeeded: bool = False
    evidence: list[str] = field(default_factory=list)
    unresolvedIssues: list[str] = field(default_factory=list)
    repairAttempts: int = 0


class TaskRegistry:
    """In-memory task registry with atomic updates."""

    def __init__(self) -> None:
        self._tasks: dict[str, BaseTask] = {}
        self._lock = RLock()

    def createTask(self, task: BaseTask) -> None:
        with self._lock:
            self._tasks[task.id] = task

    def getTask(self, taskId: str) -> BaseTask | None:
        with self._lock:
            return self._tasks.get(taskId)

    def listTasksBySession(self, sessionId: str) -> list[BaseTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.coordinatorSessionId == sessionId]

    def listIncompleteBackgroundTasks(self, sessionId: str) -> list[BaseTask]:
        with self._lock:
            return [
                t
                for t in self._tasks.values()
                if t.coordinatorSessionId == sessionId
                and t.runInBackground
                and t.status in {"pending", "running"}
            ]

    def updateTask(self, taskId: str, updater: Callable[[BaseTask], BaseTask]) -> BaseTask | None:
        with self._lock:
            current = self._tasks.get(taskId)
            if current is None:
                return None
            updated = updater(current)
            updated.updatedAt = int(time.time() * 1000)
            self._tasks[taskId] = updated
            return updated

    def findTaskByName(self, sessionId: str, name: str) -> BaseTask | None:
        with self._lock:
            for task in self._tasks.values():
                if task.coordinatorSessionId == sessionId and task.name == name:
                    return task
        return None


@dataclass
class AgentToolInput:
    prompt: str
    name: str | None = None
    subagent_type: str | None = None
    run_in_background: bool = True
    isolation: TaskIsolation = "none"
    model: str | None = None


@dataclass
class SendMessageToolInput:
    to: str
    message: str


@dataclass
class TaskStopToolInput:
    task_id: str


class SubagentTaskManager:
    """Run and control sub-agent tasks in current process."""

    def __init__(
        self,
        worker: Callable[[BaseTask, str], Awaitable[str]],
        enqueue_notification: Callable[[str], None],
    ) -> None:
        self.registry = TaskRegistry()
        self._worker = worker
        self._enqueue_notification = enqueue_notification
        self._runner_tasks: dict[str, asyncio.Task] = {}
        self._wake_events: dict[str, asyncio.Event] = {}
        self._cancel_flags: set[str] = set()

    async def spawnAgentTask(self, input_data: AgentToolInput, session_id: str) -> dict[str, str]:
        mode: TaskMode = "spawn" if input_data.subagent_type else "fork"
        now = int(time.time() * 1000)
        task_id = str(uuid.uuid4())
        task = BaseTask(
            id=task_id,
            name=input_data.name,
            createdAt=now,
            updatedAt=now,
            status="pending",
            mode=mode,
            isolation=input_data.isolation,
            coordinatorSessionId=session_id,
            runInBackground=input_data.run_in_background,
            prompt=input_data.prompt,
            subagentType=input_data.subagent_type,
            model=input_data.model,
        )

        self.registry.createTask(task)
        self._wake_events[task_id] = asyncio.Event()

        if input_data.run_in_background:
            t = asyncio.create_task(self.runAgentTask(task_id))
            self._runner_tasks[task_id] = t
            # Clean up bookkeeping dicts when the task finishes so they don't
            # grow unboundedly across many spawn/finish cycles.
            t.add_done_callback(lambda _t, tid=task_id: self._cleanup_task(tid))
            return {"task_id": task_id, "status": "started", "name": input_data.name or ""}

        await self.runAgentTask(task_id, one_shot=True)
        final = self.registry.getTask(task_id)
        return {
            "task_id": task_id,
            "status": final.status if final else "failed",
            "name": input_data.name or "",
        }

    async def runAgentTask(self, task_id: str, one_shot: bool = False) -> None:
        task = self.registry.getTask(task_id)
        if not task:
            return

        started_at = time.time()
        foreground_mode = one_shot
        has_run_once = False

        while True:
            current = self.registry.getTask(task_id)
            if not current:
                return

            if task_id in self._cancel_flags:
                self.registry.updateTask(task_id, lambda t: replace(t, status="killed", summary="Task stopped"))
                self._enqueue_once(task_id)
                return

            next_prompt: str | None = None
            if not has_run_once:
                next_prompt = current.prompt
            elif current.pendingMessages:
                next_prompt = current.pendingMessages[0]

            if next_prompt is None:
                if foreground_mode:
                    if current.status == "running":
                        self.registry.updateTask(task_id, lambda t: replace(t, status="completed"))
                        self._enqueue_once(task_id)
                    return

                event = self._wake_events.get(task_id)
                if event is None:
                    return
                try:
                    await asyncio.wait_for(event.wait(), timeout=IDLE_WAIT_TIMEOUT_SECONDS)
                    event.clear()
                    continue
                except asyncio.TimeoutError:
                    self.registry.updateTask(task_id, lambda t: replace(t, status="completed", summary="Idle timeout"))
                    self._enqueue_once(task_id)
                    return

            self.registry.updateTask(task_id, lambda t: replace(t, status="running", pendingMessages=t.pendingMessages[1:] if has_run_once and t.pendingMessages else t.pendingMessages, notified=False))

            try:
                result_text = await self._worker(current, next_prompt)
                has_run_once = True
                worker_result = self._build_worker_result(current.id, result_text, started_at)

                verification_result_text = None
                verification_result = None
                decision = decide_completion(worker_result)
                if decision.nextAction == "run-verification":
                    verification_prompt = self._build_verification_prompt(current, worker_result)
                    verification_task = replace(current, subagentType="verification")
                    verification_result_text = await self._worker(verification_task, verification_prompt)
                    verification_result = parse_verification_verdict(verification_result_text, task_id=current.id)
                    decision = decide_completion(worker_result, verification_result)

                if decision.done:
                    self.registry.updateTask(
                        task_id,
                        lambda t: replace(
                            t,
                            result=worker_result.result,
                            summary=worker_result.summary,
                            filesChanged=worker_result.filesChanged,
                            commandsExecuted=worker_result.commandsExecuted,
                            unresolvedIssues=worker_result.unresolvedIssues,
                            evidence=(worker_result.evidence + ([verification_result_text] if verification_result_text else [])),
                            durationMs=worker_result.usage.durationMs if worker_result.usage else None,
                            status="completed",
                            notified=False,
                        ),
                    )
                    self._enqueue_once(task_id)
                    if foreground_mode:
                        return
                    continue

                if decision.nextAction == "retry-worker":
                    if current.repairAttempts >= MAX_REPAIR_ATTEMPTS:
                        reason = (
                            "Exceeded maximum repair attempts; stopping to avoid retry loop. "
                            "Please revise task plan or switch implementation approach."
                        )
                        self.registry.updateTask(
                            task_id,
                            lambda t: replace(
                                t,
                                status="failed",
                                summary=reason,
                                error=reason,
                                notified=False,
                            ),
                        )
                        self._enqueue_once(task_id)
                        return

                    retry_reason = decision.reason
                    if verification_result_text:
                        retry_reason += "\n" + verification_result_text
                    self.registry.updateTask(
                        task_id,
                        lambda t: replace(
                            t,
                            pendingMessages=[
                                *t.pendingMessages,
                                (
                                    "Please fix and continue using a different approach than previous attempts. "
                                    f"Attempt {t.repairAttempts + 1}/{MAX_REPAIR_ATTEMPTS}. {retry_reason}"
                                ),
                            ],
                            summary=retry_reason,
                            repairAttempts=t.repairAttempts + 1,
                            notified=False,
                        ),
                    )
                    continue

                self.registry.updateTask(task_id, lambda t: replace(t, status="failed", summary=decision.reason, error=decision.reason, notified=False))
                self._enqueue_once(task_id)
                return
            except Exception as exc:
                self.registry.updateTask(
                    task_id,
                    lambda t: replace(t, status="failed", error=str(exc), summary=str(exc), notified=False),
                )
                self._enqueue_once(task_id)
                return

    def sendMessageToTask(self, input_data: SendMessageToolInput, session_id: str) -> dict[str, str | bool]:
        task = self.registry.getTask(input_data.to)
        if task is None:
            task = self.registry.findTaskByName(session_id, input_data.to)
        if task is None:
            return {"delivered": False, "task_id": "", "error": "task not found"}
        if task.status in {"completed", "failed", "killed"}:
            return {"delivered": False, "task_id": task.id, "error": f"task already {task.status}"}

        self.registry.updateTask(
            task.id,
            lambda t: replace(t, pendingMessages=[*t.pendingMessages, input_data.message], notified=False),
        )
        event = self._wake_events.get(task.id)
        if event:
            event.set()
        return {"delivered": True, "task_id": task.id}

    def stopTask(self, input_data: TaskStopToolInput) -> dict[str, str | bool]:
        task = self.registry.getTask(input_data.task_id)
        if task is None:
            return {"stopped": False, "task_id": input_data.task_id, "error": "task not found"}
        if task.status in {"completed", "failed", "killed"}:
            return {"stopped": False, "task_id": task.id, "error": f"task already {task.status}"}

        self._cancel_flags.add(task.id)
        event = self._wake_events.get(task.id)
        if event:
            event.set()
        return {"stopped": True, "task_id": task.id}

    def listTasks(self, session_id: str) -> list[dict[str, str | int | bool | None]]:
        items = self.registry.listTasksBySession(session_id)
        return [
            {
                "task_id": t.id,
                "name": t.name,
                "status": t.status,
                "mode": t.mode,
                "subagent_type": t.subagentType,
                "created_at": t.createdAt,
                "updated_at": t.updatedAt,
                "duration_ms": t.durationMs,
                "verification_needed": t.verificationNeeded,
            }
            for t in items
        ]

    def listIncompleteBackgroundTasks(self, session_id: str) -> list[dict[str, str | int | bool | None]]:
        items = self.registry.listIncompleteBackgroundTasks(session_id)
        return [
            {
                "task_id": t.id,
                "name": t.name,
                "status": t.status,
                "mode": t.mode,
                "subagent_type": t.subagentType,
                "created_at": t.createdAt,
            }
            for t in items
        ]

    def _cleanup_task(self, task_id: str) -> None:
        """Drop transient bookkeeping after a runner task finishes."""
        self._runner_tasks.pop(task_id, None)
        self._wake_events.pop(task_id, None)
        self._cancel_flags.discard(task_id)

    def _enqueue_once(self, task_id: str) -> None:
        def updater(t: BaseTask) -> BaseTask:
            if t.notified:
                return t
            status = cast(
                Literal["completed", "failed", "killed"],
                t.status if t.status in {"completed", "failed", "killed"} else "failed",
            )
            worker_result = WorkerResult(
                taskId=t.id,
                status=status,
                summary=t.summary or "",
                result=t.result or "",
                filesChanged=t.filesChanged,
                commandsExecuted=t.commandsExecuted,
                evidence=t.evidence,
                unresolvedIssues=t.unresolvedIssues,
                usage=TaskUsage(durationMs=t.durationMs),
            )
            self._enqueue_notification(
                to_task_notification_xml(
                    worker_result,
                    total_tokens=t.totalTokens,
                    tool_uses=t.toolUseCount,
                    output_file=t.outputFile,
                    worktree=t.worktreePath,
                    worktree_branch=t.worktreeBranch,
                )
            )
            return replace(t, notified=True)

        self.registry.updateTask(task_id, updater)

    def _build_worker_result(self, task_id: str, text: str, started_at: float) -> WorkerResult:
        summary = text.strip().splitlines()[0] if text.strip() else ""

        parsed = self._parse_structured_report(text)
        if parsed:
            result_body = "\n".join(parsed.get("RESULT", [])).strip() or text
            files_changed = [line for line in parsed.get("FILES_CHANGED", []) if line and line != "(none)"]
            commands = [line.removeprefix("$ ").strip() for line in parsed.get("COMMANDS", []) if line and line != "(none)"]
            evidence = [line for line in parsed.get("EVIDENCE", []) if line and line != "(none)"]
            unresolved = [line for line in parsed.get("UNRESOLVED", []) if line and line != "(none)"]
            if parsed.get("NEEDED_INPUT"):
                needed = [line for line in parsed["NEEDED_INPUT"] if line and line != "(none)"]
                if needed:
                    unresolved = [*unresolved, *needed]
        else:
            result_body = text
            files_changed = list(dict.fromkeys(match.group(0) for match in _FILES_PATTERN.finditer(text)))
            commands = [line.strip().removeprefix("$ ") for line in text.splitlines() if _COMMAND_PATTERN.match(line)]
            # Word-boundary match so legitimate prose like "I used the unresolved
            # tracker tool" doesn't get flagged as an unresolved issue.
            unresolved = [
                line.strip()
                for line in text.splitlines()
                if re.search(r"\b(?:UNRESOLVED|TODO|FIXME|XXX)\b", line, re.IGNORECASE)
            ]
            evidence = [line.strip() for line in text.splitlines() if line.strip().startswith("$ ")]

        return WorkerResult(
            taskId=task_id,
            status="completed",
            summary=summary,
            result=result_body,
            filesChanged=files_changed,
            commandsExecuted=commands,
            evidence=evidence,
            unresolvedIssues=unresolved,
            usage=TaskUsage(durationMs=int((time.time() - started_at) * 1000)),
        )

    def _parse_structured_report(self, text: str) -> dict[str, list[str]] | None:
        lines = text.splitlines()
        current: str | None = None
        sections: dict[str, list[str]] = {}

        for raw in lines:
            line = raw.rstrip()
            match = _SECTION_PATTERN.match(line.strip())
            if match:
                current = match.group(1)
                sections.setdefault(current, [])
                continue
            if current is not None:
                stripped = line.strip()
                if stripped:
                    sections[current].append(stripped)

        required = {"RESULT", "FILES_CHANGED", "COMMANDS", "EVIDENCE", "UNRESOLVED", "NEEDED_INPUT"}
        if not required.issubset(set(sections.keys())):
            return None
        return sections

    def _build_verification_prompt(self, task: BaseTask, worker_result: WorkerResult) -> str:
        files = worker_result.filesChanged or []
        commands = worker_result.commandsExecuted or []
        return (
            "ORIGINAL USER REQUEST:\n"
            f"{task.prompt}\n\n"
            "WORKER SUMMARY:\n"
            f"{worker_result.summary or ''}\n\n"
            "FILES CHANGED:\n"
            + ("\n".join(files) if files else "(none reported)")
            + "\n\n"
            "COMMANDS ALREADY RUN:\n"
            + ("\n".join(commands) if commands else "(none reported)")
            + "\n\n"
            "CLAIMS TO VERIFY:\n"
            + (worker_result.result or "(no result text provided)")
        )
