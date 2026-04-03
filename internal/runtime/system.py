import warnings
from contextlib import AsyncExitStack
from pathlib import Path

from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.runtime.stream_printer import stream_print

from internal.agents import MainAgent
from internal.app.handle_user_turn import create_runtime
from internal.cli import confirm
from internal.logger import logger
from internal.services.agent_factory import load_base_config
from internal.services import config_webui
from internal.services import config_cli
from internal.services.config_db import (
    list_agent_configs,
    list_mcp_tools,
    list_providers,
    list_remote_mcps,
)
from internal.services.voice_manager import VoiceManager
from internal.command_handler import CommandHandler
from internal.compaction import (
    CompactCoordinator,
    ConversationState,
    MAX_CONTEXT_TOKENS,
    recalc_total_tokens,
)

COMMAND_PREFIX = "/"


def _is_config_empty() -> bool:
    """Return True when all configurable sections are empty."""
    try:
        has_providers = bool(list_providers())
        has_agents = bool(list_agent_configs())
        has_mcp_tools = bool(list_mcp_tools())
        has_remote_mcps = bool(list_remote_mcps())
        return not (has_providers or has_agents or has_mcp_tools or has_remote_mcps)
    except Exception:
        logger.exception("Failed to evaluate config emptiness in CLI")
        return False


def _guide_user_for_empty_config() -> None:
    """Show onboarding guidance and optionally open interactive config setup."""
    print("\n[設定引導] 尚未偵測到任何 Provider/Agent 設定。")
    print("你可以使用以下方式完成初始設定：")
    print("  1. 互動式設定選單：/config")
    print("  2. Web 設定頁：/config-web")

    if confirm("是否現在開啟互動式設定選單？", "Y"):
        try:
            config_cli.cmd_config_menu()
        except Exception as exc:
            logger.error("Failed to open config menu from CLI onboarding", exc_info=exc)
            print(f"⚠️ 無法開啟設定選單：{exc}")

    if _is_config_empty():
        print("\n⚠️ 目前仍未完成設定，模型呼叫可能失敗。")
        print("   你可隨時輸入 /config 或 /config-web 進行設定。")
    else:
        print("\n✅ 偵測到有效設定，已可開始對話。")


def _summarize_exception(exc: Exception) -> str:
    """Extract a concise root-cause message from nested exception groups."""
    current: BaseException | None = exc
    visited: set[int] = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, (list, tuple)) and nested:
            current = nested[0]
            continue
        if getattr(current, "__cause__", None) is not None:
            current = current.__cause__
            continue
        if getattr(current, "__context__", None) is not None:
            current = current.__context__
            continue
        break

    if current is None:
        return "Unknown error"
    return f"{type(current).__name__}: {current}"


def _format_tool_line(event: dict) -> str:
    tool = str(event.get("tool") or "tool")
    args = event.get("args") or ()
    kwargs = event.get("kwargs") or {}
    stage = str(event.get("stage") or "")
    is_skill_call = tool == "use_skill"
    explicit_skill_name = str(event.get("skill_name") or "").strip()

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
        if not skill_name and explicit_skill_name:
            skill_name = explicit_skill_name
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
    if is_skill_call:
        if stage == "skill-activated":
            return f"[SKILL] {label}"
        # Suppress use_skill start/end/error lines to keep only one [SKILL] hint.
        return ""

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
        orchestration_runtime = create_runtime(main_agent)

        def reload_skills_from_webui() -> dict[str, object]:
            from internal.skills_loader import load_skill_registry

            root_dirs = getattr(main_agent, "skill_root_dirs", None)
            main_agent.skills = load_skill_registry(root_dirs=root_dirs)
            count = len(main_agent.skills.list_names())
            return {
                "success": True,
                "count": count,
                "message": f"Skills 已自動重新載入（{count} 個）",
            }

        config_webui.register_skills_reload_handler(reload_skills_from_webui)

        def emit_tool_event(event: dict) -> None:
            try:
                line = _format_tool_line(event)
                if not line:
                    return
                print("\n[TOOL] " + line, flush=True)
            except Exception as exc:
                logger.debug(f"Failed to print tool event: {exc}")

        main_agent.set_tool_event_callback(emit_tool_event)

        chat_history: list[ModelRequest | ModelResponse] | None = None
        conversation_state = ConversationState(fullMessages=[])
        compact_coordinator = CompactCoordinator(runner=main_agent.run_compaction_subagent)
        history: list[tuple[str, str]] = []
        
        # 創建共用的指令處理器
        command_handler = CommandHandler(
            main_agent=main_agent,
            history=history,
            output_callback=print,
        )

        # CLI onboarding: guide users when configuration is completely empty.
        if prompt_once is None and not single_turn and _is_config_empty():
            _guide_user_for_empty_config()

        try:
            async with AsyncExitStack() as stack:
                # MCP servers are run by the main agent (contains browser tools)
                mcp_started = False
                try:
                    await stack.enter_async_context(main_agent.agent.run_mcp_servers())
                except Exception as exc:  # pragma: no cover - best effort when MCP fails
                    reason = _summarize_exception(exc)
                    logger.warning(
                        "MCP browser tools failed to start; continuing without them. Root cause: %s",
                        reason,
                    )
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
                    "\nAgent ready. Type /help for commands."
                    "\nNote: install Playwright via `uv run playwright install` if you want browser tooling."
                )
            print(ready_msg)

            if prompt_once is not None:
                user_input = prompt_once.strip()
                if not user_input:
                    return
                await stream_print(
                    orchestration_runtime.handle_user_turn_stream(
                        user_input,
                        message_history=chat_history,
                    )
                )
                return

            async def update_history() -> None:
                nonlocal chat_history
                try:
                    if getattr(main_agent, "_last_messages", None):
                        conversation_state.fullMessages = (
                            main_agent._last_messages if main_agent._last_messages is not None else []
                        )
                        conversation_state.totalTokens = recalc_total_tokens(conversation_state.fullMessages)
                        updated_state = await compact_coordinator.maybeCompact(conversation_state)
                        conversation_state.fullMessages = updated_state.fullMessages
                        conversation_state.recentMessages = updated_state.recentMessages
                        conversation_state.compressedSummary = updated_state.compressedSummary
                        conversation_state.totalTokens = updated_state.totalTokens
                        conversation_state.lastCompactedMessageId = updated_state.lastCompactedMessageId
                        chat_history = updated_state.fullMessages
                    else:
                        chat_history = None
                except Exception:
                    chat_history = None

            async def force_compact() -> tuple[bool, int, int]:
                nonlocal chat_history
                base_messages = chat_history or getattr(main_agent, "_last_messages", None) or []
                if not base_messages:
                    return False, 0, 0

                conversation_state.fullMessages = list(base_messages)
                before_count = len(conversation_state.fullMessages)
                conversation_state.totalTokens = max(
                    recalc_total_tokens(conversation_state.fullMessages),
                    MAX_CONTEXT_TOKENS,
                )
                updated_state = await compact_coordinator.maybeCompact(conversation_state)
                conversation_state.fullMessages = updated_state.fullMessages
                conversation_state.recentMessages = updated_state.recentMessages
                conversation_state.compressedSummary = updated_state.compressedSummary
                conversation_state.totalTokens = updated_state.totalTokens
                conversation_state.lastCompactedMessageId = updated_state.lastCompactedMessageId
                chat_history = updated_state.fullMessages
                after_count = len(chat_history)
                return after_count < before_count, before_count, after_count

            def clear_context() -> None:
                nonlocal chat_history, conversation_state
                chat_history = None
                conversation_state = ConversationState(fullMessages=[])
                command_handler.clear_context_state()
                history.clear()
                main_agent._last_messages = None
                main_agent._last_assistant_reply = None

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
                    if action == "__clear_context__":
                        clear_context()
                        print("已清空對話 context。")
                        return
                    if action == "__compact__":
                        changed, before, after = await force_compact()
                        if changed:
                            print(f"已執行壓縮：訊息數 {before} -> {after}")
                        else:
                            print("已嘗試壓縮，但目前可壓縮內容不足（需要超過最近保留訊息量）。")
                        return
                    if action:
                        user_input = action
                    else:
                        return
                if user_input.lower() in ["exit", "quit"]:
                    return
                command_handler.update_last_prompt(user_input)
                await stream_print(
                    orchestration_runtime.handle_user_turn_stream(
                        user_input,
                        message_history=chat_history,
                    )
                )
                await update_history()
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
                        if action == "__clear_context__":
                            clear_context()
                            print("已清空對話 context。")
                            continue
                        if action == "__compact__":
                            changed, before, after = await force_compact()
                            if changed:
                                print(f"已執行壓縮：訊息數 {before} -> {after}")
                            else:
                                print("已嘗試壓縮，但目前可壓縮內容不足（需要超過最近保留訊息量）。")
                            continue
                        if action:
                            user_input = action
                        else:
                            continue
                    if user_input.lower() in ["exit", "quit"]:
                        break
                    command_handler.update_last_prompt(user_input)
                    await stream_print(
                        orchestration_runtime.handle_user_turn_stream(
                            user_input,
                            message_history=chat_history,
                        )
                    )
                    await update_history()
                    reply = main_agent._last_assistant_reply or ""
                    command_handler.update_last_reply(reply)
                    history.append((user_input, reply))
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error("Error: " + str(exc))
                    print("\nError: " + str(exc) + "\n")
        finally:
            config_webui.register_skills_reload_handler(None)
