# 10 — 未公開/實驗性功能總整理

## 完整編譯期 Feature Flags 清單（`feature()` from `bun:bundle`）

共發現 **82 個** 編譯期 feature flags。以下按類別整理：

---

### AI 寵物與 UI 功能

| Flag | 說明 | 狀態 |
|------|------|------|
| `BUDDY` | AI 寵物（Buddy）系統 | 2026-04-01 發布 |
| `AUTO_THEME` | 自動主題 | — |
| `MESSAGE_ACTIONS` | 訊息操作 UI | — |
| `HISTORY_PICKER` | 歷史記錄選擇器 | — |
| `HISTORY_SNIP` | 歷史記錄截取 | — |
| `TERMINAL_PANEL` | 終端面板 | — |
| `STREAMLINED_OUTPUT` | 精簡輸出 | — |
| `SHOT_STATS` | 統計截圖 | — |
| `QUICK_SEARCH` | 快速搜尋 | — |

### 語音與對話模式

| Flag | 說明 | 狀態 |
|------|------|------|
| `VOICE_MODE` | 語音模式 | 已上線（claude.ai OAuth 用戶） |
| `ULTRAPLAN` | UltraPlan 遠端規劃 | 已上線（關鍵字觸發） |
| `ULTRATHINK` | UltraThink（超級思考模式） | 已上線 |
| `COORDINATOR_MODE` | 協調者模式（多 agent 協調？） | 實驗性 |
| `PROACTIVE` | 主動模式 | 實驗性 |
| `AWAY_SUMMARY` | 離開摘要（AFK 模式） | 實驗性 |

### 記憶與學習系統

| Flag | 說明 | 狀態 |
|------|------|------|
| `EXTRACT_MEMORIES` | 自動記憶萃取 | 已上線 |
| `AGENT_MEMORY_SNAPSHOT` | Agent 記憶快照 | 實驗性 |
| `MEMORY_SHAPE_TELEMETRY` | 記憶形狀遙測 | 內部 |
| `KAIROS_DREAM` | KAIROS 模式的 Dream | KAIROS 限定 |
| `TEAMMEM` | 團隊記憶 | 實驗性 |
| `DOWNLOAD_USER_SETTINGS` | 下載使用者設定 | 實驗性 |
| `UPLOAD_USER_SETTINGS` | 上傳使用者設定 | 實驗性 |

### Computer Use 與 OS 整合

| Flag | 說明 | 狀態 |
|------|------|------|
| `CHICAGO_MCP` | Computer Use MCP（Chicago 代號） | Max/Pro 用戶 |
| `NATIVE_CLIPBOARD_IMAGE` | 原生剪貼簿圖片 | 實驗性 |
| `WEB_BROWSER_TOOL` | Web 瀏覽器工具 | 實驗性 |

### 遠端執行與 CCR

| Flag | 說明 | 狀態 |
|------|------|------|
| `CCR_AUTO_CONNECT` | CCR 自動連接 | 實驗性 |
| `CCR_MIRROR` | CCR 鏡像 | 實驗性 |
| `CCR_REMOTE_SETUP` | CCR 遠端設置 | 實驗性 |
| `BYOC_ENVIRONMENT_RUNNER` | BYOC 環境執行器 | Beta |
| `BRIDGE_MODE` | Bridge 模式 | 已上線 |
| `DIRECT_CONNECT` | 直連模式 | 實驗性 |
| `SSH_REMOTE` | SSH 遠端連接 | 實驗性 |
| `SELF_HOSTED_RUNNER` | 自行託管執行器 | 實驗性 |
| `DAEMON` | Daemon 模式 | 實驗性 |
| `UDS_INBOX` | Unix Domain Socket Inbox | 實驗性 |
| `BG_SESSIONS` | 背景 sessions | 實驗性 |

### Agent 與工作流

| Flag | 說明 | 狀態 |
|------|------|------|
| `AGENT_TRIGGERS` | Agent 觸發器 | 實驗性 |
| `AGENT_TRIGGERS_REMOTE` | 遠端 Agent 觸發器 | 實驗性 |
| `FORK_SUBAGENT` | Fork Subagent | 已上線 |
| `BUILTIN_EXPLORE_PLAN_AGENTS` | 內建探索/計畫 Agents | 實驗性 |
| `COORDINATOR_MODE` | 協調者模式 | 實驗性 |
| `VERIFICATION_AGENT` | 驗證 Agent | 實驗性 |
| `WORKFLOW_SCRIPTS` | 工作流腳本 | 實驗性 |
| `TEMPLATES` | 模板系統 | 實驗性 |

### KAIROS 系列（特殊模式）

> KAIROS 是 Claude Code 的特殊高效能模式，有獨立的 dream、brief、channels 等子系統。

| Flag | 說明 |
|------|------|
| `KAIROS` | KAIROS 主模式 |
| `KAIROS_BRIEF` | KAIROS 摘要模式 |
| `KAIROS_CHANNELS` | KAIROS 通道 |
| `KAIROS_DREAM` | KAIROS 夢境整合 |
| `KAIROS_GITHUB_WEBHOOKS` | KAIROS GitHub Webhooks |
| `KAIROS_PUSH_NOTIFICATION` | KAIROS 推送通知 |

### 工具與能力

| Flag | 說明 | 狀態 |
|------|------|------|
| `MCP_SKILLS` | MCP 技能 | 實驗性 |
| `MCP_RICH_OUTPUT` | MCP 豐富輸出 | 實驗性 |
| `EXPERIMENTAL_SKILL_SEARCH` | 實驗性技能搜尋 | 實驗性 |
| `SKILL_IMPROVEMENT` | 技能改進 | 實驗性 |
| `RUN_SKILL_GENERATOR` | 技能生成器 | 實驗性 |
| `MONITOR_TOOL` | 監控工具 | 實驗性 |
| `OVERFLOW_TEST_TOOL` | 溢出測試工具 | 內部 |
| `REVIEW_ARTIFACT` | 審查製品 | 實驗性 |
| `BUILDING_CLAUDE_APPS` | 建構 Claude Apps | 實驗性 |

### 上下文管理

| Flag | 說明 | 狀態 |
|------|------|------|
| `CONTEXT_COLLAPSE` | 上下文壓縮 | 實驗性 |
| `REACTIVE_COMPACT` | 反應式壓縮 | 實驗性 |
| `CACHED_MICROCOMPACT` | 快取微壓縮 | 實驗性 |
| `COMPACTION_REMINDERS` | 壓縮提醒 | 實驗性 |
| `TOKEN_BUDGET` | Token 預算 | 已上線 |
| `PROMPT_CACHE_BREAK_DETECTION` | Prompt 快取中斷偵測 | 內部 |

### 安全與分析

| Flag | 說明 | 狀態 |
|------|------|------|
| `BASH_CLASSIFIER` | Bash 命令分類器 | 已上線 |
| `TRANSCRIPT_CLASSIFIER` | Transcript 分類器（影響 AFK beta header） | 條件性 |
| `ANTI_DISTILLATION_CC` | 反蒸餾（反模型複製）機制 | 內部 |
| `ABLATION_BASELINE` | 消融基線（A/B 測試基線？） | 內部 |
| `NATIVE_CLIENT_ATTESTATION` | 原生客戶端認證 | 實驗性 |
| `HOOK_PROMPTS` | Hook prompt 注入 | 實驗性 |
| `ENHANCED_TELEMETRY_BETA` | 增強遙測（Beta） | Beta |
| `COWORKER_TYPE_TELEMETRY` | 同事類型遙測 | 內部 |

### 開發/調試工具

| Flag | 說明 |
|------|------|
| `DUMP_SYSTEM_PROMPT` | 傾印 system prompt（內部調試） |
| `BREAK_CACHE_COMMAND` | 中斷快取命令 |
| `HARD_FAIL` | 硬失敗模式（測試用） |
| `ALLOW_TEST_VERSIONS` | 允許測試版本 |
| `SLOW_OPERATION_LOGGING` | 慢操作日誌 |
| `PERFETTO_TRACING` | Perfetto 效能追蹤 |
| `FILE_PERSISTENCE` | 檔案持久化 |
| `LODESTONE` | Lodestone 功能 |

### 平台/連接器

| Flag | 說明 |
|------|------|
| `CONNECTOR_TEXT` | Connector 文字（影響 beta header） |
| `COMMIT_ATTRIBUTION` | Commit 歸因 |
| `POWERSHELL_AUTO_MODE` | PowerShell 自動模式 |
| `IS_LIBC_GLIBC` | glibc 平台偵測 |
| `IS_LIBC_MUSL` | musl 平台偵測 |
| `TORCH` | TORCH 功能（推測：熱點追蹤？） |
| `UNATTENDED_RETRY` | 無人值守重試 |

---

## 特別值得關注的隱藏功能

### 1. KAIROS 模式（6 個子 flags）
KAIROS 似乎是 Claude Code 的「高功能模式」，有自己的 dream（記憶整合）、brief（摘要）、channels（通道）、GitHub Webhooks 和推送通知等子系統。這可能是未來的 Agent 自主運行模式的前身。

### 2. ANTI_DISTILLATION_CC
反蒸餾（Anti-Distillation）機制——防止第三方模型從 Claude Code 的輸出中學習/複製能力。結合 `tengu_anti_distill_fake_tool_injection`（在工具中注入假資料），這是 Anthropic 對抗模型複製的防禦機制。

### 3. COORDINATOR_MODE / PROACTIVE
可能是多 agent 協調或主動式 agent 功能——Claude 主動發起動作而非等待使用者輸入。

### 4. DAEMON + UDS_INBOX + BG_SESSIONS
Daemon 模式 + Unix Domain Socket + 背景 sessions，組合起來暗示一個可以在背景持續運行並接收任務的 Claude Code 服務模式。

### 5. BUILDING_CLAUDE_APPS
協助使用者構建 Claude API 應用程式的功能，可能包含引導流程、模板和工具。

### 6. KAIROS_PUSH_NOTIFICATION
推送通知功能——可能讓 Claude 在長時間任務完成後主動通知使用者（即使 terminal 在背景）。

### 7. SSH_REMOTE + SELF_HOSTED_RUNNER
SSH 遠端連接和自行託管執行器——允許 Claude Code 連接到遠端機器直接操作。

---

## 隱藏命令補充（`src/commands/` 目錄完整掃描）

除了前述分析外，還發現以下隱藏命令：

| 命令 | 說明 |
|------|------|
| `/heapdump` | `isHidden: true`，Node.js 堆記憶體轉儲（內部調試） |
| `/output-style` | `isHidden: true`，輸出樣式控制 |
| `/rate-limit-options` | `isHidden: true`，速率限制選項（內部使用） |
| `/thinkback-play` | `isHidden: true`，快速重播年度回顧 |
| `/mock-limits` | 模擬速率限制（測試用） |
| `/heapdump` | 記憶體分析 |
| `/break-cache` | 中斷 prompt cache（`feature('BREAK_CACHE_COMMAND')` 保護） |
| `/ant-trace` | Anthropic 內部追蹤命令 |
| `/perf-issue` | 效能問題報告 |
| `/ctx_viz` | Context 視覺化 |
| `/debug-tool-call` | 工具呼叫調試 |

---

## 發布時間線推斷

| 日期 | 事件 |
|------|------|
| 2025-02-19 | Claude Code beta 公開 |
| 2025-05-14 | Interleaved thinking |
| 2025-08-07 | 1M context |
| 2025-11-20 | Advanced tool use |
| 2025-12-15 | Structured outputs |
| 2026-01-05 | Prompt caching scope |
| 2026-01-31 | AFK mode beta |
| 2026-02-01 | Fast mode |
| 2026-02-12 | Redact thinking |
| 2026-03-01 | Advisor tool |
| 2026-03-13 | Task budgets + Connector text |
| 2026-03-28 | Token efficient tools |
| **2026-04-01** | **Buddy AI 寵物（預計）** |
