# agent

這是一個日常 AI agent，類似 Siri，目標是協助用戶完成日常任務。

## 特色
- 支援主 agent + 工具導向執行架構。
- 可透過 `/tools` 查看可用能力。
- 具備語音輸入（Whisper）與 CLI 互動流程。
- **新功能**: SQLite 配置系統，支援多種模型提供者 (OpenAI、Claude、GitHub Copilot 等)

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

from agent import Agent, OpenAICompatibleModel


async def main() -> None:
    async with Agent(
        system_name="MyAssistant",
        system_prompt_append="你是企業內部助理，回答要精簡。",
        skill_root_dirs=["./skills"],
        model=OpenAICompatibleModel(
            model_name="gpt-4.1-mini",
            base_url="https://api.openai.com",
            api_key="YOUR_API_KEY",
            temperature=0.2,
        ),
        # mcp_servers=[] 可完全停用 MCP
        # use_default_tools=False 可停用預設 tools，僅用 extra_tools
    ) as agent:
        reply = await agent.run("請幫我整理今天的待辦")
        print(reply)


asyncio.run(main())
```

**程式化串流回應**：

```python
import asyncio

from agent import Agent


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
- `/config` - 開啟文字式設定選單（CLI）；在 GUI 下會在終端中啟動互動式設定選單
- `/config-web` - 啟動並/或打開設定 Web UI（在瀏覽器中開啟，伺服器會在背景運行）

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

# 配置範例

```sh
# 在程式內啟動的情況下（或任何時候），可使用下列指令：
# 在 CLI 或 GUI 的輸入框輸入：
/config          # 啟動文字式設定選單
/config-web      # 啟動並在瀏覽器打開設定頁
```

GUI 模式詳細說明請參考 `GUI_README.md`。

