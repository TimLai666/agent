"""Persistent memory system for tim-agent.

Manages memory files in a configurable directory (default: ~/.tim-agent/memory/).
Files are kept concise and point-form. The agent reads them at startup and injects
them into each turn's context, and can update them at any time without permission.

Supported files:
  ME.md     - Agent identity and role
  USER.md   - User info and preferences
  TOOLS.md  - Environment tools and configuration
  MEMORY.md - Long-term conversation memory
  TODO.md   - Long-term plans and goals
"""
from __future__ import annotations

from pathlib import Path

MEMORY_FILES = ("ME.md", "USER.md", "TOOLS.md", "MEMORY.md", "TODO.md")

_FILE_LABELS = {
    "ME.md": "Agent Identity & Role",
    "USER.md": "User Info & Preferences",
    "TOOLS.md": "Environment & Tools",
    "MEMORY.md": "Long-term Memory",
    "TODO.md": "Long-term Plans",
}


class MemoryManager:
    """Manages agent persistent memory files.

    Can be disabled or pointed at a custom directory.  Supports being replaced
    by an external MemoryManager instance via the SDK's memory_system parameter.
    """

    def __init__(
        self,
        *,
        memory_dir: str | Path | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        if not enabled:
            self._dir: Path | None = None
            return

        if memory_dir is not None:
            self._dir = Path(memory_dir).expanduser().resolve()
        else:
            from internal.paths import TIM_AGENT_MEMORY_DIR
            self._dir = TIM_AGENT_MEMORY_DIR

        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def memory_dir(self) -> Path | None:
        return self._dir

    def _validate_name(self, name: str) -> str:
        """Normalize and validate a memory file name."""
        if not name.lower().endswith(".md"):
            name = name + ".md"
        name_upper = name.upper()
        if name_upper not in MEMORY_FILES:
            raise ValueError(
                f"Unknown memory file '{name}'. Valid files: {', '.join(MEMORY_FILES)}"
            )
        return name_upper

    def read_file(self, name: str) -> str:
        """Read a memory file. Returns empty string if not found or system disabled."""
        if not self.enabled or self._dir is None:
            return ""
        try:
            name = self._validate_name(name)
        except ValueError:
            return ""
        path = self._dir / name
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def write_file(self, name: str, content: str) -> None:
        """Write a memory file, replacing its full content."""
        if not self.enabled or self._dir is None:
            return
        name = self._validate_name(name)
        path = self._dir / name
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def read_all(self) -> dict[str, str]:
        """Read all non-empty memory files."""
        if not self.enabled or self._dir is None:
            return {}
        result: dict[str, str] = {}
        for fname in MEMORY_FILES:
            content = self.read_file(fname)
            if content:
                result[fname] = content
        return result

    def build_context_block(self) -> str:
        """Build a concise memory context block for injection into each turn's prompt."""
        if not self.enabled or self._dir is None:
            return ""
        all_mem = self.read_all()
        if not all_mem:
            return ""
        parts: list[str] = ["<persistent-memory>"]
        for fname, content in all_mem.items():
            label = _FILE_LABELS.get(fname, fname)
            parts.append(f"### {label} ({fname})\n{content}")
        parts.append(
            "\n[Memory is auto-injected. Use memory_write to update any file. "
            "Keep entries concise and point-form. Merge/remove stale entries when writing.]"
        )
        parts.append("</persistent-memory>")
        return "\n\n".join(parts)
