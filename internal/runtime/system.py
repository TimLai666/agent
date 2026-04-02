import warnings
from contextlib import AsyncExitStack
from pathlib import Path

from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.runtime.stream_printer import stream_print

from internal.agents import MainAgent
from internal.logger import logger
from internal.services.agent_factory import load_base_config
from internal.services.voice_manager import VoiceManager
from internal.command_handler import CommandHandler

HISTORY_LIMIT = 30
COMMAND_PREFIX = "/"


def _format_tool_line(event: dict) -> str:
    tool = str(event.get("tool") or "tool")
    args = event.get("args") or ()
    kwargs = event.get("kwargs") or {}
    stage = str(event.get("stage") or "")

    def _trim(value: str, limit: int = 80) -> str:
        value = value.strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    detail = ""
    if tool == "use_skill":
        skill_name = ""
        if isinstance(kwargs, dict):
            raw = kwargs.get("skill_name")
            if isinstance(raw, str):
                skill_name = raw.strip()
        if not skill_name and args:
            first = args[0]
            if isinstance(first, str):
                skill_name = first.strip()
        if skill_name:
            detail = f"skill={_trim(skill_name)}"
    elif isinstance(kwargs, dict):
        for key in ("command", "path", "url", "query"):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                detail = f"{key}={_trim(value)}"
                break

    if not detail and args:
        try:
            first = args[0]
            if isinstance(first, str) and first.strip():
                detail = f"arg={_trim(first)}"
        except Exception:
            pass

    label = tool if not detail else f"{tool} ({detail})"
    if stage == "start":
        return f"[>] {label}"
    if stage == "end":
        return f"[OK] {label}"
    if stage == "error":
        error = str(event.get("error") or "")
        suffix = f": {error}" if error else ""
        return f"[ERR] {label}{suffix}"
    return f"[*] {label}"


async def run_cli(
    prompt_once: str | None = None,
    single_turn: bool = False,
    skill_root_dirs: list[Path] | None = None,
) -> None:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    logger.info("Starting agent...")

    voice_manager = VoiceManager()
    base_config = load_base_config()

    async with AsyncClient(verify=False) as http_client:
        main_agent = MainAgent.create(
            base_config,
            http_client,
            skill_root_dirs=skill_root_dirs,
        )

        def emit_tool_event(event: dict) -> None:
            try:
                print("\n[TOOL] " + _format_tool_line(event), flush=True)
            except Exception as exc:
                logger.debug(f"Failed to print tool event: {exc}")

        main_agent.set_tool_event_callback(emit_tool_event)

        chat_history: list[ModelRequest | ModelResponse] | None = None
        history: list[tuple[str, str]] = []
        
        # 創建共用的指令處理器
        command_handler = CommandHandler(
            main_agent=main_agent,
            history=history,
            output_callback=print,
        )

        async with AsyncExitStack() as stack:
            # MCP servers are run by the main agent (contains browser tools)
            mcp_started = False
            try:
                await stack.enter_async_context(main_agent.agent.run_mcp_servers())
            except Exception as exc:  # pragma: no cover - best effort when MCP fails
                logger.warning("MCP browser tools failed to start; continuing without them.", exc_info=exc)
                # Keep CLI behavior consistent with GUI: remove unavailable MCP toolsets
                # so the agent won't repeatedly attempt calls to broken MCP servers.
                try:
                    main_agent.agent._user_toolsets = []
                    logger.info("Cleared MCP toolsets from agent to prevent tool call failures")
                except Exception as clear_exc:
                    logger.debug("Failed to clear MCP toolsets in CLI", exc_info=clear_exc)
            else:
                mcp_started = True

            ready_msg = "\nAgent ready. Type /help for commands."
            if not mcp_started:
                ready_msg = (
                    "\nAgent ready (browser tools disabled). Type /help for commands."
                    "\nNote: install Playwright via `uv run playwright install` if you want browser tooling."
                )
            print(ready_msg)
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
                user_input = input("輸入文字或按Enter啟動語音辨識> ").strip()
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
                if user_input.startswith(COMMAND_PREFIX):
                    action = command_handler.handle(user_input)
                    if action == "__exit__":
                        return
                    if action:
                        user_input = action
                    else:
                        return
                if user_input.lower() in ["exit", "quit"]:
                    return
                command_handler.update_last_prompt(user_input)
                await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                update_history()
                reply = main_agent._last_assistant_reply or ""
                command_handler.update_last_reply(reply)
                history.append((user_input, reply))
                return

            while True:
                try:
                    user_input = read_input_once()
                    if not user_input:
                        continue
                    if user_input.startswith(COMMAND_PREFIX):
                        action = command_handler.handle(user_input)
                        if action == "__exit__":
                            break
                        if action:
                            user_input = action
                        else:
                            continue
                    if user_input.lower() in ["exit", "quit"]:
                        break
                    command_handler.update_last_prompt(user_input)
                    await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                    update_history()
                    reply = main_agent._last_assistant_reply or ""
                    command_handler.update_last_reply(reply)
                    history.append((user_input, reply))
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error("Error: " + str(exc))
                    print("\nError: " + str(exc) + "\n")
