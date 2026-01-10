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
from pydantic_ai.mcp import MCPServerStdio

# from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT
from internal.services.voice_manager import VoiceManager
from internal.set_tools import add_all_tools


async def main() -> None:
    load_dotenv()
    logger.info("Starting agent...")

    # Initialize voice manager
    voice_manager = VoiceManager()

    openai_base_url = os.getenv("OPENAI_BASE_URL")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    model_name = os.getenv("MODEL_NAME") or ""
    model_temperature = 0.2
    model_temperature_raw = os.getenv("MODEL_TEMPERATURE")
    if model_temperature_raw:
        try:
            model_temperature = float(model_temperature_raw)
        except ValueError:
            logger.warning(
                f"Invalid MODEL_TEMPERATURE '{model_temperature_raw}', using default {model_temperature}."
            )

    # Ensure OPENAI_BASE_URL is formatted correctly (no trailing slash or /v1)
    if openai_base_url:
        openai_base_url = openai_base_url.rstrip("/")
        if openai_base_url.endswith("/v1"):
            openai_base_url = openai_base_url[:-3].rstrip("/")

    async with AsyncClient(verify=False) as http_client:
        base_url = f"{openai_base_url}/v1" if openai_base_url else None
        model = OpenAIModel(
            model_name=model_name,
            provider=OpenAIProvider(
                base_url=base_url,
                api_key=openai_api_key,
                http_client=http_client,
            ),
        )

        mcp_env = os.environ.copy()
        if openai_api_key:
            mcp_env["OPENAI_API_KEY"] = openai_api_key
        if model_name:
            mcp_env["BROWSER_USE_LLM_MODEL"] = model_name

        browser_use_mcp = MCPServerStdio(
            command=sys.executable,
            args=["-m", "browser_use.mcp.server"],
            env=mcp_env,
        )
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            model_settings={"temperature": model_temperature},
            mcp_servers=[browser_use_mcp],
        )

        add_all_tools(agent, model_name, openai_base_url, openai_api_key)

        chat_history: list[ModelRequest | ModelResponse] | None = None

        async with agent.run_mcp_servers():
            print("\nAgent 已就緒。")
            while True:
                try:
                    user_input = input(
                        "請輸入文字 (或直接按 Enter 開啟語音辨識): "
                    ).strip()
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
                        # print("回答: ", end="", flush=True)

                        # 串流輸出文字 (打字機效果)
                        async for message in result.stream_text(delta=True):
                            for char in message:
                                print(char, end="", flush=True)
                                await asyncio.sleep(0.05)
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
