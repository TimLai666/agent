"""Centralized filesystem paths used by the agent runtime."""

import os
from pathlib import Path


def _path_from_env(name: str) -> Path | None:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return None
	return Path(raw).expanduser().resolve()


def _default_agent_root() -> Path:
	return (Path.home() / ".tim-agent").resolve()


TIM_AGENT_ROOT = _path_from_env("TIM_AGENT_ROOT") or _default_agent_root()
TIM_AGENT_CONFIG_DIR = _path_from_env("TIM_AGENT_CONFIG_DIR") or (TIM_AGENT_ROOT / "config")
TIM_AGENT_SKILLS_DIR = _path_from_env("TIM_AGENT_SKILLS_DIR") or (TIM_AGENT_ROOT / "skills")
TIM_AGENT_SANDBOX_DIR = _path_from_env("TIM_AGENT_SANDBOX_DIR") or (TIM_AGENT_ROOT / "sandbox")
