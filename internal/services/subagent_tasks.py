from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Awaitable, Callable, Literal
from xml.sax.saxutils import escape

TaskStatus = Literal[
    "queued",
    "running",
    "waiting_message",
    "completed",
    "failed",
    "killing",
    "killed",
]
TaskIsolation = Literal["none", "worktree", "remote"]
TaskMode = Literal["spawn", "fork"]


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


class NotificationQueue:
    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._lock = RLock()

    def enqueue(self, xml: str) -> None:
        with self._lock:
            self._queue.append(xml)

    def drain(self) -> list[str]:
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items


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
            status="queued",
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
            self._runner_tasks[task_id] = asyncio.create_task(self.runAgentTask(task_id))
            return {"task_id": task_id, "status": "started", "name": input_data.name or ""}

        await self.runAgentTask(task_id, one_shot=True)
        return {"task_id": task_id, "status": "completed", "name": input_data.name or ""}

    async def runAgentTask(self, task_id: str, one_shot: bool = False) -> None:
        task = self.registry.getTask(task_id)
        if not task:
            return

        started_at = time.time()
        self.registry.updateTask(task_id, lambda t: replace(t, status="running", notified=False))

        has_run_once = False
        while True:
            current = self.registry.getTask(task_id)
            if not current:
                return
            if task_id in self._cancel_flags or current.status in {"killing", "killed"}:
                self.registry.updateTask(task_id, lambda t: replace(t, status="killed", summary="Task stopped"))
                self._enqueue_once(task_id)
                return

            next_prompt: str | None = None
            if not has_run_once:
                next_prompt = current.prompt
            elif current.pendingMessages:
                next_prompt = current.pendingMessages[0]

            if next_prompt is None:
                if one_shot:
                    self.registry.updateTask(task_id, lambda t: replace(t, status="completed"))
                    self._enqueue_once(task_id)
                    return

                self.registry.updateTask(task_id, lambda t: replace(t, status="waiting_message"))
                event = self._wake_events.get(task_id)
                if event is None:
                    self.registry.updateTask(task_id, lambda t: replace(t, status="completed"))
                    self._enqueue_once(task_id)
                    return
                try:
                    await asyncio.wait_for(event.wait(), timeout=300)
                    event.clear()
                    continue
                except asyncio.TimeoutError:
                    self.registry.updateTask(task_id, lambda t: replace(t, status="completed", summary="Idle timeout"))
                    self._enqueue_once(task_id)
                    return

            def _consume_message(t: BaseTask) -> BaseTask:
                pending = list(t.pendingMessages)
                if has_run_once and pending:
                    pending = pending[1:]
                return replace(t, status="running", pendingMessages=pending)

            self.registry.updateTask(task_id, _consume_message)

            try:
                result = await self._worker(current, next_prompt)
                has_run_once = True
                duration_ms = int((time.time() - started_at) * 1000)
                self.registry.updateTask(
                    task_id,
                    lambda t: replace(
                        t,
                        result=result,
                        summary=(result[:140] + "...") if len(result) > 140 else result,
                        durationMs=duration_ms,
                        status="waiting_message" if not one_shot else "completed",
                        notified=False,
                    ),
                )
                self._enqueue_once(task_id)
                if one_shot:
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
        self.registry.updateTask(task.id, lambda t: replace(t, status="killing", notified=False))
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
            }
            for t in items
        ]

    def buildTaskNotificationXml(self, task: BaseTask) -> str:
        status = task.status if task.status in {"failed", "killed"} else "completed"
        summary = escape(task.summary or "")
        result = escape(task.result or "")
        output_file = escape(task.outputFile or "")
        total_tokens = task.totalTokens if task.totalTokens is not None else 0
        tool_uses = task.toolUseCount
        duration = task.durationMs if task.durationMs is not None else 0

        xml = (
            "<task-notification>\n"
            f"  <task-id>{escape(task.id)}</task-id>\n"
            f"  <status>{status}</status>\n"
            f"  <summary>{summary}</summary>\n"
            f"  <result>{result}</result>\n"
            f"  <output_file>{output_file}</output_file>\n"
            "  <usage>\n"
            f"    <total_tokens>{total_tokens}</total_tokens>\n"
            f"    <tool_uses>{tool_uses}</tool_uses>\n"
            f"    <duration_ms>{duration}</duration_ms>\n"
            "  </usage>\n"
            "</task-notification>"
        )
        return xml

    def _enqueue_once(self, task_id: str) -> None:
        def updater(t: BaseTask) -> BaseTask:
            if t.notified:
                return t
            xml = self.buildTaskNotificationXml(t)
            self._enqueue_notification(xml)
            return replace(t, notified=True)

        self.registry.updateTask(task_id, updater)
