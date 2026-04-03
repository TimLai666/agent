"""Centralized filesystem paths used by the agent runtime."""

from pathlib import Path


TIM_AGENT_ROOT = Path.home() / ".tim-agent"
TIM_AGENT_CONFIG_DIR = TIM_AGENT_ROOT / "config"
TIM_AGENT_SKILLS_DIR = TIM_AGENT_ROOT / "skills"
TIM_AGENT_SANDBOX_DIR = TIM_AGENT_ROOT / "sandbox"
