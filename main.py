import asyncio
import os
import sys
import warnings

# Suppress DeprecationWarnings from third-party libraries (like undetected-chromedriver)
warnings.filterwarnings("ignore", category=DeprecationWarning)
# Suppress ResourceWarnings for cleaner output
warnings.filterwarnings("ignore", category=ResourceWarning)

from dotenv import load_dotenv
from httpx import AsyncClient
from pydantic_ai import Agent
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

# Ensure OPENAI_BASE_URL is formatted correctly (no trailing slash or /v1)
if OPENAI_BASE_URL:
    OPENAI_BASE_URL = OPENAI_BASE_URL.rstrip("/")
    if OPENAI_BASE_URL.endswith("/v1"):
        OPENAI_BASE_URL = OPENAI_BASE_URL[:-3].rstrip("/")


async def main() -> None:
    load_dotenv()
    logger.info("Starting agent...")

    # Initialize voice manager
    voice_manager = VoiceManager()

    async with AsyncClient(verify=False) as http_client:
        model = OpenAIModel(
            model_name=MODEL_NAME,
            provider=OpenAIProvider(
                base_url=f"{OPENAI_BASE_URL}/v1",
                api_key=OPENAI_API_KEY,
                http_client=http_client,
            ),
        )

        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[duckduckgo_search_tool(max_results=10)],
        )

        add_all_tools(agent)

        chat_history: list[ModelRequest | ModelResponse] | None = None

        print("\nAgent 已就緒。")
        while True:
            try:
                user_input = input("請輸入文字 (或直接按 Enter 開啟語音辨識): ").strip()
                if not user_input:
                    user_input = voice_manager.recognize_speech()
                    if not user_input:
                        continue
                    print(f"辨識結果: {user_input}")

                if user_input.lower() in ["exit", "quit", "離開", "結束"]:
                    break

                # 使用 run_stream 進行串流
                async with agent.run_stream(
                    user_prompt=user_input, message_history=chat_history
                ) as result:
                    print("回答: ", end="", flush=True)

                    # 串流輸出文字
                    async for message in result.stream_text(delta=True):
                        print(message, end="", flush=True)
                    print("\n")

                    # 重要：更新聊天紀錄，確保對話連貫
                    chat_history = result.all_messages()[-30:]

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"發生錯誤: {e}")
                print(f"\n抱歉，發生了錯誤: {e}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
