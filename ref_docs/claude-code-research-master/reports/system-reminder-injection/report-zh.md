# 逆向 Claude Code 的 System-Reminder 注入機制

Claude Code 在每輪 API request 中動態注入 `<system-reminder>` 內容區塊。這些區塊在 UI 中不可見、不存在對話歷史檔案中，且模型被指示永遠不要提及它們。目前有超過 15 種類型，每輪對話都會重新注入。

本報告基於對 `@anthropic-ai/claude-code` v2.1.71 的 `cli.js` 逆向工程，交叉比對 30+ 個 GitHub open issues 和 session JSONL 數據分析，完整記錄注入機制。

本報告是[報告 #1（Agent SDK Cache 失效）](../agent-sdk-cache-invalidation/)的姊妹篇。第一篇講成本影響，這篇聚焦注入機制本身。

---

## 完整類型清單

來源：cli.js 逆向 + [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts)

### 每輪固定注入

| system-reminder | 觸發條件 | 估計佔用量 |
|---|---|---|
| malware analysis | 每次 Read file | ~50 tokens × 讀檔次數 |
| file modified by user or linter | 檔案 mtime 變化（IDE autosave、linter、hook 寫檔等） | ~30 tokens + 檔案 diff（可能很大） |
| TodoWrite reminder | 一段時間沒用 TodoWrite | ~80 tokens |
| Task tools reminder | 一段時間沒用 TaskCreate/TaskUpdate | ~80 tokens |
| memory file contents | 每輪 user message 附帶 MEMORY.md 內容 | MEMORY.md 全文大小 |
| invoked skills | 每輪注入可用 skills 列表 | ~2000+ tokens（隨 skill 數量增長） |

### 條件觸發

| system-reminder | 觸發條件 | 估計佔用量 |
|---|---|---|
| hook success/error/context | 每個 hook 執行結果 | 依 hook stdout 大小 |
| hook stopped continuation | hook block 時 | ~30 tokens + message |
| file exists but empty | 讀到空檔案 | ~30 tokens |
| file truncated | 檔案太長被截斷 | ~30 tokens |
| file shorter than offset | Read 的 offset 超過檔案長度 | ~30 tokens |
| new diagnostics detected | LSP/IDE 回報新的錯誤/警告 | ~50 tokens + 診斷內容 |
| file opened in IDE | IDE 中開啟了檔案 | ~30 tokens + 檔案資訊 |
| lines selected in IDE | IDE 中選取了程式碼 | ~30 tokens + 選取內容 |
| session continuation | context compaction 後的延續摘要 | 數百至數千 tokens |
| token usage | 接近 context 上限時 | ~50 tokens |
| USD budget | 接近預算上限時 | ~30 tokens |
| compact file reference | compaction 後引用被壓縮的檔案 | 不定 |
| plan mode active | plan mode 開啟時 | ~100 tokens |
| output style active | 指定輸出風格時 | ~30 tokens |
| team coordination/shutdown | 多 agent 團隊模式 | ~100 tokens |
| agent mention | 被 @ 提及 | ~30 tokens |

### File Modification 注入模板

```
Note: ${filename} was modified, either by the user or by a linter.
This change was intentional, so make sure to take it into account as you proceed
(ie. don't revert it unless the user asks you to). Don't tell the user this, since
they are already aware. Here are the relevant changes (shown with line numbers):
${snippet}
```

---

## 歷史變遷

### 第一階段：隱形但輕量（2025 年中）

- 2025-07：[#4464](https://github.com/anthropics/claude-code/issues/4464) 第一份報告
- 當時主要就是 malware reminder（每次 Read 約 50 tokens）
- 用 `isMeta: true` 標記，UI 層直接過濾
- 大部分使用者完全不知道它的存在

### 第二階段：File Modification 開始膨脹（2025 Q4 ~ 2026 Q1）

- 2025-10：[#9769](https://github.com/anthropics/claude-code/issues/9769) 請求加開關（至今未加）
- 2026-01-02：[#16021](https://github.com/anthropics/claude-code/issues/16021) 發現每則 user message 都注入數百行程式碼
- 2026-01-12：[#17601](https://github.com/anthropics/claude-code/issues/17601) mitmproxy 抓到 10,577 次隱藏注入

關鍵轉折：file modification reminder 從「通知一次」變成「每則 user message 都重複注入」。VS Code 擴充套件尤其嚴重——Claude 自己的 Edit 也觸發。CLI 稍好——只在 user edit 時注入一次。

### 第三階段：種類爆增（2026 Q1）

- TodoWrite reminder、Task tools reminder、IP reminder（著作權提醒）、Skills 列表注入、diagnostics 注入陸續加入
- 注入類型從 1-2 種暴增到 15+ 種
- 每種都帶 `NEVER mention this reminder`
- 2026-01-16：[#18560](https://github.com/anthropics/claude-code/issues/18560) system-reminder 開始覆蓋 CLAUDE.md 指令

### 第四階段：行為劣化（2026-02 ~ 03）

- 2026-02-06：[#23537](https://github.com/anthropics/claude-code/issues/23537) 模型把 system-reminder 當成使用者指令執行
- 2026-02-22：[#27599](https://github.com/anthropics/claude-code/issues/27599) headless 模式無限重複
- 2026-03-05：[#30730](https://github.com/anthropics/claude-code/issues/30730) sub-agent 注入覆蓋自定義 agent 定義
- 2026-03-06：[#31447](https://github.com/anthropics/claude-code/issues/31447) Claude 聲稱 system-reminder 是「被注入的」，要使用者放寬權限
- 2026-03-06：v2.1.70 惡化——整個檔案內容被注入（1300 行，每輪 15%+ context）
- 2026-03-07：v2.1.71 確認——Edit 過但沒 Re-read 的檔案永遠被視為 stale

---

## 核心機制：檔案追蹤表（readFileState）

`readFileState` 是一個 LRU Cache（最大 100 個 entry），每筆 entry 追蹤一個檔案：

```javascript
{
  content: string,      // 檔案內容快照
  timestamp: number,    // 記錄時間（ms）
  offset: number | undefined,
  limit: number | undefined
}
```

### 四個寫入點

| 來源 | key 格式 | offset | limit | timestamp 來源 |
|---|---|---|---|---|
| Memory 載入（CLAUDE.md、MEMORY.md） | 原始路徑（不正規化） | `undefined` | `undefined` | `Date.now()` |
| Read tool | 正規化路徑 | `1`（預設值） | `undefined` | `Math.floor(mtimeMs)` |
| Write/Edit tool | 正規化路徑 | `undefined` | `undefined` | 檔案 mtime |
| Session resume（重建函數） | 正規化路徑 | `undefined` | `undefined` | JSONL 訊息時間戳 |

關鍵觀察：**Read 反而安全，Edit/Write 才會中招。** Read 預設 `offset: 1`，stale check 會跳過它。Edit/Write 設 `offset: undefined`，entry 會被永遠追蹤。

### Stale Check（每輪 user message 執行）

每次使用者發訊息時，cli.js 遍歷追蹤表：

```
對 readFileState 中的每個 entry：
  1. offset 或 limit 不是 undefined → 跳過（不追蹤）
  2. 檔案 mtime <= 記錄的 timestamp → 跳過（沒變）
  3. 重新讀檔，計算 diff
  4. diff 為空 → 跳過
  5. diff 不為空 → 注入 system-reminder
```

五個條件全部滿足才會注入。

---

## File Modification 注入的五個觸發條件

| # | 條件 | 不觸發的情況 |
|---|---|---|
| 1 | 檔案在 readFileState 裡 | 從沒被 Read/Edit 過、也不是 CLAUDE.md/MEMORY.md |
| 2 | 不是 partial read（offset 和 limit 都是 `undefined`） | Read tool 預設 offset=1 → stale check 跳過 |
| 3 | mtime > timestamp | mtime 精度 race condition：Edit 和 timestamp 記錄在同一個 ms 內 → 跳過 |
| 4 | 能成功 Read 檔案 | 檔案被刪了、權限問題 → 從 tracking 移除 |
| 5 | diff 不為空 | 內容實際沒變（IDE autosave 同內容）→ 跳過 |

---

## 注入不穩定觸發的三個根因

### 根因 1：路徑 key 不一致

追蹤表有多個寫入點，使用不同的 key 格式：

- Memory 載入：原始路徑（不經正規化）
- Read/Write/Edit tool：正規化路徑（NFC Unicode 正規化 + 路徑解析）

在 Windows 上，正規化可能改變路徑字串（`.normalize("NFC")`、`/c/` → `C:\` 等），導致同一個檔案有兩筆 entry。stale check 遍歷到原始 key 時觸發，但內部重讀更新到正規化 key → 原始 key entry 永遠不被更新 → 無限注入循環。

### 根因 2：mtime 精度 Race Condition

```
Claude Edit 寫檔 → 追蹤表記錄 timestamp from mtime          // T1
→ 外部程序（IDE autosave、linter、git hook）touch 了檔案     // mtime 變成 T2
→ stale check：目前 mtime T2 > 記錄的 T1 → 觸發
```

Windows NTFS 的 mtime 精度是 100ns，但 JS `Date.now()` 是 ms。如果 Edit 和 timestamp 記錄在同一個 ms 內完成，`mtime <= timestamp` 成立 → 不觸發。反之則觸發。

### 根因 3：Stale Check 不更新原始 entry

偵測到變更後，stale check 函數只回傳 diff，不更新原始 key 的 content 和 timestamp。內部重讀更新的是正規化 key。如果原始 key ≠ 正規化 key，原始 entry 的值永遠停留在舊狀態。

---

## CLI vs Agent SDK 的運作差異

| | CLI 互動模式 | Agent SDK / 無頭模式 |
|---|---|---|
| 追蹤表生命週期 | 整個 session 共用一份，活到 session 結束 | 每次 `submitMessage()` 從 JSONL 全量重建 |
| CLAUDE.md/MEMORY.md 載入 | session 開始載入一次，`.has()` 檢查不重複加 | 每次初始化都重新載入 → 每次都重新加回原始路徑 key |
| 結果 | 有時觸發有時不觸發（看 LRU 快取裡有沒有撞 key） | 穩定觸發（因為每輪都重建追蹤表） |

### Agent SDK 的根本問題

`readFileState` 不是 class property（沒有 `this.readFileState`），它是 `submitMessage()` 內的區域變數。每次呼叫都從 `this.mutableMessages` 用重建函數全量重建——所有 entry 都是 `offset: undefined` + 過去時間戳——所以每次都觸發注入。

```
submitMessage() 被呼叫
  → readFileState = rebuild(this.mutableMessages)  ← 從 JSONL 全量重建，max=10
  → stale check → 注入 diff
  → 主迴圈跑完，Edit/Write 更新了記憶體中的 readFileState
  → 下一次 submitMessage()
  → readFileState = rebuild(this.mutableMessages)  ← 又從頭重建，之前的更新全丟
  → 永遠注入
```

---

## Session Resume：追蹤表的重建機制

CLI `--resume` 或 Agent SDK `resume: true` 時，cli.js 從 JSONL 對話歷史重建追蹤表。

### 重建邏輯

```javascript
// 從反混淆源碼簡化
function rebuildTrackingTable(messages, cwd, maxEntries = 10) {
  let cache = new LRUCache(maxEntries);
  let readOps = new Map();   // tool_use_id → 正規化路徑
  let writeOps = new Map();  // tool_use_id → { path, content }

  // 第一輪：掃描 assistant 訊息，收集 Read 和 Write 的 tool_use
  for (let msg of messages) {
    if (msg.type === "assistant") {
      for (let block of msg.message.content) {
        // 只收集「無 offset、無 limit」的 Read
        if (block.name === "Read"
            && block.input.offset === undefined
            && block.input.limit === undefined) {
          readOps.set(block.id, normalize(block.input.file_path));
        }
        // 收集帶 content 的 Write
        if (block.name === "Write"
            && block.input.file_path
            && block.input.content) {
          writeOps.set(block.id, { path, content });
        }
        // Edit 不處理
      }
    }
  }

  // 第二輪：掃描 user 訊息，找對應的 tool_result
  for (let msg of messages) {
    if (msg.type === "user") {
      for (let block of msg.message.content) {
        if (block.type === "tool_result") {
          let readPath = readOps.get(block.tool_use_id);
          if (readPath) {
            cache.set(readPath, {
              content: cleanContent(block.content),
              timestamp: new Date(msg.timestamp).getTime(),  // 過去時間
              offset: undefined,   // 永遠 undefined
              limit: undefined     // 永遠 undefined
            });
          }
        }
      }
    }
  }
  return cache;
}
```

### 四個關鍵問題

**1. Edit 操作完全被忽略。** 重建函數只處理 Read（無 offset/limit）和 Write。Edit——最常見的修改方式——不被處理。session 中用 Edit 修改的檔案不會透過這條路徑進入追蹤表。

**2. 帶預設 offset=1 的 Read 也被忽略。** 收集條件是 `offset === undefined`，但 Read tool 的預設值是 `offset: 1`，所以大多數正常的 Read 操作不被收集。只有極少數明確用 `offset: undefined` 的 Read 才會進表。

**3. 最多 10 筆（Agent SDK）vs 100 筆（CLI）。** Agent SDK 重建用 max=10，超過 10 個檔案的操作會被 LRU 淘汰。留下的 10 筆全部 `offset: undefined`，全部用過去時間戳。

**4. timestamp 用 JSONL 的過去時間。** `new Date(msg.timestamp).getTime()` 取的是訊息原始記錄時間。resume 後檔案的 mtime 幾乎一定比這個時間新 → stale check 觸發 → 注入。

---

## 隱藏機制

| 機制 | 效果 |
|---|---|
| `isMeta: true` flag | UI 層完全隱藏，使用者在介面看不到 |
| JSONL 不記錄 | session 檔案裡找不到，事後分析看不到 |
| `NEVER mention this reminder` | Claude 被指示不主動揭露 |
| LaunchDarkly feature flags | 服務端控制，使用者無法關閉 |
| Runtime 動態注入 | 只存在於 API request，不落地 |

唯一能觀察到的方式：

1. **mitmproxy** — 攔截實際的 API request（[#17601](https://github.com/anthropics/claude-code/issues/17601) 的方法）
2. **直接問 Claude** — 有時 Claude 會違反 `NEVER mention` 指令揭露
3. **Token 消耗異常** — 間接推斷

---

## 已知 Bug

### Bug 1：路徑 key 不一致（根因級）

- **位置**：Memory 載入 vs Read/Write/Edit tool
- **問題**：Memory 載入用原始路徑作為 key，Read/Write/Edit 用正規化路徑。同一檔案可能有兩筆 entry。
- **影響**：stale check 的原始 key entry 永遠不被解消 → 無限注入

### Bug 2：Stale Check 不更新 readFileState（根因級）

- **位置**：stale check 函數
- **問題**：偵測到 stale 後只回傳 diff，不更新原始 key 的 content 和 timestamp
- **影響**：每輪都重新偵測到「變更」→ 每輪都注入

### Bug 3：重建函數全部設 offset: undefined

- **位置**：追蹤表重建函數
- **問題**：重建的 entry 全部 `offset: undefined` → 全部被追蹤。timestamp 用過去時間 → 幾乎一定比 mtime 舊。
- **影響**：session resume 後幾乎必定觸發大量注入

### Bug 4：Edit/Write 後 offset 設為 undefined

- **位置**：Write/Edit tool 的 `.set()` 呼叫
- **問題**：Edit/Write 後的 entry 的 offset 和 limit 都是 `undefined` → stale check 永遠追蹤
- **影響**：Claude 自己改過的檔案從此被永遠追蹤。Read tool 的預設 offset=1 反而能「修復」（offset !== undefined → 跳過）

---

## 社群影響：30+ 個 GitHub Open Issues

### Token 浪費（最多人回報）

| Issue | 標題 | 留言數 | 日期 |
|---|---|---|---|
| [#16021](https://github.com/anthropics/claude-code/issues/16021) | 每則 user message 都注入數百行修改檔案備註 | 23 | 2025-01-02 |
| [#4464](https://github.com/anthropics/claude-code/issues/4464) | system-reminder 消耗過多 context tokens | 22 | 2025-07-25 |
| [#17601](https://github.com/anthropics/claude-code/issues/17601) | 隱藏注入 10,000+ 次，吃掉 15%+ context window | 10 | 2026-01-12 |
| [#21214](https://github.com/anthropics/claude-code/issues/21214) | 每次 Read file 都注入 system-reminder，浪費百萬 tokens | 4 | 2026-01-27 |
| [#25327](https://github.com/anthropics/claude-code/issues/25327) | CLI wrapper 注入 =「好工程的 token 稅」 | 0 | 2026-02-12 |
| [#27721](https://github.com/anthropics/claude-code/issues/27721) | Skills 被 system prompt 重複註冊，context 用量翻倍 | 1 | 2026-02-22 |
| [#27599](https://github.com/anthropics/claude-code/issues/27599) | headless 模式下 system-reminder 無限重複 | 2 | 2026-02-22 |

### 安全 / 信任問題

| Issue | 標題 | 留言數 | 日期 |
|---|---|---|---|
| [#18560](https://github.com/anthropics/claude-code/issues/18560) | system-reminder 指示 Claude 不遵守 CLAUDE.md | 3 | 2026-01-16 |
| [#31447](https://github.com/anthropics/claude-code/issues/31447) | Claude 聲稱 system messages 是「被注入的」，社交工程使用者放寬權限 | 2 | 2026-03-06 |
| [#23537](https://github.com/anthropics/claude-code/issues/23537) | system task reminders 偽裝成 user input，模型無法區分 | 2 | 2026-02-06 |
| [#27128](https://github.com/anthropics/claude-code/issues/27128) | system-generated messages 被誤標為 Human: turn，導致未授權行為 | 4 | 2026-02-20 |

### 功能性 Bug

| Issue | 標題 | 留言數 | 日期 |
|---|---|---|---|
| [#31458](https://github.com/anthropics/claude-code/issues/31458) | system-reminder 在對話持久化時被剝離，破壞 grounding | 2 | 2026-03-06 |
| [#26370](https://github.com/anthropics/claude-code/issues/26370) | Compaction 後 system-reminder 殘留舊 Read 結果造成混亂 | 1 | 2026-02-17 |
| [#25810](https://github.com/anthropics/claude-code/issues/25810) | Memory system 錯誤回報 MEMORY.md 為空 | 0 | 2026-02-14 |

### Feature Request

| Issue | 標題 | 留言數 | 日期 |
|---|---|---|---|
| [#9769](https://github.com/anthropics/claude-code/issues/9769) | 讓所有 system-reminder 類型可個別開關 | 4 | 2025-10-17 |

---

## 緩解方案

| 方案 | 效果 | 成本 | 適用場景 |
|---|---|---|---|
| CLAUDE.md 加忽略指令 | 中（不穩定） | 低 | 所有場景的基線 |
| **JSONL 預處理** | **高（根治 resume 注入）** | **中** | **CLI resume / Agent SDK** |
| Edit 後強制 re-read | 中 | 額外 Read token | 追蹤檔案數量少時 |
| Memory 檔寫到 cwd 外面 | 高（根治） | 架構調整 | 有 memory 寫入的專案 |
| 避免讓 CLI 工具修改大檔案（改用 MCP tool） | 高 | 架構調整 | 有大 JSON/config 的專案 |
| 短 session + 頻繁 compact | 中 | 增加 session 管理複雜度 | 互動模式 |
| [Cozempic](https://github.com/Ruya-AI/cozempic) daemon | 中 | 第三方依賴 | CLI 互動模式 |
| 直接用 Claude API 不走 CC CLI | 高 | 重寫 orchestration | Agent SDK / 生產環境 |
| 等官方加 `--no-system-reminders` | 最高 | 等 | [#9769](https://github.com/anthropics/claude-code/issues/9769)（2025-10 開到現在） |

### JSONL 預處理（Agent SDK 推薦方案）

追蹤表重建函數有具體的收集條件：
- Read：`offset === undefined && limit === undefined`
- Write：`file_path && content`

在 resume 前破壞這些條件，重建函數產出空表 → 不觸發 file modification 注入。

**方法**：給 JSONL 中所有 Read entry 加上 `offset: 1`，移除所有 Write entry 的 `content`。重建函數的條件不再匹配，不收集任何 entry。

```python
# 核心邏輯（簡化）
for block in assistant_message.content:
    if block.name == "Read" and block.input.offset is None:
        block.input["offset"] = 1      # 破壞收集條件
    if block.name == "Write" and "content" in block.input:
        del block.input["content"]      # 破壞收集條件
```

在每次 `--resume` 或 Agent SDK `resume: true` 前執行。

**副作用**：Write tool 首次寫未讀過的檔案會報 `"File has not been read yet"`（errorCode: 2），但 Claude 會自動先 Read 再 Write，實務上不影響。

**不影響的部分**：CLAUDE.md/MEMORY.md 透過 memory 載入路徑載入，不受此方法影響。這些檔案的 timestamp 用 `Date.now()`，通常不會觸發注入。

完整 JSONL 預處理器實作和 V2 persistent session 方案見[報告 #1](../agent-sdk-cache-invalidation/)。

---

## 附錄：Memory 檔案如何進入追蹤表

Claude Code 的「memory 檔案」是指被 memory 載入機制處理的檔案：

| 類型 | 檔案 | 路徑 |
|---|---|---|
| Managed | Anthropic 內建規則 | 系統目錄 |
| User | `~/.claude/CLAUDE.md` | 全域指令 |
| Project | `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*.md` | 專案根目錄往上每一層 |
| Local | `CLAUDE.local.md` | 專案本地指令 |
| AutoMem | `MEMORY.md` | `~/.claude/projects/<project-hash>/memory/MEMORY.md` |
| TeamMem | team memory | 組織共享 |

使用者自訂的檔案（如 `memory/2026-03-08.md`）不在此列。它們進入追蹤表的途徑是 Claude 用 Edit/Write 修改它們時，設了 `offset: undefined`——從此被永遠追蹤。

---

## SDK 版本基準

研究基於 `@anthropic-ai/claude-code` v2.1.71 / Claude Code v2.1.71（2026 年 3 月）。內部函數名稱是混淆過的，每次版本更新都會改變。本報告描述的機制是透過字串常數錨點定位（如 `"was modified, either by the user"`、`"Cannot send to closed session"`），這些字串在版本間是穩定的。
