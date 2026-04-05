# Memory & Context 管理系統架構全景圖

## 一、系統全貌

Claude Code 的 Memory 系統是一個多層次、多機制並存的持久化記憶架構。其核心設計目標是讓模型能跨 session 記住使用者偏好、專案脈絡與回饋，同時維持架構的可靠性、安全性與資源效率。

```
Memory 系統層次結構
─────────────────────────────────────────────────────
[永久記憶層] Auto Memory (memdir)
   ├── MEMORY.md — 索引文件，每次 session 自動載入
   ├── 主題記憶文件 (user_*.md, feedback_*.md, ...)
   ├── logs/ — KAIROS 模式的 append-only 日誌
   └── team/ — Team Memory (TEAMMEM feature)

[Session 記憶層] Session Memory
   └── ~/.claude/session-memory/<session>.md

[動態文件層] MagicDocs
   └── 用戶 repo 中任何帶 # MAGIC DOC: 標頭的 .md 檔

[Context 壓縮層] Compact / Context Compaction
   └── 對話歷史摘要 (base / partial / partial_up_to)

[記憶提取層] ExtractMemories
   └── 每輪對話結束後的背景記憶提取 subagent

[夢境整合層] AutoDream
   └── 跨 session 定期記憶鞏固 subagent
─────────────────────────────────────────────────────
```

## 二、各子系統職責對應

| 子系統 | 觸發時機 | 主要檔案 | 作用 |
|---|---|---|---|
| Auto Memory (memdir) | session 啟動 / 模型主動寫入 | `memdir.ts`, `paths.ts` | 跨 session 永久記憶 |
| ExtractMemories | 每輪 query 結束 | `extractMemories.ts` | 背景自動提取記憶 |
| Session Memory | context 達門檻 | `sessionMemory.ts` | 當前 session 快照筆記 |
| MagicDocs | 對話結束 (idle) | `magicDocs.ts` | 自動維護特定文件 |
| Team Memory | session 啟動 / 文件變更 | `teamMemorySync/` | 跨用戶團隊共享記憶 |
| AutoDream | 定期 (24h+5 sessions) | `autoDream.ts` | 跨 session 記憶整合 |
| Context Compact | context 接近上限 | `compact/prompt.ts` | 壓縮對話歷史 |

## 三、記憶類型分類

系統定義了四種封閉類型（`memoryTypes.ts`），確保記憶有明確語義：

| 類型 | 說明 | 預設範圍 |
|---|---|---|
| `user` | 使用者角色、目標、知識背景 | 私人 |
| `feedback` | 指導原則（錯誤修正 + 成功確認） | 私人優先 |
| `project` | 專案進行中的目標、決策、事件 | 團隊優先 |
| `reference` | 外部系統指標（Linear、Grafana 等） | 通常團隊 |

**明確禁止記憶的資訊**：
- 可從程式碼推導的架構、慣例
- git 歷史、誰改了什麼
- 已在 CLAUDE.md 記錄的事項
- 臨時任務狀態、當前 session 上下文

## 四、Feature Flag 控制

所有子系統都有 GrowthBook feature flag 控制：

| Flag | 控制對象 |
|---|---|
| `tengu_passport_quail` | ExtractMemories 啟用 |
| `tengu_session_memory` | Session Memory 啟用 |
| `tengu_herring_clock` | Team Memory 啟用 |
| `tengu_onyx_plover` | AutoDream 啟用 + 排程設定 |
| `tengu_coral_fern` | 過去 context 搜尋段落 |
| `tengu_moth_copse` | skipIndex 模式（略過 MEMORY.md 索引） |
| `tengu_bramble_lintel` | ExtractMemories 節流間隔 |

## 五、資料流向圖

```
用戶對話 ──→ 主 REPL loop
              │
              ├── 每輪結束 ──→ ExtractMemories (forked agent)
              │                  └── 寫入 ~/.claude/projects/<proj>/memory/
              │
              ├── context 達門檻 ──→ Session Memory (forked agent)
              │                        └── 寫入 ~/.claude/session-memory/<id>.md
              │
              ├── 讀到 Magic Doc ──→ MagicDocs (idle 後 forked agent)
              │                        └── 原地更新 repo 內的 .md 檔
              │
              └── 定時觸發 ──→ AutoDream (forked agent)
                               └── 整合 logs/ + 記憶文件 → 精煉 MEMORY.md

session 啟動 ──→ 載入 MEMORY.md → 注入 system prompt
              └── Team Memory pull → 同步 ~/.../memory/team/

context 超限 ──→ Context Compact → 替換對話歷史為摘要
```

## 六、路徑系統

記憶路徑的解析優先鏈（`paths.ts`）：
1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` 環境變數（Cowork 用）
2. settings.json `autoMemoryDirectory`（支援 `~/` 展開）
3. 預設：`{memoryBase}/projects/{sanitized-git-root}/memory/`

`memoryBase` 優先順序：
1. `CLAUDE_CODE_REMOTE_MEMORY_DIR` 環境變數
2. `~/.claude`（`getClaudeConfigHomeDir()`）

所有路徑解析都經過安全驗證（防止 null bytes、路徑穿越、UNC paths、Windows drive roots）。
