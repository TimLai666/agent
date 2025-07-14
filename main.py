from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from dotenv import load_dotenv
import os

from internal.tools.tools import add_all_tools


def main() -> None:
    load_dotenv()

    ollama_model: OpenAIModel = OpenAIModel(
        model_name='qwen3:14b', provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')
    )
    agent: Agent[None, str] = Agent(ollama_model)

    add_all_tools(agent)

    user_input: str = input('請輸入您的問題: ')
    result: AgentRunResult[str] = agent.run_sync(user_input)

    print(result.output)
    print('\n', result.usage())
    # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)


if __name__ == "__main__":
    main()
