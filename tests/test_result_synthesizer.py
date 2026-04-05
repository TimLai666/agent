from internal.core.coordinator.result_synthesizer import synthesize_final_answer
from internal.core.tasks.task_types import VerificationResult, WorkerResult


def test_synthesizer_includes_worker_result_details():
    worker = WorkerResult(
        taskId="t-1",
        status="completed",
        summary="已完成搜尋與比較",
        result="已完成搜尋與比較\n- 主題 A\n- 主題 B\n- 主題 C",
        filesChanged=[],
        commandsExecuted=[],
        evidence=[],
        unresolvedIssues=[],
    )
    verification = VerificationResult(
        taskId="t-1",
        verdict="PASS",
        summary="verified",
        evidence=[],
        missingRequirements=[],
        suspectedProblems=[],
    )

    text = synthesize_final_answer(worker, verification)

    assert "已完成：" not in text
    assert "驗證結果：" not in text
    assert "詳細結果：" not in text
    assert "- 主題 A" in text


def test_synthesizer_strips_todo_prefix_lines():
    worker = WorkerResult(
        taskId="t-2",
        status="completed",
        summary="research-task",
        result="[todo_001]\n[todo_002] 真正內容",
        filesChanged=[],
        commandsExecuted=[],
        evidence=[],
        unresolvedIssues=[],
    )

    text = synthesize_final_answer(worker)
    assert "[todo_001]" not in text
    assert "[todo_002]" not in text
    assert text == "真正內容"
