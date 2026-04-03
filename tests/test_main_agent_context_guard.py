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
