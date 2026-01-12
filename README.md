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

啟動後可使用（CLI 模式）：
- `/help` 查看指令
- `/subagents` 列出 subagents
- `/tools` 列出工具

GUI 模式詳細說明請參考 `GUI_README.md`。

