import asyncio

from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.agents.main_agent import MainAgent


def test_runtime_instructions_are_merged_into_single_leading_system_message():
    merged_system_prompt, request_instructions = MainAgent._compose_agent_prompt(
        "Base system prompt",
        "Runtime instructions",
    )

    async def run_test() -> None:
        model = OpenAIChatModel(
            model_name="test-model",
            provider=OpenAIProvider(base_url="https://example.com/v1", api_key="test-key"),
        )
        messages = [
            ModelRequest(
                parts=[
                    SystemPromptPart(content=merged_system_prompt),
                    UserPromptPart(content="hello"),
                ],
                instructions=request_instructions,
            ),
            ModelResponse(parts=[TextPart(content="ok")], model_name="test-model"),
            ModelRequest(
                parts=[UserPromptPart(content="next")],
                instructions=request_instructions,
            ),
        ]

        mapped = await model._map_messages(messages, ModelRequestParameters())
        roles = [message["role"] for message in mapped]

        assert roles == ["system", "user", "assistant", "user"]

    asyncio.run(run_test())
