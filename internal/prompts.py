from pathlib import Path

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
