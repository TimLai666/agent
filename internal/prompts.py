from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import sys

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompts() -> dict[str, str]:
    prompts: dict[str, str] = {}
    if not PROMPTS_DIR.exists():
        return prompts

    for path in PROMPTS_DIR.glob("*.md"):
        key = path.stem.upper()
        prompts[key] = path.read_text(encoding="utf-8").strip()

    return prompts


_PROMPTS = _load_prompts()


def get_prompt(key: str, default: str = "") -> str:
    return _PROMPTS.get(key.upper(), default)


def _build_system_prompt() -> str:
    return _PROMPTS.get("SYSTEM_PROMPT", "").strip()


SYSTEM_PROMPT: str = _build_system_prompt()

_LOCAL_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CONTEXT.md")
_KEYWORD_TRIGGER_FILE = PROMPTS_DIR / "KEYWORD_TRIGGERS.json"


def _find_upwards(start_dir: Path, filename: str) -> Path | None:
    if not start_dir:
        return None
    current = start_dir if start_dir.is_dir() else start_dir.parent
    for directory in (current, *current.parents):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def _find_git_root(start_dir: Path) -> Path | None:
    if not start_dir:
        return None
    current = start_dir if start_dir.is_dir() else start_dir.parent
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


def load_local_instructions(start_dir: Path | None = None) -> list[str]:
    base = start_dir or Path.cwd()
    instructions: list[str] = []
    for filename in _LOCAL_INSTRUCTION_FILES:
        path = _find_upwards(base, filename)
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if content:
            instructions.append(f"指示來源：{path}\n{content}")
    return instructions


def build_environment_context(start_dir: Path | None = None) -> str:
    base = start_dir or Path.cwd()
    git_root = _find_git_root(base)
    lines = [
        "執行環境：",
        f"- 工作目錄：{base}",
        f"- Git 專案：{'是' if git_root else '否'}",
    ]
    if git_root:
        lines.append(f"- Git 根目錄：{git_root}")
    lines.append(f"- 平台：{sys.platform}")
    lines.append(f"- 日期：{date.today().isoformat()}")
    return "\n".join(lines)


def build_runtime_instructions(base_instructions: str, start_dir: Path | None = None) -> str:
    parts: list[str] = []
    base = (base_instructions or "").strip()
    if base:
        parts.append(base)
    context = build_environment_context(start_dir)
    if context:
        parts.append(context)
    local_instructions = load_local_instructions(start_dir)
    if local_instructions:
        parts.append("\n\n".join(local_instructions))
    return "\n\n".join(parts)


@lru_cache(maxsize=1)
def load_keyword_triggers() -> list[dict[str, str]]:
    if not _KEYWORD_TRIGGER_FILE.exists():
        return []
    try:
        raw = _KEYWORD_TRIGGER_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return []

    triggers: list[dict[str, str]] = []
    for item in data.get("triggers", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        pattern = str(item.get("pattern", "")).strip()
        inject = str(item.get("inject", "")).strip()
        position = str(item.get("position", "prefix")).strip().lower()
        if not name or not pattern or not inject:
            continue
        if position not in {"prefix", "suffix"}:
            position = "prefix"
        triggers.append(
            {
                "name": name,
                "pattern": pattern,
                "inject": inject,
                "position": position,
            }
        )
    return triggers
