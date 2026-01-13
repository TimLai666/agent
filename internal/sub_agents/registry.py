from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Awaitable, Callable, Optional, Any

from httpx import AsyncClient
from pydantic_ai import Agent

from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT, build_runtime_instructions
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.set_tools import add_all_tools
from internal.co_agents.philosopher import PhilosopherCoAgent
from internal.sub_agents.base import SubAgent
from internal.mcp_server_list import all_mcp_servers

SUB_AGENTS_DIR = Path(__file__).resolve().parent
_MENTION_RE = re.compile(r"(?<![\\w`])@(\.?[^\s`,.]*(?:\.[^\s`,.]+)*)")


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    color: str
    tools: tuple[str, ...]
    prompt: str
    path: Path

    def short_description(self) -> str:
        if not self.description:
            return ""
        if "\\n" in self.description:
            return self.description.split("\\n", 1)[0].strip()
        if "\n" in self.description:
            return self.description.split("\n", 1)[0].strip()
        return self.description.strip()


class SubAgentRegistry:
    def __init__(
        self, specs: dict[str, SubAgentSpec], agents: dict[str, SubAgent]
    ) -> None:
        self._specs = specs
        self._agents = agents

    def is_empty(self) -> bool:
        return not self._specs

    def list_specs(self) -> list[SubAgentSpec]:
        return sorted(self._specs.values(), key=lambda spec: spec.name)

    def list_names(self) -> list[str]:
        return [spec.name for spec in self.list_specs()]

    def list_summaries(self) -> list[dict[str, str]]:
        return [
            {"name": spec.name, "description": spec.short_description()}
            for spec in self.list_specs()
        ]

    def resolve_name(self, name: str) -> str | None:
        if not name:
            return None
        key = _normalize_name(name)
        if key in self._specs:
            return key
        return None

    def get_spec(self, name: str) -> SubAgentSpec | None:
        key = self.resolve_name(name)
        if not key:
            return None
        return self._specs.get(key)

    def get_agent(self, name: str) -> SubAgent | None:
        key = self.resolve_name(name)
        if not key:
            return None
        return self._agents.get(key)

    def register_tools(self, agent: Agent) -> None:
        if not self._specs:
            return
        for spec in self.list_specs():
            tool = _build_subagent_tool(spec, self)
            description = spec.short_description() or "Use this sub-agent to handle specific tasks."
            agent.tool_plain(name=spec.name, description=description)(tool)

    def extract_mentions(self, text: str) -> tuple[str, list[str]]:
        if not text:
            return text, []
        matches: list[str] = []
        seen: set[str] = set()
        for match in _MENTION_RE.finditer(text):
            raw = match.group(1)
            name = self.resolve_name(raw)
            if not name or name in seen:
                continue
            seen.add(name)
            matches.append(name)
        if not matches:
            return text, []
        cleaned = _strip_agent_mentions(text, set(matches))
        return cleaned, matches


def load_sub_agent_registry(
    base_config: AgentConfig,
    env: dict[str, str],
    http_client: AsyncClient,
    root_dir: Path | None = None,
    philosopher: PhilosopherCoAgent | None = None,
    skills: Optional[Any] = None,
) -> SubAgentRegistry:
    specs = load_sub_agent_specs(root_dir or SUB_AGENTS_DIR)
    if not specs:
        return SubAgentRegistry({}, {})

    # Sub-agents inherit MAIN_* for base settings, but MODEL_TEMPERATURE is per-SUB only.
    config = load_agent_config_chain(["MAIN", "SUB"], base_config, env)
    # Temperature: if SUB_MODEL_TEMPERATURE is specified, use it; otherwise default to 1.0 (do not use MAIN_MODEL_TEMPERATURE).
    sub_temp_raw = env.get("SUB_MODEL_TEMPERATURE")
    if sub_temp_raw and sub_temp_raw.strip() != "":
        try:
            sub_temp = float(sub_temp_raw)
        except ValueError:
            logger.warning(f"Invalid SUB_MODEL_TEMPERATURE '{sub_temp_raw}', using default 1.0.")
            sub_temp = 1.0
    else:
        sub_temp = 1.0
    config = AgentConfig(
        name=config.name,
        base_url=config.base_url,
        api_key=config.api_key,
        model_name=config.model_name,
        temperature=sub_temp,
    )
    model = create_openai_model(config, http_client)

    spec_map: dict[str, SubAgentSpec] = {}
    agents: dict[str, SubAgent] = {}
    for spec in specs:
        key = _normalize_name(spec.name)
        if key in spec_map:
            logger.warning(
                "Duplicate sub-agent name '%s' from %s; skipping",
                spec.name,
                spec.path,
            )
            continue
        prompt_text = spec.prompt.strip()
        if philosopher:
            prompt_text = (
                f"{prompt_text}\n\n"
                "When you need broader reasoning or planning guidance, "
                "call the `ask_philosopher` tool to discuss the request with the philosopher co-agent."
            )
        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=build_runtime_instructions(prompt_text),
            tools=[],
            model_settings={"temperature": config.temperature},
            toolsets=all_mcp_servers,
        )
        add_all_tools(
            agent,
        )
        if philosopher:
            _register_philosopher_tools(agent, philosopher)
        # Register skill tool if skills available
        if skills:
            from internal.tools.skill_tools import register_skill_tool
            register_skill_tool(agent, skills)
        spec_map[key] = spec
        agents[key] = SubAgent(agent, philosopher=philosopher, skills=skills)

    return SubAgentRegistry(spec_map, agents)


def load_sub_agent_specs(root_dir: Path) -> list[SubAgentSpec]:
    if not root_dir.exists():
        logger.warning("Sub-agent directory not found: %s", root_dir)
        return []

    specs: list[SubAgentSpec] = []
    for path in root_dir.rglob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read sub-agent file: %s", path)
            continue

        meta, body = _split_frontmatter(raw)
        name = (meta.get("name") or path.stem).strip()
        if not name:
            logger.warning("Sub-agent file missing name: %s", path)
            continue

        prompt = body.strip()
        if not prompt:
            logger.warning("Sub-agent file missing prompt body: %s", path)
            continue

        description = (meta.get("description") or "").strip()
        color = (meta.get("color") or "").strip()
        tools = tuple(_parse_tools(meta.get("tools", "")))

        specs.append(
            SubAgentSpec(
                name=name,
                description=description,
                color=color,
                tools=tools,
                prompt=prompt,
                path=path,
            )
        )

    specs.sort(key=lambda spec: spec.name)
    return specs


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text

    front_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])
    return _parse_frontmatter_lines(front_lines), body


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in lines:
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            meta[key] = value
    return meta


def _parse_tools(raw: str) -> list[str]:
    if not raw:
        return []
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    tools = [item.strip() for item in value.split(",") if item.strip()]
    return tools


def _strip_agent_mentions(text: str, names: set[str]) -> str:
    if not text or not names:
        return text
    parts: list[str] = []
    last = 0
    for match in _MENTION_RE.finditer(text):
        raw = match.group(1)
        name = _normalize_name(raw)
        if name in names:
            parts.append(text[last:match.start()])
            last = match.end()
    parts.append(text[last:])
    cleaned = "".join(parts)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _normalize_name(name: str) -> str:
    cleaned = []
    for char in name.strip().lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {"-", "_", " "}:
            cleaned.append("-")
    normalized = "".join(cleaned)
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-")


def _build_philosopher_tool(
    tool_name: str, philosopher: PhilosopherCoAgent
) -> Callable[[str], Awaitable[str]]:
    async def tool(question: str) -> str:
        return await philosopher.run(question)

    tool.__name__ = tool_name
    tool.__doc__ = "Ask the philosopher co-agent for deeper reasoning."
    return tool


def _register_philosopher_tools(
    agent: Agent, philosopher: PhilosopherCoAgent
) -> None:
    for tool_name in ("ask_philosopher", "philosopher", "philosopher-co-agent"):
        agent.tool_plain(_build_philosopher_tool(tool_name, philosopher))


def _build_subagent_tool(
    spec: SubAgentSpec, registry: SubAgentRegistry
) -> Callable[[str], Awaitable[str]]:
    normalized_name = _normalize_name(spec.name) or spec.name


    async def tool(prompt: str) -> str:
        agent = registry.get_agent(normalized_name)
        if not agent:
            return f"Sub-agent '{spec.name}' not available yet."
        return await agent.run(prompt)

    tool.__name__ = normalized_name
    desc = spec.short_description() or "Use this sub-agent to handle specific tasks."
    tool.__doc__ = desc
    return tool
