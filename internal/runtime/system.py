import os
import warnings
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.agents import FunctionCallAgent, MainAgent
from internal.co_agents import PhilosopherCoAgent, SupportCoAgent
from internal.logger import logger
from internal.services.agent_factory import load_base_config
from internal.services.voice_manager import VoiceManager
from internal.sub_agents import FunctionCallSubAgent

HISTORY_LIMIT = 30


async def run_cli() -> None:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    load_dotenv()
    logger.info("Starting agent...")

    voice_manager = VoiceManager()
    env = dict(os.environ)
    base_config = load_base_config(env)

    async with AsyncClient(verify=False) as http_client:
        function_call_agent = FunctionCallAgent.create(base_config, env, http_client)
        philosopher = PhilosopherCoAgent.create(base_config, env, http_client)
        co_agent = SupportCoAgent.create(base_config, env, http_client, philosopher)
        sub_agent = FunctionCallSubAgent.create(
            base_config, env, http_client, function_call_agent
        )
        main_agent = MainAgent.create(
            base_config, env, http_client, co_agent, philosopher, sub_agent
        )

        chat_history: list[ModelRequest | ModelResponse] | None = None

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(function_call_agent.agent.run_mcp_servers())
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

                    async with main_agent.agent.run_stream(
                        user_prompt=user_input, message_history=chat_history
                    ) as result:
                        async for message in result.stream_text(delta=True):
                            print(message, end="", flush=True)
                        print()
                        chat_history = result.all_messages()[-HISTORY_LIMIT:]

                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error(f"Error: {exc}")
                    print(f"\nError: {exc}\n")
