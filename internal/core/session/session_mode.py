from __future__ import annotations

from internal.core.tasks.task_types import SessionMode


def resolve_session_mode(prompt: str) -> SessionMode:
    lowered = prompt.lower()
    coordinator_hints = ["coordinate", "orchestrate", "分工", "協調", "派工"]
    if any(hint in lowered for hint in coordinator_hints):
        return "coordinator"
    return "normal"
