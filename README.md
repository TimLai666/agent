# agent

這是一個日常 AI agent，類似 Siri，目標是協助用戶完成日常任務。

## 特色
- 支援主 agent + 工具導向執行架構。
- 可透過 `/tools` 查看可用能力。
- 具備語音輸入（Whisper）與 CLI 互動流程。
- SQLite 配置系統，支援多種模型提供者 (OpenAI、Claude、GitHub Copilot 等)
- **512k context window**：每次對話支援大量內容
- **持久記憶系統**：agent 自動維護 `~/.tim-agent/memory/` 下的五個記憶檔案，每輪自動注入最新內容

## 🚀 快速開始

本專案建議使用 [uv](https://github.com/astral-sh/uv) 來安裝依賴與運行。

### 安裝依賴
```sh
uv sync
```

### 設定模型（首次使用必須）

使用 SQLite 資料庫存儲配置：

```sh
# 方式 A: Web UI（推薦）- 圖形化介面，自動列出模型
uv run main.py --config-web
# 瀏覽器會自動打開 http://127.0.0.1:5000

# 方式 B: CLI 介面
uv run main.py --config

# 按照提示設定:
# 1. 新增提供者 (OpenAI / Claude / GitHub Copilot / 本地 LLM)
# 2. 設定 main agent 使用的模型
# 3. [可選] 設定默認配置
```

**💡 默認配置功能**：
- 在 Web UI 的 Agents 頁面，點擊 "⚙️ 默認配置" 按鈕
- 設定後，未配置項目可自動使用此配置
- 適合快速開始和統一管理模型設定

📖 **詳細文檔**：
- [配置指南](docs/CONFIG_GUIDE.md) - 完整配置說明（包含 Web UI 使用教學）
- [默認配置指南](docs/DEFAULT_CONFIG_GUIDE.md) - 默認配置功能詳細說明
- [Windows 快速開始](docs/WINDOWS_QUICK_START.md) - Windows 用戶指南
- [GitHub 瀏覽器登入](docs/GITHUB_BROWSER_LOGIN.md) - 最簡單的 GitHub Copilot 設定方式
- [文檔索引](docs/README.md) - 所有文檔列表

### 安裝 Playwright（選用，用於瀏覽器工具）
```sh
uv run playwright install
```

### 啟動

**CLI 模式（默認）**：
```sh
uv run main.py
```

**GUI 模式**：
```sh
uv run main.py --gui
```

**程式化模式（import 即用）**：

```python
import asyncio

from sdk import Agent, OpenAICompatibleModel


async def main() -> None:
    async with Agent(
        workspace="./.agent-workspace",
        system_name="MyAssistant",
        system_prompt_append="你是企業內部助理，回答要精簡。",
        skill_root_dirs=["./skills"],
        model=OpenAICompatibleModel(
            model_name="gpt-4.1-mini",
            base_url="https://api.openai.com",
            api_key="YOUR_API_KEY",
            temperature=0.2,
        ),
        # 停用特定 skills
        disabled_skills=["bcg-growth-share-matrix", "scamper"],
        # 在預設 MCP 清單之外追加自訂 MCP server
        extra_mcp_servers=[my_custom_mcp],
        # mcp_servers=[] 可完全取代預設 MCP 清單
        # use_default_tools=False 可停用預設 tools，僅用 extra_tools
    ) as agent:
        reply = await agent.run("請幫我整理今天的待辦")
        print(reply)


asyncio.run(main())
```

`workspace` 可在程式化使用時覆寫 agent 工作目錄；未覆寫時會使用預設沙盒模式。

**記憶系統（SDK 參數）**：

```python
# 預設：~/.tim-agent/memory/ 自動啟用
Agent()

# 覆寫記憶目錄
Agent(memory_dir="/path/to/custom/memory")

# 關閉記憶系統
Agent(memory_enabled=False)

# 帶入外部記憶系統實例
from internal.memory import MemoryManager
Agent(memory_system=MemoryManager(memory_dir="/shared/memory"))
```

記憶檔案說明：

| 檔案 | 注入方式 | 用途 |
| --- | --- | --- |
| `ME.md` | **每輪自動注入** | Agent 自身身份與角色定義 |
| `USER.md` | **每輪自動注入** | 使用者資訊與偏好設定 |
| `TODO.md` | **每輪自動注入** | 長期計劃與待辦事項 |
| `TOOLS.md` | 工具呼叫 | 環境工具與服務配置資訊 |
| `MEMORY.md` | 工具呼叫 | 長期對話記憶重點 |

- `ME.md`、`USER.md`、`TODO.md` 不需呼叫工具，每輪對話自動注入 context
- `TOOLS.md`、`MEMORY.md` 透過 `memory_read` 工具按需存取
- Agent 可隨時用 `memory_read` / `memory_write` 工具讀寫，無需額外授權
- 每次寫入時同步整理舊內容（合併重複、移除過時項目）
- 目錄路徑可透過環境變數 `TIM_AGENT_MEMORY_DIR` 覆寫

**程式化串流回應**：

```python
import asyncio

from sdk import Agent


async def main() -> None:
    async with Agent() as agent:
        async for chunk in agent.run_stream("請用三段列出今天重點"):
            print(chunk, end="", flush=True)
        print()


asyncio.run(main())
```

同步程式也可使用 `run_stream_sync(prompt, on_chunk=...)`。

**配置模式**：

```sh
uv run main.py --config
```

## 可用指令

CLI 和 GUI 模式都支援以下指令：

### 基本指令

- `/help` - 顯示所有可用指令
- `/exit`, `/quit` - 退出程式
- `/clear` - 清除屏幕（僅 CLI）
- `/config` - 開啟文字式設定選單（CLI）
- `/config-web` - 啟動並在瀏覽器打開設定 Web UI

### 查詢指令

- `/tools` - 列出所有可用工具
- `/skills` 或 `/skills list` - 列出所有已載入的 skills
- `/skills info <name>` - 顯示特定 skill 的詳細資訊
- `/skills test <prompt>` - 測試哪些 skills 會匹配給定的提示

### 對話管理指令

- `/history [N]` - 顯示最近 N 輪對話（預設 5）
- `/last` - 顯示最後一次助手回覆
- `/retry` - 重新執行最後一次用戶提示

### Skills 管理指令

- `/skills reload` - 重新載入所有 skills（從磁碟）

### 使用範例

```sh
# 查看所有可用 skills
/skills

# 查看特定 skill 的詳細資訊
/skills info code-review

# 測試哪些 skills 會被匹配
/skills test Can you review my code?

# 重新載入 skills（修改後無需重啟）
/skills reload

# 查看對話歷史
/history 10
```

## 配置範例

```sh
/config          # 啟動文字式設定選單
/config-web      # 啟動並在瀏覽器打開設定頁
```

GUI 模式詳細說明請參考 `GUI_README.md`。

