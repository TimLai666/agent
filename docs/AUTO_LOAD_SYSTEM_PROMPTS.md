# 自動載入 System Prompts 功能

## 概述

從現在開始，**MainAgent 預設會自動載入所有可用的 system prompts**。這意味著 agent 在啟動時會自動組合：

1. 基礎的 `prompts/SYSTEM_PROMPT.md`
2. `prompts/system-prompts/` 目錄中的**所有** `.md` 檔案

## 這改變了什麼？

### 之前（手動載入）

```python
# agent 只看到基礎的 SYSTEM_PROMPT
agent = MainAgent.create(...)

# 需要手動指定要載入的 prompts
agent = MainAgent.create(
    ...,
    additional_system_prompts=["tool-description-bash", "agent-prompt-explore"]
)
```

### 現在（自動載入）✨

```python
# agent 自動載入所有 system prompts（預設行為）
agent = MainAgent.create(...)
# 👆 這會自動載入 prompts/system-prompts/ 中的所有檔案
```

## Agent 現在看到什麼？

完整的 system prompt 結構：

```
基礎 SYSTEM_PROMPT
---
agent-prompt-agent-creation-architect
---
agent-prompt-agent-hook
---
agent-prompt-bash-command-description-writer
---
... (總共 66+ 個 prompts)
---
tool-description-write
```

## 控制自動載入行為

### 選項 1：完全自動載入（預設）

```python
agent = MainAgent.create(
    base_config=config,
    env=env,
    http_client=client,
    philosopher=philosopher,
    # auto_load_all_prompts=True  # 預設值，可省略
)
```

### 選項 2：關閉自動載入

```python
agent = MainAgent.create(
    ...,
    auto_load_all_prompts=False  # 只使用基礎 SYSTEM_PROMPT
)
```

### 選項 3：自動載入 + 額外指定

```python
agent = MainAgent.create(
    ...,
    additional_system_prompts=["my-custom-prompt"],  # 會載入所有 + 這個
    auto_load_all_prompts=True
)
```

### 選項 4：只載入特定的 prompts

```python
agent = MainAgent.create(
    ...,
    additional_system_prompts=["tool-description-bash", "agent-prompt-explore"],
    auto_load_all_prompts=False  # 關閉自動載入，只用指定的
)
```

## 效能考量

### System Prompt 大小

- **基礎 SYSTEM_PROMPT**: ~3,000 字元
- **所有 system-prompts**: ~200,000+ 字元
- **總計**: ~203,000 字元

### 是否影響效能？

**短答案**：對於現代 LLM（如 GPT-4、Claude）影響很小。

**長答案**：
- ✅ **Token 數量增加**：會消耗更多 input tokens
- ✅ **Context 視窗**：現代模型有 100K-200K token 的 context
- ✅ **成本增加**：每次請求會多付約 $0.002-0.005（以 GPT-4 為例）
- ⚠️ **首次載入**：啟動時會花幾秒鐘處理 prompts
- ❌ **回應速度**：幾乎沒有影響（LLM 處理速度很快）

### 建議

| 使用場景 | 建議設定 |
|---------|---------|
| 生產環境（完整功能） | 自動載入（預設） |
| 開發測試 | 自動載入（預設） |
| 成本敏感 | 關閉自動載入 |
| 簡單任務 | 關閉自動載入 |
| 特定領域 | 手動選擇相關 prompts |

## 測試自動載入

執行測試腳本：

```bash
python tests/test_auto_load_prompts.py
```

輸出範例：

```
============================================================
測試：自動載入所有 system prompts
============================================================

✓ 找到 66 個 system prompts

基礎 SYSTEM_PROMPT 長度: 3,247 字元
組合後總長度: 203,485 字元
增加了: 200,238 字元
增加比例: 6165.1%

✓ 包含 66 個分隔符

前 10 個載入的 prompts:
  1. agent-prompt-agent-creation-architect
  2. agent-prompt-agent-hook
  3. agent-prompt-bash-command-description-writer
  ...

✓ 測試完成
```

## 檢視載入的內容

### 列出所有 prompts

```python
from internal.prompts import list_available_system_prompts

prompts = list_available_system_prompts()
print(f"總共 {len(prompts)} 個 prompts")
for name in prompts:
    print(f"  - {name}")
```

### 檢視組合後的 prompt

```python
from internal.agents.main_agent import MainAgent

# 創建 agent（會自動載入）
agent = MainAgent.create(...)

# 檢視 system prompt
print(agent.agent._system_prompt)
```

## 關閉自動載入的場景

考慮關閉自動載入當：

1. **成本優先**：最小化 API 成本
2. **簡單任務**：只需要基礎功能
3. **特定領域**：只需要某幾個特定 prompts
4. **偵錯測試**：想測試沒有額外 prompts 的行為

範例：

```python
# 成本優化版本
minimal_agent = MainAgent.create(
    ...,
    auto_load_all_prompts=False,
    additional_system_prompts=["tool-description-bash"]  # 只載入必要的
)

# 完整功能版本（預設）
full_agent = MainAgent.create(...)
```

## 動態調整載入策略

### 根據環境變數控制

```python
import os

# 從環境變數讀取設定
auto_load = os.getenv("AUTO_LOAD_PROMPTS", "true").lower() == "true"

agent = MainAgent.create(
    ...,
    auto_load_all_prompts=auto_load
)
```

### 根據任務類型控制

```python
def create_agent_for_task(task_type: str):
    if task_type == "simple":
        return MainAgent.create(..., auto_load_all_prompts=False)
    elif task_type == "coding":
        return MainAgent.create(
            ...,
            additional_system_prompts=["tool-description-bash", "agent-prompt-explore"],
            auto_load_all_prompts=False
        )
    else:  # complex
        return MainAgent.create(...)  # 全載入
```

## 優點與缺點

### 優點 ✅

1. **功能完整**：agent 擁有所有知識和指導
2. **零配置**：不需要手動指定要載入的 prompts
3. **一致性**：所有實例都有相同的完整知識
4. **靈活性**：可隨時關閉或自定義

### 缺點 ⚠️

1. **Token 成本**：每次請求多消耗 ~2,000 tokens
2. **啟動時間**：首次載入會花幾秒鐘
3. **可能冗餘**：某些 prompts 可能用不到

## 最佳實踐

### 1. 預設使用自動載入

```python
# 推薦：簡單且功能完整
agent = MainAgent.create(...)
```

### 2. 特殊場景才關閉

```python
# 只在有明確需求時才關閉
if is_cost_sensitive:
    agent = MainAgent.create(..., auto_load_all_prompts=False)
```

### 3. 定期檢查載入的內容

```python
# 確保沒有載入不需要的 prompts
prompts = list_available_system_prompts()
print(f"目前會載入 {len(prompts)} 個 prompts")
```

### 4. 監控成本

```python
# 計算預估成本（以 GPT-4 為例）
from internal.prompts import build_combined_system_prompt, list_available_system_prompts

prompts = list_available_system_prompts()
combined = build_combined_system_prompt(additional_prompts=prompts)

# 粗估 token 數量（1 token ≈ 4 字元）
estimated_tokens = len(combined) / 4
cost_per_request = estimated_tokens * 0.00001  # GPT-4 input 價格
print(f"每次請求預估成本: ${cost_per_request:.4f}")
```

## FAQ

### Q: 會不會讓 agent 變慢？

**A**: 幾乎不會。現代 LLM 處理長 context 的速度很快。

### Q: 成本增加多少？

**A**: 以 GPT-4 為例，每次請求約增加 $0.002-0.005。

### Q: 可以選擇只載入某些 prompts 嗎？

**A**: 可以！設定 `auto_load_all_prompts=False` 並手動指定。

### Q: 這會影響現有的程式碼嗎？

**A**: 不會！這是預設行為，現有程式碼無需修改。如果不想自動載入，可以明確設定 `auto_load_all_prompts=False`。

## 相關文檔

- [SYSTEM_PROMPTS_INTEGRATION.md](./SYSTEM_PROMPTS_INTEGRATION.md) - 完整的使用指南
- [SYSTEM_PROMPTS_MIGRATION_SUMMARY.md](./SYSTEM_PROMPTS_MIGRATION_SUMMARY.md) - 遷移總結

## 回饋與改進

如果你發現某些 prompts 不應該被自動載入，或有其他改進建議，請開 issue 討論。
