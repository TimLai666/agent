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


async def run_cli(prompt_once: str | None = None, single_turn: bool = False) -> None:
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
            if prompt_once is not None:
                user_input = prompt_once.strip()
                if not user_input:
                    return
                await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                return

            def update_history() -> None:
                nonlocal chat_history
                try:
                    if getattr(main_agent, "_last_messages", None):
                        chat_history = (
                            main_agent._last_messages[-HISTORY_LIMIT:]
                            if main_agent._last_messages is not None
                            else None
                        )
                except Exception:
                    chat_history = None

            def read_input_once() -> str | None:
                user_input = input("Enter text (or press Enter for speech): ").strip()
                if not user_input:
                    user_input = voice_manager.recognize_speech()
                    if not user_input:
                        return None
                    print("Speech recognized: " + user_input)
                return user_input

            if single_turn:
                user_input = read_input_once()
                if not user_input:
                    return
                if user_input.lower() in ["exit", "quit"]:
                    return
                await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                update_history()
                return

            while True:
                try:
                    user_input = read_input_once()
                    if not user_input:
                        continue
                    if user_input.lower() in ["exit", "quit"]:
                        break
                    await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                    update_history()
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error("Error: " + str(exc))
                    print("\nError: " + str(exc) + "\n")
