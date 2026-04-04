from __future__ import annotations

import re

from internal.core.tasks.task_types import VerificationResult, WorkerResult


_TODO_PREFIX = re.compile(r"^\[todo_\d+\]\s*")


def _normalize_result_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw in text.splitlines():
        line = _TODO_PREFIX.sub("", raw).strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def synthesize_final_answer(
    worker: WorkerResult,
    verification: VerificationResult | None = None,
) -> str:
    result_text = _normalize_result_text(worker.result or "")
    if result_text:
        return result_text

    summary = (worker.summary or "").strip()
    if summary:
        return summary

    if verification and verification.verdict in {"FAIL", "PARTIAL"}:
        return (verification.summary or "驗證未通過，請檢查驗證報告。").strip()

    return ""
