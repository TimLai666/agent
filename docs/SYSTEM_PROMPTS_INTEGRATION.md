# System Prompts 整合指南

本文檔說明如何使用 `prompts/system-prompts/` 目錄中的 system prompts。

## 概述

專案支援模組化的 system prompts 管理：

- **基礎 prompt**：`prompts/SYSTEM_PROMPT.md` - 核心系統約束和規則
- **額外 prompts**：`prompts/system-prompts/*.md` - 特定功能的 prompts（從 Claude Code 移植）

## 檔案結構

```
prompts/
├── SYSTEM_PROMPT.md              # 主要的 system prompt（保持不變）
├── MAIN_AGENT_PROMPT.md          # Main agent 的指示
├── PHILOSOPHER_PROMPT.md         # Philosopher agent 的指示
└── system-prompts/               # 額外的 system prompts
    ├── agent-prompt-explore.md   # Explore agent 的 prompt
    ├── tool-description-bash.md  # Bash 工具描述
    └── ...                       # 其他 prompts
```

## API 使用

### 1. 取得原本的 SYSTEM_PROMPT

```python
from internal.prompts import SYSTEM_PROMPT

# SYSTEM_PROMPT 仍然是 prompts/SYSTEM_PROMPT.md 的內容
print(SYSTEM_PROMPT)
```

### 2. 取得特定的 system prompt

```python
from internal.prompts import get_system_prompt

# 取得 explore agent 的 prompt
explore_prompt = get_system_prompt("agent_prompt_explore")

# 也可以使用完整的 key
explore_prompt = get_system_prompt("system_prompts.agent_prompt_explore")
```

### 3. 取得並處理變量的 system prompt

```python
from internal.prompts import get_system_prompt_processed

# 自動處理變量替換（例如 ${BASH_TOOL_NAME} -> "Bash"）
bash_desc = get_system_prompt_processed("tool_description_bash")

# 使用自定義變量
custom_vars = {"PROJECT_NAME": "我的專案", "VERSION": "2.0.0"}
prompt = get_system_prompt_processed("some_prompt", variables=custom_vars)
```

### 4. 組合多個 system prompts

```python
from internal.prompts import build_combined_system_prompt

# 組合基礎 prompt 和額外的 prompts
combined = build_combined_system_prompt(
    base_prompt=None,  # None = 使用預設的 SYSTEM_PROMPT
    additional_prompts=[
        "tool_description_bash",
        "tool_description_grep",
        "agent_prompt_explore",
    ],
    separator="\n\n---\n\n"
)
```

### 5. 列出所有可用的 system prompts

```python
from internal.prompts import list_available_system_prompts

# 列出所有 system-prompts 子目錄中的檔案
available = list_available_system_prompts()
for name in available:
    print(f"- {name}")
```

## 在 Agent 中使用

### MainAgent 使用範例

```python
from internal.agents.main_agent import MainAgent

# 創建帶有額外 system prompts 的 agent
agent = MainAgent.create(
    base_config=config,
    env=env,
    http_client=client,
    philosopher=philosopher,
    additional_system_prompts=[
        "tool_description_bash",
        "tool_description_grep",
    ]
)
```

### Sub-Agent 使用範例

當創建 sub-agent 時，可以為每個 agent 指定不同的 system prompts：

```python
# 創建 explore agent 並載入相關的 prompts
explore_agent = Agent(
    model=model,
    system_prompt=get_system_prompt_processed("agent_prompt_explore"),
    instructions="額外的指示",
    tools=tools,
)
```

## 變量處理

從 Claude Code 移植的 prompts 包含變量語法（例如 `${VARIABLE_NAME}`）。系統會自動處理這些變量：

### 支援的變量

```python
# 工具名稱
TASK_TOOL_NAME = "Task"
BASH_TOOL_NAME = "Bash"
READ_TOOL_NAME = "Read"
WRITE_TOOL_NAME = "Write"
EDIT_TOOL_NAME = "Edit"
GLOB_TOOL_NAME = "Glob"
GREP_TOOL_NAME = "Grep"

# Agent 類型
EXPLORE_AGENT = "Explore"

# 配置值
MAX_TIMEOUT_MS = "120000"
MAX_OUTPUT_CHARS = "30000"
```

### 變量格式

- `${VARIABLE_NAME}` - 簡單替換
- `${FUNCTION_NAME()}` - 函數調用（也會替換）
- `${COMPLEX_FUNCTION(args)}` - 複雜函數（會被移除）

## 最佳實踐

### 1. 保持基礎 SYSTEM_PROMPT 簡潔

`prompts/SYSTEM_PROMPT.md` 應該只包含核心約束和規則，例如：
- 語言設定
- 安全政策
- 基本行為準則

### 2. 使用額外 prompts 提供具體指導

`prompts/system-prompts/` 中的檔案應該提供：
- 特定工具的詳細說明
- Agent 的角色和行為
- 特定任務的指南

### 3. 根據需要組合 prompts

不同的 agent 可能需要不同的 prompts 組合：

```python
# Main agent：基礎 + 工具描述
main_agent_prompts = [
    "tool_description_bash",
    "tool_description_grep",
    "tool_description_read",
]

# Explore agent：基礎 + explore 特定指導
explore_agent_prompts = [
    "agent_prompt_explore",
]
```

### 4. 微調移植的 prompts

從 Claude Code 移植的 prompts 可能需要調整：

1. 檢查變量是否正確映射
2. 移除不適用的部分
3. 添加專案特定的指導
4. 調整語言和語氣

## 範例：創建自訂 Agent

```python
from internal.prompts import build_combined_system_prompt, get_system_prompt_processed
from pydantic_ai import Agent

# 1. 組合 system prompt
system_prompt = build_combined_system_prompt(
    additional_prompts=[
        "agent_prompt_explore",
        "tool_description_bash",
    ]
)

# 2. 創建 agent
my_agent = Agent(
    model=model,
    system_prompt=system_prompt,
    instructions="你是一個專門的檔案搜尋助手。",
    tools=my_tools,
)

# 3. 使用 agent
result = await my_agent.run("搜尋所有 Python 檔案")
```

## 故障排除

### 問題：變量沒有被替換

**解決方案**：使用 `get_system_prompt_processed()` 而不是 `get_system_prompt()`

```python
# ❌ 錯誤：變量不會被處理
raw = get_system_prompt("tool_description_bash")

# ✅ 正確：變量會被自動替換
processed = get_system_prompt_processed("tool_description_bash")
```

### 問題：找不到 prompt

**解決方案**：檢查檔案名稱和路徑

```python
# 列出所有可用的 prompts
from internal.prompts import list_available_system_prompts
print(list_available_system_prompts())
```

### 問題：SYSTEM_PROMPT 被覆蓋了

**解決方案**：`SYSTEM_PROMPT` 永遠不會被自動覆蓋。額外的 prompts 只會在你明確指定時才會被載入。

```python
from internal.prompts import SYSTEM_PROMPT

# 這永遠是 prompts/SYSTEM_PROMPT.md 的內容
print(SYSTEM_PROMPT)
```

## 進階使用

### 動態載入 prompts

```python
from internal.prompts import get_system_prompt_processed

def create_agent_with_prompts(agent_type: str):
    """根據 agent 類型動態載入對應的 prompts。"""
    prompt_mapping = {
        "explore": ["agent_prompt_explore"],
        "bash": ["tool_description_bash"],
        "search": ["tool_description_grep", "tool_description_glob"],
    }

    prompts = prompt_mapping.get(agent_type, [])
    combined = build_combined_system_prompt(additional_prompts=prompts)

    return Agent(
        model=model,
        system_prompt=combined,
        # ...
    )
```

### 條件式組合

```python
def build_agent_prompt(include_tools: bool = True, include_examples: bool = False):
    """根據條件組合不同的 prompts。"""
    prompts = []

    if include_tools:
        prompts.extend([
            "tool_description_bash",
            "tool_description_grep",
        ])

    if include_examples:
        prompts.append("agent_prompt_examples")

    return build_combined_system_prompt(additional_prompts=prompts)
```

## 參考

- [examples/prompt_usage_example.py](../examples/prompt_usage_example.py) - 完整的使用範例
- [internal/prompts.py](../internal/prompts.py) - 原始碼實作
- [prompts/SYSTEM_PROMPT.md](../prompts/SYSTEM_PROMPT.md) - 基礎 system prompt
