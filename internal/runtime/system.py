import asyncio
from collections import deque
import os
import warnings
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.runtime.stream_printer import stream_print

from internal.agents import MainAgent
from internal.co_agents import PhilosopherCoAgent
from internal.logger import logger
from internal.services.agent_factory import load_base_config
from internal.services.voice_manager import VoiceManager

HISTORY_LIMIT = 30
TYPEWRITER_DELAY = 0.04


async def run_cli() -> None:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    load_dotenv()
    logger.info("Starting agent...")

    voice_manager = VoiceManager()
    env = dict(os.environ)
    base_config = load_base_config(env)

    async with AsyncClient(verify=False) as http_client:
        philosopher = PhilosopherCoAgent.create(base_config, env, http_client)
        # Register tools directly on main agent; no separate sub-agent layer
        main_agent = MainAgent.create(base_config, env, http_client, philosopher)

        chat_history: list[ModelRequest | ModelResponse] | None = None

        async with AsyncExitStack() as stack:
            # MCP servers are run by the main agent (contains browser tools)
            await stack.enter_async_context(main_agent.agent.run_mcp_servers())

            print("\nAgent ready.")
            while True:
                try:
                    user_input = input(
                        "Enter text (or press Enter for speech): "
                    ).strip()
                    if not user_input:
                        user_input = voice_manager.recognize_speech()
                        if not user_input:
                            continue
                        print(f"Speech recognized: {user_input}")

                    if user_input.lower() in ["exit", "quit"]:
                        break

                    # 使用統一的 stream_printer 來印出主 agent 串流結果
                    await stream_print(main_agent.run_stream(user_input, message_history=chat_history))

                    # 嘗試從 MainAgent 儲存的最後訊息更新 chat_history
                    try:
                        if getattr(main_agent, "_last_messages", None):
                            chat_history = (
                                main_agent._last_messages[-HISTORY_LIMIT:]
                                if main_agent._last_messages is not None
                                else None
                            )
                    except Exception:
                        chat_history = None

                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error(f"Error: {exc}")
                    print(f"\nError: {exc}\n")
