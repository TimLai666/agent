from functools import lru_cache
from pathlib import Path
import re
import sys

from internal.paths import TIM_AGENT_SANDBOX_DIR

# 系統名稱配置（避免注入特定廠商或模型身分）
SYSTEM_NAME = "Assistant"

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompts() -> dict[str, str]:
    """載入所有 prompts，包含根目錄和 system-prompts 子目錄。

    根目錄的檔案：key = 檔名大寫（例如 SYSTEM_PROMPT）
    system-prompts 的檔案：key = system_prompts.檔名（例如 system_prompts.agent_prompt_explore）
    """
    prompts: dict[str, str] = {}
    if not PROMPTS_DIR.exists():
        return prompts

    # 載入根目錄的 prompts
    for path in PROMPTS_DIR.glob("*.md"):
        key = path.stem.upper()
        prompts[key] = path.read_text(encoding="utf-8").strip()

    # 載入 system-prompts 子目錄
    system_prompts_dir = PROMPTS_DIR / "system-prompts"
    if system_prompts_dir.exists():
        for path in system_prompts_dir.glob("*.md"):
            # 使用小寫並保留連字符，以 system_prompts. 為前綴
            key = f"system_prompts.{path.stem}"
            prompts[key] = path.read_text(encoding="utf-8").strip()

    return prompts


_PROMPTS = _load_prompts()


def _prompt_key_candidates(prompt_name: str) -> list[str]:
    raw = (prompt_name or "").strip()
    if not raw:
        return []

    names = [raw]
    for candidate in (raw.replace("_", "-"), raw.replace("-", "_")):
        if candidate not in names:
            names.append(candidate)

    candidates: list[str] = []
    for name in names:
        variants = [name, name.lower(), name.upper()]
        if name.startswith("system_prompts."):
            stem = name.removeprefix("system_prompts.")
            variants.extend([
                "system_prompts." + stem,
                "system_prompts." + stem.replace("_", "-"),
            ])
        elif name.startswith("system-prompts."):
            stem = name.removeprefix("system-prompts.")
            variants.extend([
                "system_prompts." + stem,
                "system_prompts." + stem.replace("_", "-"),
            ])
        else:
            variants.extend([
                "system_prompts." + name,
                "system_prompts." + name.replace("_", "-"),
            ])
        for variant in variants:
            if variant not in candidates:
                candidates.append(variant)
    return candidates


def get_prompt(key: str, default: str = "") -> str:
    for candidate in _prompt_key_candidates(key):
        if candidate in _PROMPTS:
            return _PROMPTS[candidate]
    return default


def _build_system_prompt() -> str:
    """建立基礎 system prompt。"""
    return _PROMPTS.get("SYSTEM_PROMPT", "").strip()


def get_system_prompt(prompt_name: str, default: str = "") -> str:
    """取得特定的 system prompt。

    Args:
        prompt_name: prompt 的名稱（例如 "agent_prompt_explore" 或 "system_prompts.agent_prompt_explore"）
        default: 找不到時的預設值

    Returns:
        prompt 內容
    """
    # 如果已經有前綴，直接查詢
    for candidate in _prompt_key_candidates(prompt_name):
        if candidate in _PROMPTS:
            return _PROMPTS[candidate]
    return default


def build_combined_system_prompt(
    base_prompt: str | None = None,
    additional_prompts: list[str] | None = None,
    separator: str = "\n\n---\n\n",
    variables: dict[str, str] | None = None,
) -> str:
    """組合多個 system prompts。

    Args:
        base_prompt: 基礎 prompt（預設使用 SYSTEM_PROMPT）
        additional_prompts: 額外要加入的 prompt 名稱列表
        separator: prompts 之間的分隔符

    Returns:
        組合後的 system prompt
    """
    parts: list[str] = []

    # 添加基礎 prompt（進行變數代換）
    if base_prompt is None:
        base_prompt = _build_system_prompt()
    if base_prompt:
        parts.append(_process_variables(base_prompt, variables=variables))

    # 添加額外的 prompts（進行變數代換）
    if additional_prompts:
        for prompt_name in additional_prompts:
            prompt = get_system_prompt_processed(prompt_name, variables=variables)
            if prompt:
                parts.append(prompt)

    return separator.join(parts)


def list_available_system_prompts() -> list[str]:
    """列出所有可用的 system prompts（僅 system-prompts 子目錄中的）。

    Returns:
        system prompts 名稱列表（不含 "system_prompts." 前綴）
    """
    return [
        key.replace("system_prompts.", "")
        for key in _PROMPTS.keys()
        if key.startswith("system_prompts.")
    ]


def _process_variables(text: str, variables: dict[str, str] | None = None) -> str:
    """處理 prompt 中的變量替換。

    支援的變量格式：
    - ${VARIABLE_NAME}：簡單替換
    - ${FUNCTION_NAME()}：函數調用（移除）

    Args:
        text: 要處理的文本
        variables: 變量映射字典

    Returns:
        處理後的文本
    """
    if not text:
        return text

    # 預設變量映射（針對從 Claude Code 移植的 prompts）
    # 將 Claude Code 的工具名稱映射到我們專案的實際工具名稱
    default_vars = {
        # 系統名稱
        "SYSTEM_NAME": SYSTEM_NAME,
        # 工具名稱（映射到專案實際的工具）
        "TASK_TOOL_NAME": "todo",  # 任務規劃
        "BASH_TOOL_NAME": "run_terminal_command",  # 執行終端命令
        "READ_TOOL_NAME": "run_terminal_command",  # 讀取檔案改由終端命令
        "WRITE_TOOL_NAME": "run_terminal_command",  # 寫檔改由終端命令
        "EDIT_TOOL_NAME": "run_terminal_command",  # 修改改由終端命令
        "GLOB_TOOL_NAME": "run_terminal_command",  # 列檔改由終端命令
        "GREP_TOOL_NAME": "run_terminal_command",  # 搜尋內容改由終端命令
        "SEARCH_TOOL_NAME": "run_terminal_command",  # 搜尋檔案改由終端命令
        "WEBFETCH_TOOL_NAME": "fetch",  # 瀏覽網站內容
        "WEBSEARCH_TOOL_NAME": "web_search",  # 網路搜尋（使用 DuckDuckGo）
        "ASKUSERQUESTION_TOOL_NAME": "ask_user_question",  # 舊版變數名
        "ASK_USER_QUESTION_TOOL_NAME": "ask_user_question",
        "ASK_USER_QUESTION_TOOL": "ask_user_question",
        "EXIT_PLAN_MODE_TOOL_NAME": "exit_plan_mode",
        "EXIT_PLAN_MODE_TOOL_OBJECT_NAME": "exit_plan_mode",
        "TODO_TOOL_NAME": "todo",
        # Agent 類型
        "EXPLORE_AGENT": "explore",  # 探索 agent 類型
        "CLAUDE_CODE_GUIDE_SUBAGENT_TYPE": "guide",  # 指南 agent 類型
        # 配置值
        "MAX_TIMEOUT_MS": "120000",  # 命令超時時間（毫秒）
        "CUSTOM_TIMEOUT_MS": "600000",  # 自定義超時時間（毫秒）
        "MAX_OUTPUT_CHARS": "30000",  # 最大輸出字元數
        # 其他常見變量
        "OUTPUT_STYLE_CONFIG": "",  # 輸出樣式配置
        "SECURITY_POLICY": "",  # 安全政策
        "RUN_IN_BACKGROUND_NOTE": "",  # 背景執行說明
        "BASH_TOOL_EXTRA_NOTES": "",  # Bash 工具額外說明
        "BASH_BACKGROUND_TASK_NOTES_FN": "",  # Bash 背景任務說明
            "SCRATCHPAD_DIR_FN": str(TIM_AGENT_SANDBOX_DIR),  # 沙盒/暫存目錄
        "AGENT_TOOL_USAGE_NOTES": "",  # Agent 工具使用說明
        "TODO_TOOL_OBJECT": "todo",  # 待辦事項工具對象
        "AVAILABLE_TOOLS_SET": "tools",  # 可用工具集合
    }

    # 合併使用者提供的變量
    if variables:
        default_vars.update(variables)

    # 處理函數調用格式 ${FUNCTION_NAME()}
    text = re.sub(r'\$\{([A-Z_]+)\(\)\}', lambda m: default_vars.get(m.group(1), m.group(0)), text)

    # 處理屬性存取格式 ${VAR.name} / ${VAR.agentType}
    text = re.sub(
        r'\$\{([A-Z_]+)\.name\}',
        lambda m: default_vars.get(f"{m.group(1)}_NAME", default_vars.get(m.group(1), m.group(0))),
        text,
    )
    text = re.sub(
        r'\$\{([A-Z_]+)\.agentType\}',
        lambda m: default_vars.get(f"{m.group(1)}_AGENT_TYPE", default_vars.get(m.group(1), m.group(0))),
        text,
    )

    # 處理簡單變量格式 ${VARIABLE_NAME}
    text = re.sub(r'\$\{([A-Z_]+)\}', lambda m: default_vars.get(m.group(1), m.group(0)), text)

    # 移除複雜的函數調用（帶參數或複雜邏輯）
    text = re.sub(r'\$\{[^}]+\([^)]*\)[^}]*\}', '', text)

    # 清除 Claude/Anthropic 身分注入（保留工具識別字串，不改 mcp__claude-in-chrome 這類名稱）
    text = re.sub(r'\bClaude\b', 'assistant', text, flags=re.IGNORECASE)
    text = re.sub(r'\bAnthropic\b', 'provider', text, flags=re.IGNORECASE)

    return text


def get_system_prompt_processed(
    prompt_name: str,
    variables: dict[str, str] | None = None,
    default: str = "",
) -> str:
    """取得並處理變量的 system prompt。

    Args:
        prompt_name: prompt 的名稱
        variables: 自定義變量映射
        default: 找不到時的預設值

    Returns:
        處理後的 prompt 內容
    """
    raw_prompt = get_system_prompt(prompt_name, default)
    return _process_variables(raw_prompt, variables)


SYSTEM_PROMPT: str = _build_system_prompt()

_LOCAL_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CONTEXT.md")


def _strip_generated_metadata(content: str) -> str:
    """移除本地指示檔中的自動產生中繼資訊（例如 Generated:）。"""
    cleaned_lines: list[str] = []
    for line in content.splitlines():
        normalized = line.strip().lower()
        if normalized.startswith("generated:") or normalized.startswith("**generated:**"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


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
    # 使用沙盒目錄作為 agent 的視角，不暴露真實 CWD
    from internal.paths import TIM_AGENT_SANDBOX_DIR
    
    base = start_dir or TIM_AGENT_SANDBOX_DIR
    instructions: list[str] = []
    for filename in _LOCAL_INSTRUCTION_FILES:
        path = _find_upwards(base, filename)
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        content = _strip_generated_metadata(content)
        if content:
            instructions.append(f"指示來源：{path}\n{content}")
    return instructions


def build_environment_context(start_dir: Path | None = None) -> str:
    # Agent 的工作目錄永遠是沙盒目錄，不暴露真實 CWD
    from internal.paths import TIM_AGENT_SANDBOX_DIR, get_workspace_mode
    
    agent_workspace = TIM_AGENT_SANDBOX_DIR
    home = Path.home()
    desktop = home / "Desktop"
    # 使用沙盒目錄來檢查 git root（ agent 的視角）
    git_root = _find_git_root(agent_workspace)
    workspace_mode = get_workspace_mode()
    mode_text = "沙盒模式" if workspace_mode == "sandbox" else "workspace 模式"
    lines = [
        "執行環境：",
        f"- 模式：{mode_text}",
        f"- 工作目錄：{agent_workspace}",
        f"- Home 目錄：{home}",
        f"- Desktop 目錄：{desktop}",
        f"- Git 專案：{'是' if git_root else '否'}",
    ]
    if git_root:
        lines.append(f"- Git 根目錄：{git_root}")
    lines.append(f"- 平台：{sys.platform}")
    lines.append("- 時間：由系統在每輪使用者訊息自動注入本地時區時間戳")
    return "\n".join(lines)


def build_runtime_instructions(
    base_instructions: str,
    start_dir: Path | None = None,
    include_environment_context: bool = True,
) -> str:
    parts: list[str] = []
    base = (base_instructions or "").strip()
    if base:
        parts.append(base)
    if include_environment_context:
        context = build_environment_context(start_dir)
        if context:
            parts.append(context)
    local_instructions = load_local_instructions(start_dir)
    if local_instructions:
        parts.append("\n\n".join(local_instructions))
    return "\n\n".join(parts)


