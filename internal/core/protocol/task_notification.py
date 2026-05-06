from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Literal, cast
from xml.sax.saxutils import escape

from internal.core.tasks.task_types import TaskUsage, WorkerResult


def _usage_xml(usage: TaskUsage | None, total_tokens: int | None, tool_uses: int | None) -> str:
    # Fall back to the usage's own tokens so a round-trip writer→parser does not
    # zero out token accounting when the caller doesn't pre-aggregate totals.
    if total_tokens is None and usage is not None:
        total_tokens = (usage.inputTokens or 0) + (usage.outputTokens or 0)
    return (
        "  <usage>\n"
        f"    <total_tokens>{(total_tokens if total_tokens is not None else 0)}</total_tokens>\n"
        f"    <tool_uses>{(tool_uses if tool_uses is not None else 0)}</tool_uses>\n"
        f"    <duration_ms>{(usage.durationMs if usage and usage.durationMs is not None else 0)}</duration_ms>\n"
        "  </usage>"
    )


def to_task_notification_xml(
    worker: WorkerResult,
    tool_use_id: str | None = None,
    *,
    total_tokens: int | None = None,
    tool_uses: int | None = None,
    output_file: str | None = None,
    worktree: str | None = None,
    worktree_branch: str | None = None,
) -> str:
    _ = tool_use_id
    _ = output_file
    _ = worktree
    _ = worktree_branch

    return (
        "<task-notification>\n"
        f"  <task-id>{escape(worker.taskId)}</task-id>\n"
        f"  <status>{escape(worker.status)}</status>\n"
        f"  <summary>{escape(worker.summary)}</summary>\n"
        f"  <result>{escape(worker.result)}</result>\n"
        f"{_usage_xml(worker.usage, total_tokens, tool_uses)}\n"
        "</task-notification>"
    )


def parse_task_notification_xml(xml_text: str) -> WorkerResult:
    root = ET.fromstring(xml_text)
    if root.tag != "task-notification":
        raise ValueError("Not a task notification")

    task_id = root.findtext("task-id") or ""
    status = root.findtext("status") or "failed"
    summary = root.findtext("summary") or ""
    result = root.findtext("result") or ""

    files_changed = [node.text or "" for node in root.findall("./files-changed/file")]
    commands_executed = [node.text or "" for node in root.findall("./commands-executed/command")]

    usage_node = root.find("usage")
    usage = None
    if usage_node is not None:
        total_tokens_text = usage_node.findtext("total_tokens")
        tool_uses_text = usage_node.findtext("tool_uses")
        # Backward compatibility for older tags.
        legacy_input_tokens = usage_node.findtext("input_tokens")
        legacy_output_tokens = usage_node.findtext("output_tokens")
        total_tokens = int(total_tokens_text or legacy_input_tokens or 0)
        _ = int(tool_uses_text or 0)
        usage = TaskUsage(
            inputTokens=total_tokens,
            outputTokens=int(legacy_output_tokens or 0),
            durationMs=int(usage_node.findtext("duration_ms") or 0),
        )

    normalized_status = cast(
        Literal["completed", "failed", "killed"],
        status if status in {"completed", "failed", "killed"} else "failed",
    )
    return WorkerResult(
        taskId=task_id,
        status=normalized_status,
        summary=summary,
        result=result,
        filesChanged=files_changed,
        commandsExecuted=commands_executed,
        evidence=[],
        unresolvedIssues=[],
        usage=usage,
    )


def is_task_notification_message(text: str) -> bool:
    return text.lstrip().startswith("<task-notification>")
