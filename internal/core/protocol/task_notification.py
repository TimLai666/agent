from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Literal, cast
from xml.sax.saxutils import escape

from internal.core.tasks.task_types import TaskUsage, WorkerResult


def _usage_xml(usage: TaskUsage | None) -> str:
    return (
        "  <usage>\n"
        f"    <input_tokens>{(usage.inputTokens if usage and usage.inputTokens is not None else 0)}</input_tokens>\n"
        f"    <output_tokens>{(usage.outputTokens if usage and usage.outputTokens is not None else 0)}</output_tokens>\n"
        f"    <duration_ms>{(usage.durationMs if usage and usage.durationMs is not None else 0)}</duration_ms>\n"
        "  </usage>"
    )


def to_task_notification_xml(worker: WorkerResult, tool_use_id: str | None = None) -> str:
    files_xml = "\n".join(f"    <file>{escape(path)}</file>" for path in worker.filesChanged)
    commands_xml = "\n".join(
        f"    <command>{escape(command)}</command>" for command in worker.commandsExecuted
    )
    tool_use_xml = f"  <tool-use-id>{escape(tool_use_id)}</tool-use-id>\n" if tool_use_id else ""

    return (
        "<task-notification>\n"
        f"  <task-id>{escape(worker.taskId)}</task-id>\n"
        f"  <status>{escape(worker.status)}</status>\n"
        f"  <summary>{escape(worker.summary)}</summary>\n"
        f"  <result>{escape(worker.result)}</result>\n"
        "  <files-changed>\n"
        f"{files_xml}\n"
        "  </files-changed>\n"
        "  <commands-executed>\n"
        f"{commands_xml}\n"
        "  </commands-executed>\n"
        f"{_usage_xml(worker.usage)}\n"
        f"{tool_use_xml}"
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
        usage = TaskUsage(
            inputTokens=int(usage_node.findtext("input_tokens") or 0),
            outputTokens=int(usage_node.findtext("output_tokens") or 0),
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
    return "<task-notification>" in text
