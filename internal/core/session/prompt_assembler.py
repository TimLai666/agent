from __future__ import annotations

from internal.core.prompts.coordinator_system_prompt import COORDINATOR_SYSTEM_PROMPT
from internal.core.prompts.main_system_prompt import MAIN_SYSTEM_PROMPT
from internal.core.tasks.task_types import SessionMode


def assemble_system_prompt(mode: SessionMode) -> str:
    if mode == "coordinator":
        return COORDINATOR_SYSTEM_PROMPT
    return MAIN_SYSTEM_PROMPT
