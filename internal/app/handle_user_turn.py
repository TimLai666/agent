from __future__ import annotations

from collections.abc import Awaitable, Callable

from internal.core.session.prompt_assembler import assemble_system_prompt
from internal.core.session.session_mode import resolve_session_mode


async def handle_user_turn(
    user_prompt: str,
    run_main: Callable[[str, str], Awaitable[str]],
) -> str:
    mode = resolve_session_mode(user_prompt)
    system_prompt = assemble_system_prompt(mode)
    return await run_main(system_prompt, user_prompt)
