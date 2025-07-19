from groq import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from dotenv import load_dotenv
from httpx import AsyncClient
import os

from internal.prompts import SYSTEM_PROMPT
from internal.tools.tools import add_all_tools
from internal.services.voice_manager import VoiceManager
from internal.logger import logger


def main() -> None:
    logger.info("Starting agent...")
    load_dotenv()
    logger.debug("Environment variables loaded.")
    # 語音輸入功能測試於主程式
    voice_manager = VoiceManager()
    # recognized_text = voice_manager.recognize_speech()
    # print(recognized_text)

    ollama_model = OpenAIModel(
        model_name='qwen3:14b', provider=OpenAIProvider(
            base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1',
            http_client=AsyncClient(verify=False)
        )
    )
    agent: Agent[None, str] = Agent(
        model=ollama_model,
        system_prompt=SYSTEM_PROMPT,
        tools=[duckduckgo_search_tool(max_results=10)],
    )

    add_all_tools(agent)

    chat_history: list[ModelRequest | ModelResponse] | None = None
    while user_input := input("請輸入文字: "):
        result: AgentRunResult[str] = agent.run_sync(
            user_prompt=user_input, message_history=chat_history)
        print(result.output)
        print('\n', result.usage(), end="\n\n")
        # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)

        # 只保留最近30則聊天記錄
        chat_history = result.all_messages()[-30:]


if __name__ == "__main__":
    main()
