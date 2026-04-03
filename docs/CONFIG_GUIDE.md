# Agent 配置管理指南

本專案使用 SQLite 資料庫存儲 agent 配置，支援多種模型提供者。

## 快速開始

### 1. 開啟配置介面

#### 方式 A: Web UI（推薦）

```bash
# 使用 uv
uv run main.py --config-web

# 或直接執行
python main.py --config-web
```

瀏覽器會自動打開 `http://127.0.0.1:5000`，提供圖形化配置介面：
- ✅ 直觀的視覺化介面
- ✅ 自動列出提供者可用模型
- ✅ 一鍵 GitHub OAuth 認證
- ✅ 即時配置預覽

#### 方式 B: CLI 介面

```bash
# 使用 uv
uv run main.py --config

# 或直接執行
python main.py --config
```

### 2. 設定提供者 (Provider)

支援兩種提供者類型：

#### OpenAI 相容 API
適用於：
- OpenAI 官方 API
- Azure OpenAI
- Anthropic Claude
- 本地 LLM (Ollama, LM Studio 等)
- 其他相容 OpenAI API 格式的服務

設定步驟：
1. 選擇 "新增 OpenAI 相容 API 提供者"
2. 輸入提供者 ID (例如: `openai`, `anthropic`, `azure`)
3. 輸入顯示名稱
4. 輸入 Base URL (留空則使用 OpenAI 預設)
5. 輸入 API Key

範例：
```
提供者 ID: anthropic
顯示名稱: Anthropic Claude
Base URL: https://api.anthropic.com
API Key: sk-ant-...
```

#### GitHub Copilot
使用 GitHub Copilot 的模型服務。

**Web UI 設定步驟**：
1. 選擇 "GitHub Copilot" 類型
2. 輸入提供者 ID 和名稱
3. 點擊「🔐 瀏覽器登入」按鈕 - 自動完成 OAuth 認證
4. Token 會自動填入並保存

**CLI 設定步驟**：
1. 選擇 "新增 GitHub Copilot 提供者"
2. 輸入提供者 ID (例如: `github-copilot`)
3. 選擇取得 Token 的方式：
   - **瀏覽器登入** (推薦)
   - **自動取得** - 需要已登入 gh CLI
   - **手動輸入**

推薦使用 **Web UI + 瀏覽器登入**，最簡單！

**技術說明**：
- 使用兩段式認證：GitHub OAuth token → Copilot API token
- Token 自動緩存和刷新，有效期約 10 分鐘
- API 端點：`https://api.githubcopilot.com`

### 3. 設定 Agent

為每個 agent 指定使用的提供者和模型：

**Web UI**：
1. 切換到「🤖 Agent 配置」標籤
2. 點擊「➕ 設定 Agent」
3. 輸入 agent 名稱
4. 選擇提供者 - 系統會**自動載入該提供者的可用模型**
5. 從下拉選單選擇模型（無需手動輸入）
6. 調整 temperature（可選）

**CLI**：
1. 選擇 "設定 Agent"
2. 輸入 agent 名稱 (例如: `main`, `marketing`, `testing`)
3. 選擇提供者
4. 輸入模型名稱 (例如: `gpt-4`, `claude-3-5-sonnet-20241022`)
5. 設定 temperature (預設 0.2)

## 常用 Agent 名稱

專案中的主要 agents：
- `main` - 主要 agent
- `marketing` - 行銷 sub-agent
- `testing` - 測試 sub-agent
- `design` - 設計 sub-agent

查看更多 agents，請參考 `internal/sub_agents/` 目錄。

## 模型名稱範例

### OpenAI
- `gpt-4`
- `gpt-4-turbo`
- `gpt-3.5-turbo`

### Anthropic Claude
- `claude-3-5-sonnet-20241022`
- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`

### GitHub Copilot
- `gpt-4o-mini`
- `gpt-4o`
- `o1-preview`
- `o1-mini`
- `claude-3.5-sonnet`

## 資料庫位置

配置存儲在：
```
~/.tim-agent/config/config.db
```

## 管理命令

### 列出所有提供者
```python
from internal.services.config_db import list_providers
providers = list_providers()
```

### 列出所有 Agent 配置
```python
from internal.services.config_db import list_agent_configs
configs = list_agent_configs()
```

### 程式化設定

```python
from internal.services.config_db import (
    ProviderConfig,
    AgentModelConfig,
    add_provider,
    set_agent_config,
)

# 新增提供者
provider = ProviderConfig(
    provider_id="openai",
    provider_type="openai-compatible",
    name="OpenAI",
    base_url="https://api.openai.com",
    api_key="sk-...",
)
add_provider(provider)

# 設定 agent
config = AgentModelConfig(
    agent_name="main",
    provider_id="openai",
    model_name="gpt-4",
    temperature=0.5,
)
set_agent_config(config)
```

## 故障排除

### 問題：找不到資料庫配置
請先使用 `uv run main.py --config` 設定提供者和 agent 配置。

### 問題：GitHub Copilot 認證失敗

1. 確認你的 GitHub token 有效
2. 確認有 GitHub Copilot 訂閱（個人版或 Pro+）
3. 查看 log 確認 token 交換是否成功：
   - `Exchanging GitHub token for Copilot token...`
   - `✓ Got Copilot token from ...`
4. 如果 timeout，重試即可（token 會緩存）

### 問題：模型名稱錯誤
不同提供者支援的模型名稱不同，請參考各提供者的文檔。

## 安全性提醒

- API Keys 和 Tokens 存儲在本地 SQLite 資料庫中
- 不要將包含敏感資訊的資料庫檔案提交到版本控制
- 定期更新你的 API Keys
