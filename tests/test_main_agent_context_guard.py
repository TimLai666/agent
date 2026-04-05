from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from internal.agents.main_agent import MainAgent


def _build_history(count: int, size: int = 8000) -> list[ModelRequest | ModelResponse]:
    messages: list[ModelRequest | ModelResponse] = []
    for i in range(count):
        text = f"msg-{i}-" + ("x" * size)
        if i % 2 == 0:
            messages.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        else:
            messages.append(ModelResponse(parts=[TextPart(content=text)], model_name="test"))
    return messages


def test_trim_message_history_for_budget_keeps_recent_messages():
    agent = MainAgent.__new__(MainAgent)
    history = _build_history(520)
    user_content = ["short prompt"]

    trimmed = agent._trim_message_history_for_budget(history, user_content)

    assert trimmed is not None
    assert len(trimmed) < len(history)
    assert trimmed[-1] == history[-1]


def test_context_overflow_error_detection():
    agent = MainAgent.__new__(MainAgent)

    err = Exception(
        "This endpoint's maximum context length is 1000000 tokens. However, you requested about 1061878 tokens"
    )
    assert agent._is_context_overflow_error(err) is True

    other = Exception("temporary network failure")
    assert agent._is_context_overflow_error(other) is False


def test_follow_through_needs_retry_on_verdict_fail():
    import asyncio

    agent = MainAgent.__new__(MainAgent)
    agent._http_client = object()

    async def fake_run_subagent_task(_task, _prompt):
        return "VERDICT: FAIL\nno concrete output"

    agent._run_subagent_task = fake_run_subagent_task

    needs_retry = asyncio.run(agent._follow_through_needs_retry("請修 bug", "我會先處理"))
    assert needs_retry is True


def test_follow_through_no_retry_on_verdict_pass():
    import asyncio

    agent = MainAgent.__new__(MainAgent)
    agent._http_client = object()

    async def fake_run_subagent_task(_task, _prompt):
        return "VERDICT: PASS\ncompleted"

    agent._run_subagent_task = fake_run_subagent_task

    needs_retry = asyncio.run(agent._follow_through_needs_retry("請修 bug", "已修復並附結果"))
    assert needs_retry is False


def test_subagent_report_contract_contains_required_sections():
    text = MainAgent._build_subagent_report_contract("research")

    assert "[RESULT]" in text
    assert "[FILES_CHANGED]" in text
    assert "[COMMANDS]" in text
    assert "[EVIDENCE]" in text
    assert "[UNRESOLVED]" in text
    assert "[NEEDED_INPUT]" in text


def test_build_subagent_system_prompt_includes_env_notes_and_append():
    text = MainAgent._build_subagent_system_prompt(
        agent_type="general-purpose",
        append_prompt="APPEND-PROMPT",
        include_env_notes=True,
    )

    assert "general-purpose worker agent" in text.lower() or "general-purpose" in text.lower()
    assert "prefer absolute file paths" in text
    assert "APPEND-PROMPT" in text
