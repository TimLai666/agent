from __future__ import annotations

import json
import re
from typing import Literal

from internal.core.tasks.task_types import CoordinatorTodo, VerificationEvidence, VerificationResult


_REMEDIATION_JSON_MARKER = "REMEDIATION_TODOS_JSON:"
_REMEDIATION_LINE = re.compile(r"^REMEDIATION_TODO:\s*(.+)$")
_VERDICT_LINE = re.compile(r"^\s*VERDICT:\s*(PASS|FAIL|PARTIAL)\s*$", re.MULTILINE)


def _parse_remediation_json(text: str) -> list[CoordinatorTodo]:
    marker_index = text.find(_REMEDIATION_JSON_MARKER)
    if marker_index < 0:
        return []

    payload = text[marker_index + len(_REMEDIATION_JSON_MARKER) :].strip()
    if not payload:
        return []

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []

    items = data if isinstance(data, list) else [data]
    todos: list[CoordinatorTodo] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        description = str(item.get("description", "")).strip() or title
        raw_priority = str(item.get("priority", "medium")).strip().lower()
        priority = raw_priority if raw_priority in {"high", "medium", "low"} else "medium"
        todos.append(
            CoordinatorTodo(
                id=f"todo_remed_{index:03d}",
                title=title,
                description=description,
                priority=priority,
            )
        )
    return todos


def _parse_remediation_lines(lines: list[str], offset: int = 0) -> list[CoordinatorTodo]:
    todos: list[CoordinatorTodo] = []
    for raw in lines:
        match = _REMEDIATION_LINE.match(raw.strip())
        if not match:
            continue
        body = match.group(1)
        parts = [part.strip() for part in body.split("|") if part.strip()]
        title = parts[0] if parts else "補上驗證缺漏"
        description = parts[1] if len(parts) > 1 else title
        raw_priority = parts[2].lower() if len(parts) > 2 else "high"
        priority = raw_priority if raw_priority in {"high", "medium", "low"} else "high"
        todos.append(
            CoordinatorTodo(
                id=f"todo_remed_{offset + len(todos) + 1:03d}",
                title=title,
                description=description,
                priority=priority,
            )
        )
    return todos


def parse_verification_verdict(text: str, task_id: str = "") -> VerificationResult:
    # Match anchored "VERDICT: X" lines only (avoids false positives in prose like
    # `do not report "VERDICT: PASS" without evidence`). Take the LAST match so a
    # final verdict overrides any earlier instructional mention.
    verdict_matches = _VERDICT_LINE.findall(text)
    verdict = verdict_matches[-1] if verdict_matches else "FAIL"

    evidence: list[VerificationEvidence] = []
    # Evidence rows extracted from "$ command" lines have unknown per-command status;
    # mirror the overall verdict so a FAIL verdict isn't misrepresented as all-PASS.
    evidence_result: Literal["PASS", "FAIL"] = "PASS" if verdict == "PASS" else "FAIL"
    missing_requirements: list[str] = []
    suspected_problems: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("$ "):
            evidence.append(VerificationEvidence(command=stripped[2:], output="", result=evidence_result))
        elif stripped.startswith("MISSING_REQUIREMENT:"):
            missing_requirements.append(stripped.removeprefix("MISSING_REQUIREMENT:").strip())
        elif stripped.startswith("SUSPECTED_PROBLEM:"):
            suspected_problems.append(stripped.removeprefix("SUSPECTED_PROBLEM:").strip())

    summary = text.strip().splitlines()[0] if text.strip() else ""
    if not summary:
        summary = "Verification output missing VERDICT"
    remediation_todos = _parse_remediation_json(text)
    if not remediation_todos:
        remediation_todos = _parse_remediation_lines(text.splitlines())

    if verdict != "PASS" and not remediation_todos:
        fallback_title = "修補驗證未通過項目"
        fallback_description = "; ".join(missing_requirements + suspected_problems) or summary or "補足驗證指出的問題"
        remediation_todos = [
            CoordinatorTodo(
                id="todo_remed_001",
                title=fallback_title,
                description=fallback_description,
                priority="high",
                assignedTo="main_agent",
            )
        ]

    return VerificationResult(
        taskId=task_id,
        verdict=verdict,
        summary=summary,
        evidence=evidence,
        missingRequirements=missing_requirements,
        suspectedProblems=suspected_problems,
        remediationTodos=remediation_todos,
    )
