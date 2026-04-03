import asyncio

from internal.core.protocol.task_notification import parse_task_notification_xml
from internal.core.tasks.completion_gate import decide_completion, needs_verification
from internal.core.tasks.task_types import VerificationResult, WorkerResult
from internal.services.subagent_tasks import AgentToolInput, BaseTask, SubagentTaskManager


def test_completion_gate_requires_verification_for_implementation():
    worker = WorkerResult(
        taskId="t1",
        status="completed",
        summary="done",
        result="implemented",
        filesChanged=["a.py", "b.py", "c.py", "d.py"],
        commandsExecuted=["pytest -q"],
        evidence=["$ pytest -q"],
        unresolvedIssues=[],
    )

    decision = decide_completion(worker)
    assert decision.done is False
    assert decision.nextAction == "run-verification"
    assert needs_verification(
        {
            "taskKind": "implementation",
            "filesChanged": worker.filesChanged,
            "commandsExecuted": worker.commandsExecuted,
        }
    ) is True


def test_completion_gate_passes_after_verification_pass():
    worker = WorkerResult(
        taskId="t2",
        status="completed",
        summary="done",
        result="implemented",
        filesChanged=["a.py", "b.py", "c.py"],
        commandsExecuted=["pytest -q"],
        evidence=["$ pytest -q"],
        unresolvedIssues=[],
    )
    verification = VerificationResult(
        taskId="t2",
        verdict="PASS",
        summary="verified",
        evidence=[],
        missingRequirements=[],
        suspectedProblems=[],
    )

    decision = decide_completion(worker, verification)
    assert decision.done is True
    assert decision.nextAction == "finalize"


def test_task_notification_roundtrip_from_manager():
    notifications: list[str] = []

    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            return "VERDICT: PASS\n$ pytest -q\nall passed"
        return "Implemented feature\nTouched a.py b.py c.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, notifications.append)

    result = asyncio.run(
        manager.spawnAgentTask(
            AgentToolInput(
                prompt="請實作新功能",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "completed"
    assert notifications
    parsed = parse_task_notification_xml(notifications[-1])
    assert parsed.status == "completed"
    assert parsed.taskId


def test_verification_fail_must_retry_worker_before_complete():
    notifications: list[str] = []
    calls = {"worker": 0, "verifier": 0}

    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            calls["verifier"] += 1
            if calls["verifier"] == 1:
                return "VERDICT: FAIL\n$ pytest -q\n1 failed"
            return "VERDICT: PASS\n$ pytest -q\nall passed"
        calls["worker"] += 1
        if calls["worker"] == 1:
            return "First implementation attempt\nEdited a.py b.py c.py\n$ pytest -q"
        return "Second implementation attempt\nEdited a.py b.py c.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, notifications.append)

    result = asyncio.run(
        manager.spawnAgentTask(
            AgentToolInput(
                prompt="修 API bug",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "completed"
    assert calls["worker"] >= 2
    assert calls["verifier"] >= 2
