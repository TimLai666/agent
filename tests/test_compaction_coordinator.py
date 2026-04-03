import asyncio

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from internal.compaction import (
    CompactCoordinator,
    ConversationState,
    format_compact_summary,
    get_compact_user_summary_message,
    get_compaction_prompt,
)


def _build_history(count: int) -> list[ModelRequest | ModelResponse]:
    history: list[ModelRequest | ModelResponse] = []
    for i in range(count):
        history.append(ModelRequest(parts=[UserPromptPart(content=f"user message {i} {'x' * 400}")]))
        history.append(ModelResponse(parts=[TextPart(content=f"assistant reply {i} {'y' * 400}")]))
    return history


def test_format_compact_summary_removes_analysis():
    raw = "<analysis>debug</analysis>\n<summary>line1\n\n\nline2</summary>"
    formatted = format_compact_summary(raw)

    assert "analysis" not in formatted.lower()
    assert formatted.startswith("Summary:\n")
    assert "line1\n\nline2" in formatted


def test_build_continuation_message_flags():
    message = get_compact_user_summary_message(
        summary="Summary:\nKeep going",
        transcriptPath="/tmp/transcript.log",
        recentMessagesPreserved=True,
        suppressFollowUpQuestions=True,
        proactiveMode=True,
    )

    assert "Summary:\nKeep going" in message
    assert "transcript" in message
    assert "Recent messages are preserved verbatim." in message
    assert "without asking the user any further questions" in message
    assert "autonomous/proactive mode" in message


def test_get_compaction_prompt_modes():
    base_prompt = get_compaction_prompt("base")
    from_prompt = get_compaction_prompt("partial_from")
    up_to_prompt = get_compaction_prompt("partial_up_to")

    assert "Current Work" in base_prompt
    assert "RECENT portion" in from_prompt
    assert "Work Completed" in up_to_prompt


def test_compaction_coordinator_injects_summary_and_keeps_recent_messages():
    calls: list[str] = []

    async def fake_runner(_job, prompt: str) -> str:
        calls.append(prompt)
        return "<analysis>ok</analysis><summary>Compressed context</summary>"

    coordinator = CompactCoordinator(runner=fake_runner)
    state = ConversationState(fullMessages=_build_history(6), totalTokens=999999)

    compacted = asyncio.run(coordinator.maybeCompact(state))

    assert compacted.compressedSummary == "Summary:\nCompressed context"
    assert len(compacted.recentMessages or []) == 8
    assert len(compacted.fullMessages) == 9
    assert isinstance(compacted.fullMessages[0], ModelRequest)
    first_message = compacted.fullMessages[0]
    assert "continued from a previous conversation" in first_message.parts[0].content
    assert len(calls) == 1


def test_compaction_retry_and_fallback():
    call_count = 0

    async def flaky_runner(_job, _prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return "<analysis>missing summary tags</analysis>"
        return "<analysis>ok</analysis><summary>Recovered</summary>"

    coordinator = CompactCoordinator(runner=flaky_runner)
    state = ConversationState(fullMessages=_build_history(5), totalTokens=999999)

    compacted = asyncio.run(coordinator.maybeCompact(state))

    assert compacted.compressedSummary == "Summary:\nRecovered"
    assert call_count == 3
