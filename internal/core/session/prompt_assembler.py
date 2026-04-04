from __future__ import annotations

from internal.core.prompts.coordinator_system_prompt import COORDINATOR_SYSTEM_PROMPT
from internal.core.tasks.task_types import SessionMode


def assemble_system_prompt(_mode: SessionMode) -> str:
    return COORDINATOR_SYSTEM_PROMPT
