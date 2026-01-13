# 默認配置功能說明

## 概述

默認配置功能提供**兩級默認配置系統**，讓您能靈活地為所有 Agent 或特定類別的 Subagent 設置默認配置：

1. **全域默認配置** (`default`) - 所有未配置 Agent 的後備選項
2. **類別默認配置** (`default:{category}`) - 特定類別 Subagent 的專用配置

## 配置優先級

當獲取 Agent 配置時，系統按以下順序查找：

```
1. Agent 直接配置
   ↓ (未找到)
2. 繼承配置 (inherit_from)
   ↓ (未找到)
3. 類別默認配置 (default:{category})
   ↓ (未找到)
4. 全域默認配置 (default)
   ↓ (未找到)
5. None (無配置)
```

## 功能特點

### 1. 兩級默認配置
- **全域默認**：適用於所有未配置的 Agent
- **類別默認**：為特定類別（marketing、testing、design 等）設置專用配置
- **自動回退**：類別默認 → 全域默認

### 2. Web UI 管理
在新的 **"⚙️ 默認配置"** 標籤頁中：

- **全域默認配置區域**：
  - 查看當前全域默認狀態
  - 設定/修改/刪除全域默認

- **類別默認配置區域**：
  - 列出所有 Agent 類別
  - 為每個類別設定專用默認配置
  - 顯示配置狀態（已設定/使用全域默認）

### 3. Agent 配置標記
- **直接配置**：綠色 badge - 使用自己的 Provider 和 Model
- **繼承配置**：藍色 badge - 從父 Agent 繼承配置
- **未配置**：不出現在列表中，運行時自動使用類別或全域默認

## 使用場景

### 場景 1：統一的 LLM 提供者
如果大部分 Subagent 使用同一個 LLM，但某些類別需要特殊模型：
1. 設置全域默認配置（如 OpenAI GPT-4）
2. 為特殊類別設置類別默認（如 Marketing 類用 GPT-4-turbo）
3. 只需配置極少數特殊需求的 Agent

### 場景 2：按類別優化
不同類別的任務需要不同的模型：
1. Marketing 類：使用創意型模型（temperature 較高）
2. Testing 類：使用精確型模型（temperature 較低）
3. Design 類：使用視覺理解模型
4. 其他：使用全域默認

### 場景 3：快速開始
對於新項目：
1. 先設置全域默認配置
2. 所有 Agent 立即可以運行
3. 按需為特定類別設置專用配置
4. 最後再優化個別 Agent

### 場景 4：成本控制
根據預算分配模型：
1. 全域默認：經濟型模型
2. 重要類別（如 Marketing）：高級模型
3. 測試類別：本地模型

## API 端點

### 全域默認配置

#### GET /api/default-config
獲取全域默認配置
```json
{
  "success": true,
  "config": {
    "provider_id": "openai",
    "provider_name": "OpenAI",
    "model_name": "gpt-4",
    "temperature": 0.2
  }
}
```

#### POST /api/default-config
設置全域默認配置
```json
{
  "provider_id": "openai",
  "model_name": "gpt-4",
  "temperature": 0.2
}
```

#### DELETE /api/default-config
刪除全域默認配置

### 類別默認配置

#### GET /api/category-default-config/{category}
獲取類別默認配置
```json
{
  "success": true,
  "config": {
    "provider_id": "openai",
    "provider_name": "OpenAI",
    "model_name": "gpt-4-turbo",
    "temperature": 0.7
  }
}
```

#### POST /api/category-default-config/{category}
設置類別默認配置
```json
{
  "provider_id": "openai",
  "model_name": "gpt-4-turbo",
  "temperature": 0.7
}
```

#### DELETE /api/category-default-config/{category}
刪除類別默認配置

#### GET /api/agent-categories
獲取所有類別列表
```json
{
  "categories": [
    "co-agents",
    "design",
    "marketing",
    "operations",
    "testing",
    ...
  ]
}
```

## 代碼使用

### 基礎用法
```python
from internal.services.config_db import get_agent_config

# 獲取配置（自動使用類別/全域默認）
config = get_agent_config(
    "marketing-email-writer", 
    use_default=True,
    category="marketing"  # 指定類別以使用類別默認
)
```

### 設置配置
```python
from internal.services.config_db import set_agent_config, AgentModelConfig

# 設置全域默認
global_default = AgentModelConfig(
    agent_name="default",
    provider_id="openai",
    model_name="gpt-4",
    temperature=0.2,
    inherit_from=None
)
set_agent_config(global_default)

# 設置類別默認
marketing_default = AgentModelConfig(
    agent_name="default:marketing",
    provider_id="anthropic",
    model_name="claude-3-opus",
    temperature=0.7,
    inherit_from=None
)
set_agent_config(marketing_default)
```

### 檢查配置來源
```python
# 獲取直接配置（不使用默認）
direct_config = get_agent_config("agent-name", use_default=False)

if direct_config:
    if direct_config.inherit_from:
        if direct_config.inherit_from.startswith("default:"):
            print("Agent 使用類別默認配置")
        elif direct_config.inherit_from == "default":
            print("Agent 使用全域默認配置")
        else:
            print("Agent 使用繼承配置")
    else:
        print("Agent 有直接配置")
else:
    print("Agent 未配置")
```

## 數據庫結構

默認配置存儲在 `agent_configs` 表中：

```sql
-- 全域默認配置
INSERT INTO agent_configs 
(agent_name, provider_id, model_name, temperature, inherit_from)
VALUES 
('default', 'openai', 'gpt-4', 0.2, NULL);

-- 類別默認配置
INSERT INTO agent_configs 
(agent_name, provider_id, model_name, temperature, inherit_from)
VALUES 
('default:marketing', 'anthropic', 'claude-3-opus', 0.7, NULL);
```

## 注意事項

1. **配置優先級**
   - 直接配置 > 繼承配置 > 類別默認 > 全域默認
   - 設置了 inherit_from 的 agent 不會使用默認配置

2. **類別名稱**
   - 類別名稱來自 agent discovery（`category` 字段）
   - 格式為 `default:{category}`（如 `default:marketing`）
   - 大小寫敏感

3. **刪除默認配置**
   - 刪除類別默認：該類別回退到全域默認
   - 刪除全域默認：未配置的 agent 將無法獲取配置
   - 不影響已明確配置的 agent

4. **Temperature 繼承**
   - 默認配置的 temperature 會被繼承
   - 可以在具體 agent 配置中覆蓋

## 測試

運行測試腳本驗證功能：
```bash
python test_two_level_defaults.py
```

測試內容：
- 全域默認配置設置
- 類別默認配置設置
- 配置回退順序驗證
- 刪除配置後的回退行為

## 更新日誌

### 2026-01-13
- ✅ 實現兩級默認配置系統
- ✅ 添加類別默認配置支持
- ✅ 更新回退邏輯：類別默認 → 全域默認
- ✅ 添加類別默認配置 API 端點
- ✅ 創建專用的默認配置標籤頁
- ✅ 完成測試腳本驗證

### 2024-01-XX
- ✅ 添加默認配置數據庫邏輯
- ✅ 實現自動回退機制
- ✅ 添加 Web UI 管理界面
- ✅ 創建 API 端點
