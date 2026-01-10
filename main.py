import os

from dotenv import load_dotenv
from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT
from internal.services.voice_manager import VoiceManager
from internal.tools.tools import add_all_tools

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME") or ""


def main() -> None:
    logger.info("Starting agent...")
    load_dotenv()
    logger.debug("Environment variables loaded.")
    # 語音輸入功能
    voice_manager = VoiceManager()

    ollama_model = OpenAIModel(
        model_name=MODEL_NAME,
        provider=OpenAIProvider(
            base_url=f"{OPENAI_BASE_URL}/v1",
            api_key=OPENAI_API_KEY,
            http_client=AsyncClient(verify=False),
        ),
    )
    agent: Agent[None, str] = Agent(
        model=ollama_model,
        system_prompt=SYSTEM_PROMPT,
        tools=[duckduckgo_search_tool(max_results=10)],
    )

    add_all_tools(agent)

    chat_history: list[ModelRequest | ModelResponse] | None = None
    while True:
        user_input = input("請輸入文字 (或直接按 Enter 開啟語音辨識): ")
        if not user_input:
            user_input = voice_manager.recognize_speech()
            if not user_input:
                continue
            print(f"辨識結果: {user_input}")

        result: AgentRunResult[str] = agent.run_sync(
            user_prompt=user_input, message_history=chat_history
        )
        print(result.output)
        print("\n", result.usage(), end="\n\n")
        # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)

        # 只保留最近30則聊天記錄
        chat_history = result.all_messages()[-30:]


if __name__ == "__main__":
    main()
