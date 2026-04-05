from __future__ import annotations

from internal.core.tasks.task_types import SessionMode


def resolve_session_mode(_prompt: str) -> SessionMode:
    return "coordinator"
