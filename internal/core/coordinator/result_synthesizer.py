from __future__ import annotations

from internal.core.tasks.task_types import VerificationResult, WorkerResult


def synthesize_final_answer(
    worker: WorkerResult,
    verification: VerificationResult | None = None,
) -> str:
    lines = [f"已完成：{worker.summary}"]
    if verification:
        if verification.verdict == "PASS":
            lines.append("驗證結果：已驗證通過。")
        elif verification.verdict == "PARTIAL":
            lines.append("驗證結果：僅部分通過，仍有缺口。")
        else:
            lines.append("驗證結果：未通過。")
    if worker.unresolvedIssues:
        lines.append("未解決問題：" + "; ".join(worker.unresolvedIssues))
    return "\n".join(lines)
