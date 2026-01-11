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
COMMAND_PREFIX = "/"


def _format_tools_list(main_agent: MainAgent) -> str:
    tools_meta = main_agent._get_function_tools()
    if not tools_meta:
        return "No tools registered."
    lines = ["Available tools:"]
    for name, tool in tools_meta.items():
        doc = tool.description.splitlines()[0] if tool.description else ""
        lines.append(f"- {name}: {doc}" if doc else f"- {name}")
    return "\n".join(lines)


def _format_sub_agents_list(main_agent: MainAgent) -> str:
    specs = main_agent.list_sub_agents()
    if not specs:
        return "No sub-agents registered."
    lines = ["Available sub-agents:"]
    for spec in specs:
        name = spec.get("name", "")
        desc = spec.get("description", "")
        if desc:
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def _format_skills_list(main_agent: MainAgent) -> str:
    """Format list of available skills."""
    if not main_agent.skills or main_agent.skills.is_empty():
        return "No skills loaded."

    specs = main_agent.skills.list_summaries()
    lines = [f"Available skills ({len(specs)} total):"]
    for spec in specs:
        name = spec.get("name", "")
        desc = spec.get("description", "")
        if desc:
            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def _format_skill_info(main_agent: MainAgent, skill_name: str) -> str:
    """Format detailed information about a specific skill."""
    if not main_agent.skills or main_agent.skills.is_empty():
        return "No skills loaded."

    skill = main_agent.skills.get_skill(skill_name)
    if not skill:
        return f"Skill '{skill_name}' not found. Use /skills to see available skills."

    lines = [
        f"Skill: {skill.name}",
        f"Description: {skill.description}",
        "",
    ]

    # Show resources if available
    if skill.resources.has_resources():
        lines.append("Bundled resources:")
        resources = skill.resources.list_all()
        if resources.get("scripts"):
            lines.append(f"  Scripts: {', '.join(resources['scripts'])}")
        if resources.get("references"):
            lines.append(f"  References: {', '.join(resources['references'])}")
        if resources.get("assets"):
            lines.append(f"  Assets: {', '.join(resources['assets'])}")
        lines.append("")

    # Show content preview
    content_preview = skill.content[:500] if len(skill.content) > 500 else skill.content
    lines.append("Content preview:")
    lines.append("-" * 40)
    lines.append(content_preview)
    if len(skill.content) > 500:
        lines.append(f"... ({len(skill.content) - 500} more characters)")
    lines.append("-" * 40)

    return "\n".join(lines)


def _test_skill_matching(main_agent: MainAgent, prompt: str) -> str:
    """Test which skills would be matched for a given prompt."""
    if not main_agent.skills or main_agent.skills.is_empty():
        return "No skills loaded."

    skills = main_agent.skills.find_relevant_skills(prompt, max_skills=5)

    if not skills:
        return f"No skills matched for prompt: '{prompt}'"

    lines = [
        f"Testing prompt: '{prompt}'",
        f"Matched {len(skills)} skill(s):",
        "",
    ]

    for i, skill in enumerate(skills, 1):
        lines.append(f"{i}. {skill.name}")
        lines.append(f"   {skill.short_description()}")
        lines.append("")

    return "\n".join(lines)


def _handle_skills_command(args: list[str], main_agent: MainAgent) -> None:
    """Handle /skills command and its subcommands."""
    if not args or args[0] == "list":
        # /skills or /skills list
        print(_format_skills_list(main_agent))
    elif args[0] == "info":
        # /skills info <name>
        if len(args) < 2:
            print("Usage: /skills info <skill-name>")
            return
        skill_name = args[1]
        print(_format_skill_info(main_agent, skill_name))
    elif args[0] == "test":
        # /skills test <prompt>
        if len(args) < 2:
            print("Usage: /skills test <prompt>")
            return
        test_prompt = " ".join(args[1:])
        print(_test_skill_matching(main_agent, test_prompt))
    elif args[0] == "reload":
        # /skills reload
        try:
            from internal.skills_loader import load_skill_registry
            main_agent.skills = load_skill_registry()
            count = len(main_agent.skills.list_names())
            print(f"Skills reloaded successfully. Loaded {count} skills.")
        except Exception as e:
            print(f"Failed to reload skills: {e}")
    else:
        print(f"Unknown skills command: {args[0]}")
        print("Available commands:")
        print("  /skills [list]        List all available skills")
        print("  /skills info <name>   Show detailed info about a skill")
        print("  /skills test <prompt> Test which skills match a prompt")
        print("  /skills reload        Reload all skills from disk")


def _format_history(history: list[tuple[str, str]], limit: int) -> str:
    if not history:
        return "No conversation history yet."
    recent = history[-limit:]
    lines: list[str] = []
    for idx, (user_text, assistant_text) in enumerate(recent, start=1):
        lines.append(f"[{idx}] User: {user_text}")
        if assistant_text:
            lines.append(f"[{idx}] Assistant: {assistant_text}")
    return "\n".join(lines)


def _print_help() -> None:
    print(
        "\n".join(
            [
                "Commands:",
                "/help              Show this help.",
                "/exit, /quit       Exit the session.",
                "/clear             Clear the screen.",
                "/history [N]       Show last N turns (default 5).",
                "/last              Show last assistant reply.",
                "/retry             Re-run the last user prompt.",
                "/tools             List available tools.",
                "/subagents         List available sub-agents.",
                "/skills [list]     List available skills.",
                "/skills info <name> Show detailed info about a skill.",
                "/skills test <text> Test which skills match a prompt.",
                "/skills reload     Reload all skills from disk.",
            ]
        )
    )


def _handle_command(
    command: str,
    main_agent: MainAgent,
    history: list[tuple[str, str]],
) -> str | None:
    parts = command.strip().split()
    name = parts[0].lower()
    args = parts[1:]

    if name in ("/exit", "/quit"):
        return "__exit__"
    if name == "/help":
        _print_help()
        return None
    if name == "/clear":
        print("\n" * 80)
        return None
    if name == "/history":
        limit = 5
        if args and args[0].isdigit():
            limit = max(1, int(args[0]))
        print(_format_history(history, limit))
        return None
    if name == "/last":
        last_reply = getattr(main_agent, "_last_assistant_reply", None)
        print(last_reply or "No assistant reply yet.")
        return None
    if name == "/retry":
        last_prompt = getattr(main_agent, "_last_user_prompt", None)
        if not last_prompt:
            print("No previous prompt to retry.")
            return None
        return last_prompt
    if name == "/tools":
        print(_format_tools_list(main_agent))
        return None
    if name == "/subagents":
        print(_format_sub_agents_list(main_agent))
        return None
    if name == "/skills":
        _handle_skills_command(args, main_agent)
        return None

    print("Unknown command. Type /help for options.")
    return None


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
        history: list[tuple[str, str]] = []

        async with AsyncExitStack() as stack:
            # MCP servers are run by the main agent (contains browser tools)
            mcp_started = False
            try:
                await stack.enter_async_context(main_agent.agent.run_mcp_servers())
            except Exception as exc:  # pragma: no cover - best effort when MCP fails
                logger.warning("MCP browser tools failed to start; continuing without them.", exc_info=exc)
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
                    action = _handle_command(user_input, main_agent, history)
                    if action == "__exit__":
                        return
                    if action:
                        user_input = action
                    else:
                        return
                if user_input.lower() in ["exit", "quit"]:
                    return
                await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                update_history()
                history.append((user_input, main_agent._last_assistant_reply or ""))
                return

            while True:
                try:
                    user_input = read_input_once()
                    if not user_input:
                        continue
                    if user_input.startswith(COMMAND_PREFIX):
                        action = _handle_command(user_input, main_agent, history)
                        if action == "__exit__":
                            break
                        if action:
                            user_input = action
                        else:
                            continue
                    if user_input.lower() in ["exit", "quit"]:
                        break
                    await stream_print(main_agent.run_stream(user_input, message_history=chat_history))
                    update_history()
                    history.append((user_input, main_agent._last_assistant_reply or ""))
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error("Error: " + str(exc))
                    print("\nError: " + str(exc) + "\n")
