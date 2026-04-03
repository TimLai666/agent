from internal.core.protocol.task_notification import (
    is_task_notification_message,
    parse_task_notification_xml,
    to_task_notification_xml,
)
from internal.core.tasks.task_types import TaskUsage, WorkerResult


def test_task_notification_xml_matches_required_usage_fields():
    worker = WorkerResult(
        taskId="task-123",
        status="completed",
        summary="done",
        result="final result",
        filesChanged=["a.py"],
        commandsExecuted=["pytest -q"],
        evidence=[],
        unresolvedIssues=[],
        usage=TaskUsage(durationMs=321),
    )

    xml = to_task_notification_xml(
        worker,
        total_tokens=999,
        tool_uses=4,
        output_file="C:/tmp/out.txt",
        worktree="C:/tmp/wt",
        worktree_branch="feature/x",
    )

    assert "<total_tokens>999</total_tokens>" in xml
    assert "<tool_uses>4</tool_uses>" in xml
    assert "<output_file>C:/tmp/out.txt</output_file>" in xml
    assert "<worktree>C:/tmp/wt</worktree>" in xml
    assert "<worktree-branch>feature/x</worktree-branch>" in xml

    parsed = parse_task_notification_xml(xml)
    assert parsed.taskId == "task-123"
    assert parsed.status == "completed"
    assert parsed.usage is not None
    assert parsed.usage.inputTokens == 999
    assert parsed.usage.durationMs == 321


def test_task_notification_detection_requires_start_tag():
    assert is_task_notification_message("   <task-notification>\n...") is True
    assert is_task_notification_message("prefix <task-notification>") is False
