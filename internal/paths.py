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


DEFAULT_TIM_AGENT_ROOT = _default_agent_root()
DEFAULT_TIM_AGENT_CONFIG_DIR = DEFAULT_TIM_AGENT_ROOT / "config"
DEFAULT_TIM_AGENT_SKILLS_DIR = DEFAULT_TIM_AGENT_ROOT / "skills"
DEFAULT_TIM_AGENT_SANDBOX_DIR = DEFAULT_TIM_AGENT_ROOT / "sandbox"
DEFAULT_TIM_AGENT_MEMORY_DIR = DEFAULT_TIM_AGENT_ROOT / "memory"
DEFAULT_TIM_AGENT_CONVERSATIONS_DIR = DEFAULT_TIM_AGENT_ROOT / "conversations"

_ENV_PATH_OVERRIDDEN = any(
	os.environ.get(name, "").strip()
	for name in (
		"TIM_AGENT_ROOT",
		"TIM_AGENT_CONFIG_DIR",
		"TIM_AGENT_SKILLS_DIR",
		"TIM_AGENT_SANDBOX_DIR",
		"TIM_AGENT_MEMORY_DIR",
		"TIM_AGENT_CONVERSATIONS_DIR",
	)
)
_RUNTIME_PATH_OVERRIDDEN = False

TIM_AGENT_ROOT = _path_from_env("TIM_AGENT_ROOT") or DEFAULT_TIM_AGENT_ROOT
TIM_AGENT_CONFIG_DIR = _path_from_env("TIM_AGENT_CONFIG_DIR") or (TIM_AGENT_ROOT / "config")
TIM_AGENT_SKILLS_DIR = _path_from_env("TIM_AGENT_SKILLS_DIR") or (TIM_AGENT_ROOT / "skills")
TIM_AGENT_SANDBOX_DIR = _path_from_env("TIM_AGENT_SANDBOX_DIR") or (TIM_AGENT_ROOT / "sandbox")
TIM_AGENT_MEMORY_DIR = _path_from_env("TIM_AGENT_MEMORY_DIR") or (TIM_AGENT_ROOT / "memory")
TIM_AGENT_CONVERSATIONS_DIR = _path_from_env("TIM_AGENT_CONVERSATIONS_DIR") or (TIM_AGENT_ROOT / "conversations")


def is_workspace_overridden() -> bool:
	return _ENV_PATH_OVERRIDDEN or _RUNTIME_PATH_OVERRIDDEN


def get_workspace_mode() -> str:
	return "workspace" if is_workspace_overridden() else "sandbox"


def set_runtime_paths(
	*,
	root: str | Path | None = None,
	config_dir: str | Path | None = None,
	skills_dir: str | Path | None = None,
	sandbox_dir: str | Path | None = None,
	memory_dir: str | Path | None = None,
	conversations_dir: str | Path | None = None,
) -> None:
	"""Override runtime paths programmatically.

	This is intended for SDK/programmatic use where callers need to control
	workspace/sandbox directories without relying on process-wide env vars.
	"""

	def _resolve(raw: str | Path | None) -> Path | None:
		if raw is None:
			return None
		return Path(raw).expanduser().resolve()

	global TIM_AGENT_ROOT, TIM_AGENT_CONFIG_DIR, TIM_AGENT_SKILLS_DIR, TIM_AGENT_SANDBOX_DIR, TIM_AGENT_MEMORY_DIR, TIM_AGENT_CONVERSATIONS_DIR
	global _RUNTIME_PATH_OVERRIDDEN

	if any(value is not None for value in (root, config_dir, skills_dir, sandbox_dir, memory_dir, conversations_dir)):
		_RUNTIME_PATH_OVERRIDDEN = True

	resolved_root = _resolve(root)
	if resolved_root is not None:
		TIM_AGENT_ROOT = resolved_root

	resolved_config = _resolve(config_dir)
	resolved_skills = _resolve(skills_dir)
	resolved_sandbox = _resolve(sandbox_dir)
	resolved_memory = _resolve(memory_dir)
	resolved_conversations = _resolve(conversations_dir)

	TIM_AGENT_CONFIG_DIR = resolved_config or (TIM_AGENT_ROOT / "config")
	TIM_AGENT_SKILLS_DIR = resolved_skills or (TIM_AGENT_ROOT / "skills")
	TIM_AGENT_SANDBOX_DIR = resolved_sandbox or (TIM_AGENT_ROOT / "sandbox")
	TIM_AGENT_MEMORY_DIR = resolved_memory or (TIM_AGENT_ROOT / "memory")
	TIM_AGENT_CONVERSATIONS_DIR = resolved_conversations or (TIM_AGENT_ROOT / "conversations")
