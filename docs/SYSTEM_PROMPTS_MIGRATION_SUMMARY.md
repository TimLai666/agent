# System Prompts 整合總結

## 完成的工作

我已經成功將 `prompts/system-prompts/` 目錄中從 Claude Code 移植的 system prompts 整合到專案中。

## 主要變更

### 1. 擴充 `internal/prompts.py`

新增了以下功能：

#### 載入機制
- **`_load_prompts()`**：現在會載入根目錄和 `system-prompts/` 子目錄的所有 `.md` 檔案
  - 根目錄檔案：key = 檔名大寫（例如 `SYSTEM_PROMPT`）
  - 子目錄檔案：key = `system_prompts.檔名`（例如 `system_prompts.agent_prompt_explore`）

#### 取得 Prompts
- **`get_system_prompt(prompt_name, default="")`**：取得特定的 system prompt
- **`get_system_prompt_processed(prompt_name, variables=None, default="")`**：取得並處理變量的 system prompt

#### 組合 Prompts
- **`build_combined_system_prompt(base_prompt=None, additional_prompts=None, separator="\n\n---\n\n")`**：組合多個 system prompts

#### 變量處理
- **`_process_variables(text, variables=None)`**：處理 prompt 中的變量替換
  - 支援 `${VARIABLE_NAME}` 格式
  - 支援 `${FUNCTION_NAME()}` 格式
  - 自動移除複雜的函數調用

#### 列出可用 Prompts
- **`list_available_system_prompts()`**：列出所有可用的 system prompts

### 2. 變量映射

已建立完整的變量映射，將 Claude Code 的工具名稱映射到專案實際的工具：

| Claude Code 變量 | 專案實際工具 | 說明 |
|---|---|---|
| `BASH_TOOL_NAME` | `run_terminal_command` | 執行終端命令 |
| `READ_TOOL_NAME` | `read_file` | 讀取檔案 |
| `WRITE_TOOL_NAME` | `create_new_file` | 創建新檔案 |
| `EDIT_TOOL_NAME` | `modify_existing_file` | 修改現有檔案 |
| `GLOB_TOOL_NAME` | `list_files_in_directory` | 列出目錄檔案 |
| `GREP_TOOL_NAME` | `find_all_lines_in_file_with_fragment` | 搜尋檔案內容 |
| `SEARCH_TOOL_NAME` | `find_files_with_fragment` | 搜尋檔案 |
| `WEBFETCH_TOOL_NAME` | `browse_website` | 瀏覽網站內容 |
| `WEBSEARCH_TOOL_NAME` | `web_search` | 網路搜尋 |
| `TASK_TOOL_NAME` | `ask_sub_agent` | 委派任務給 sub-agent |

### 3. 更新 `internal/agents/main_agent.py`

#### 新增方法
- **`_build_enhanced_system_prompt(additional_prompts=None)`**：建立增強的 system prompt

#### 修改 `create()` 方法
- 新增 `additional_system_prompts` 參數
- 支援在創建 agent 時指定額外的 system prompts
- 所有 agent（main、planner、discussion）都使用增強的 system prompt

## 使用範例

### 基本使用

```python
from internal.prompts import SYSTEM_PROMPT, get_system_prompt_processed

# 1. 原本的 SYSTEM_PROMPT 仍然不變
print(SYSTEM_PROMPT)

# 2. 取得並處理特定的 system prompt
bash_desc = get_system_prompt_processed("tool_description_bash")
```

### 組合多個 Prompts

```python
from internal.prompts import build_combined_system_prompt

# 組合基礎 prompt 和額外的 prompts
combined = build_combined_system_prompt(
    additional_prompts=[
        "tool_description_bash",
        "agent_prompt_explore",
    ]
)
```

### 在 MainAgent 中使用

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

## 重要特性

### 1. 向後相容
- 原本的 `SYSTEM_PROMPT.md` 完全保持不變
- 所有現有功能都正常運作
- 新功能為**可選**的

### 2. 模組化設計
- 基礎 prompt 和額外 prompts 分離
- 可以根據需要選擇性地組合
- 支援動態載入

### 3. 變量處理
- 自動將 Claude Code 的變量映射到專案工具
- 支援自定義變量
- 智能處理複雜的變量語法

### 4. 易於擴展
- 只需在 `prompts/system-prompts/` 中添加新的 `.md` 檔案
- 自動載入並可立即使用
- 無需修改程式碼

## 檔案結構

```
prompts/
├── SYSTEM_PROMPT.md              # 主要的 system prompt（保持不變）
├── MAIN_AGENT_PROMPT.md          # Main agent 的指示
├── PHILOSOPHER_PROMPT.md         # Philosopher agent 的指示
└── system-prompts/               # 額外的 system prompts
    ├── agent-prompt-explore.md   # Explore agent 的 prompt
    ├── tool-description-bash.md  # Bash 工具描述
    └── ...                       # 其他 prompts（66 個檔案）
```

## 相關文檔

- [SYSTEM_PROMPTS_INTEGRATION.md](./SYSTEM_PROMPTS_INTEGRATION.md) - 完整的使用指南
- [examples/prompt_usage_example.py](../examples/prompt_usage_example.py) - 使用範例
- [tests/test_system_prompts_integration.py](../tests/test_system_prompts_integration.py) - 整合測試

## 測試

執行測試以驗證整合：

```bash
python tests/test_system_prompts_integration.py
```

測試涵蓋：
1. 原本的 SYSTEM_PROMPT 載入
2. 取得特定的 system prompt
3. 變量處理
4. 組合多個 prompts
5. 列出可用的 prompts
6. 自定義變量

## 下一步

### 建議的改進

1. **為 Sub-Agents 添加 System Prompts**
   - 在 `internal/sub_agents/registry.py` 中整合 system prompts
   - 讓每個 sub-agent 可以載入特定的 prompts

2. **創建專案專用的 Prompts**
   - 根據專案特性創建新的 prompts
   - 例如：針對特定領域的指導

3. **優化變量映射**
   - 隨著專案發展，持續更新變量映射
   - 添加更多專案特定的變量

4. **文檔完善**
   - 為每個重要的 system prompt 添加說明
   - 創建最佳實踐指南

## 技術細節

### 變量處理邏輯

```python
# 1. 處理函數調用格式 ${FUNCTION_NAME()}
text = re.sub(r'\$\{([A-Z_]+)\(\)\}', lambda m: default_vars.get(m.group(1), m.group(0)), text)

# 2. 處理簡單變量格式 ${VARIABLE_NAME}
text = re.sub(r'\$\{([A-Z_]+)\}', lambda m: default_vars.get(m.group(1), m.group(0)), text)

# 3. 移除複雜的函數調用（帶參數或複雜邏輯）
text = re.sub(r'\$\{[^}]+\([^)]*\)[^}]*\}', '', text)
```

### Prompt 載入優先級

1. 根目錄 prompts（例如 `SYSTEM_PROMPT.md`）
2. `system-prompts/` 子目錄 prompts
3. 使用者自定義變量（通過 `variables` 參數）

## 貢獻者注意事項

### 添加新的 System Prompt

1. 在 `prompts/system-prompts/` 中創建新的 `.md` 檔案
2. 使用 kebab-case 命名（例如 `my-new-prompt.md`）
3. 如果包含變量，使用 `${VARIABLE_NAME}` 格式
4. 在 `_process_variables()` 中添加新的變量映射（如需要）

### 修改現有的 System Prompt

1. **不要修改** `prompts/SYSTEM_PROMPT.md`（除非有充分理由）
2. 修改 `system-prompts/` 中的檔案
3. 測試變量替換是否正常工作
4. 更新相關文檔

## 授權

從 Claude Code 移植的 prompts 遵循其原始授權。

## 問題回報

如有任何問題或建議，請：
1. 檢查 [SYSTEM_PROMPTS_INTEGRATION.md](./SYSTEM_PROMPTS_INTEGRATION.md) 文檔
2. 查看測試檔案中的範例
3. 在 GitHub 上開 issue

---

**整合完成日期**：2026-01-14
**版本**：1.0.0
