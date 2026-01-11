from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from httpx import AsyncClient
from pydantic_ai import Agent

from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT, build_runtime_instructions
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.sub_agents.base import SubAgent

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
) -> SubAgentRegistry:
    specs = load_sub_agent_specs(root_dir or SUB_AGENTS_DIR)
    if not specs:
        return SubAgentRegistry({}, {})

    config = load_agent_config_chain(["MAIN", "SUB"], base_config, env)
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
        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=build_runtime_instructions(spec.prompt),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        spec_map[key] = spec
        agents[key] = SubAgent(agent)

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
