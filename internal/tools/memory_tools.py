"""Memory read/write tools for the agent.

These tools are registered directly on the agent instance and require no
permission confirmation — memory access is always auto-approved.
"""
from __future__ import annotations

from pydantic_ai import Agent

from internal.memory import MEMORY_FILES, MemoryManager


def add_memory_tools(agent: Agent, memory_manager: MemoryManager) -> None:
    """Register memory_read and memory_write tools on the agent."""

    @agent.tool_plain
    def memory_read(file_name: str) -> str:
        """Read a persistent memory file.

        Args:
            file_name: One of ME.md, USER.md, TOOLS.md, MEMORY.md, TODO.md
        """
        # Validate first so an unknown name surfaces an error rather than a
        # misleading "(empty)" message.
        try:
            canonical = memory_manager._validate_name(file_name)  # noqa: SLF001
        except ValueError as exc:
            return f"Error: {exc}"
        content = memory_manager.read_file(canonical)
        if not content:
            return f"(empty — {canonical} has no content yet)"
        return content

    @agent.tool_plain
    def memory_write(file_name: str, content: str) -> str:
        """Write/update a persistent memory file (replaces full content).

        Guidelines:
        - Keep all entries concise and point-form (no long paragraphs)
        - When updating, read first and consolidate/merge related entries
        - Remove entries that are clearly outdated or superseded
        - Valid file names: ME.md, USER.md, TOOLS.md, MEMORY.md, TODO.md

        Args:
            file_name: Target memory file name
            content: New full content for the file
        """
        try:
            memory_manager.write_file(file_name, content)
            return f"Memory updated: {file_name}"
        except ValueError as exc:
            return f"Error: {exc}"
