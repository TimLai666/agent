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

    assert "已完成：已完成搜尋與比較" in text
    assert "驗證結果：已驗證通過。" in text
    assert "詳細結果：" in text
    assert "- 主題 A" in text
