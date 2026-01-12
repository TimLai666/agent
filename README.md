# agent

這是一個日常 AI agent，類似 Siri，目標是協助用戶完成日常任務。

## 特色
- 支援多代理架構：主 agent、co-agent、subagents。
- `internal/sub_agents/` 下的每個 `.md` 會自動註冊成 main agent 的工具。
- 可透過 `/subagents` 和 `/tools` 查看可用能力。
- 具備語音輸入（Whisper）與 CLI 互動流程。

## 使用方式

本專案建議使用 [uv](https://github.com/astral-sh/uv) 來安裝依賴與運行。

### 安裝依賴
```sh
uv sync
```

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
uv run python main.py --gui
```

## 可用指令

CLI 和 GUI 模式都支援以下指令：

### 基本指令
- `/help` - 顯示所有可用指令
- `/exit`, `/quit` - 退出程式
- `/clear` - 清除屏幕（僅 CLI）

### 查詢指令
- `/tools` - 列出所有可用工具
- `/subagents` - 列出所有子代理
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

GUI 模式詳細說明請參考 `GUI_README.md`。

