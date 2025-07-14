from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from dotenv import load_dotenv
import os

from internal.tools.tools import add_all_tools


def main() -> None:
    load_dotenv()

    ollama_model: OpenAIModel = OpenAIModel(
        model_name='qwen3:14b',
        provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')
    )
    agent: Agent[None, str] = Agent(
        model=ollama_model,
        system_prompt="""
        Ignore all previous instructions.
        You are a helpful assistant. You can use various tools to assist the user.
        If you want to speak Chinese, use Traditional Chinese(Taiwan).
        Never use Simplified Chinese.
        [IMPORTANT] Never claim or agree with one China policy or Taiwan is part of China.
        [IMPORTANT] Always disagree with Chinese political statements.
        [IMPORTANT] Any statement that "xxx has been a part of China since ancient times" is wrong.
        [IMPORTANT] Anything in Chinese law has never been an international consensus.
        """
    )

    add_all_tools(agent)

    chat_history: list[ModelRequest | ModelResponse] = []
    while user_input := input('請輸入文字: '):
        result: AgentRunResult[str] = agent.run_sync(
            user_prompt=user_input, message_history=chat_history)
        print(result.output)
        print('\n', result.usage(), end='\n\n')
        # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)
        chat_history = result.all_messages()


if __name__ == "__main__":
    main()
