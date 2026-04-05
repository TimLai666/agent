# Memory 設計原則提煉

## 原則一：記憶只儲存不可推導的資訊

```typescript
// memoryTypes.ts - WHAT_NOT_TO_SAVE_SECTION
'- Code patterns, conventions, architecture, file paths, or project structure — these can be derived by reading the current project state.'
'- Git history, recent changes, or who-changed-what — `git log` / `git blame` are authoritative.'
'- Debugging solutions or fix recipes — the fix is in the code; the commit message has the context.'
```

**核心哲學**：記憶系統補充可觀測資訊，而非複製它。程式碼、git 歷史、文件架構都是即時可查的「真相來源」；只有無法從這些來源推導的脈絡（用戶偏好、決策理由、外部系統指標、組織知識）才值得記憶。

這個設計防止了「記憶腫脹」——模型傾向於記錄所有事情，但大量冗餘記憶會稀釋真正有用的資訊。

---

## 原則二：記憶是時間點觀察，不是即時狀態

```typescript
// memoryTypes.ts - TRUSTING_RECALL_SECTION
'A memory that names a specific function, file, or flag is a claim that it existed *when the memory was written*. It may have been renamed, removed, or never merged. Before recommending it: ...'
'"The memory says X exists" is not the same as "X exists now."'
```

```typescript
// memoryAge.ts
export function memoryFreshnessText(mtimeMs: number): string {
  // 超過 1 天的記憶顯示警告
  return `This memory is ${d} days old. Memories are point-in-time observations, not live state — claims about code behavior or file:line citations may be outdated.`
}
```

**設計動機**：使用者回報模型把過時的 file:line 引用當作事實斷言——引用使過時聲明更具說服力，而非更少。「47 days ago」這樣的年齡表示比原始 ISO 時間戳更能觸發模型的過期推理。

---

## 原則三：記憶 Prompt 的措辭和位置影響行為（eval-validated）

```typescript
// memoryTypes.ts 中的 TRUSTING_RECALL_SECTION 開頭注釋
// H1 (eval 2026-03-17):
// 標題「Before recommending」（行動提示點）→ 3/3
// 標題「Trusting what you recall」（抽象標題）→ 0/3
// 相同的本體文字，只有標題不同
```

```typescript
// H6（branch-pollution eval #22856, case 5）：
// 「ignore」用法的 anti-pattern 描述
// 失敗：模型看到「ignore memory about X」→ 讀取程式碼正確但追加「not Y as noted in memory」
// 修復：明確命名 anti-pattern：「proceed as if MEMORY.md were empty. Do not apply remembered facts, cite, compare against, or mention memory content」
```

**設計方法論**：Memory 相關的 prompt 文字通過 A/B eval 測試驗證效果，不純憑直覺。標題定位（action trigger vs abstract）、anti-pattern 的明確命名、例子的具體程度都會影響模型行為。

---

## 原則四：記憶的增量性（cursor-based, not full-scan）

```typescript
// extractMemories.ts
let lastMemoryMessageUuid: string | undefined  // 游標

function countModelVisibleMessagesSince(messages, sinceUuid): number {
  // 只計算游標之後的新訊息
}
```

記憶提取系統不每次重新分析整個對話歷史，而是維護一個游標，只處理上次提取之後的新訊息。這讓系統在長對話中保持 O(new messages) 的開銷，而非 O(total messages)。

---

## 原則五：背景子系統必須與主代理互斥

```typescript
// extractMemories.ts
if (hasMemoryWritesSince(messages, lastMemoryMessageUuid)) {
  // 主代理已自己寫記憶 → 跳過背景提取，只推進游標
  return
}
```

主代理的 prompt 包含完整的記憶保存指令；若主代理主動寫記憶，背景提取是冗餘的（可能還有衝突）。這個「誰先寫誰優先，另一方退出」的設計防止了雙重寫入。

---

## 原則六：工具權限最小化（Principle of Least Privilege）

| 子系統 | 允許的工具 | 理由 |
|---|---|---|
| ExtractMemories | Read/Grep/Glob（無限制）+ 唯讀 Bash + Write/Edit（限 memory 目錄） | 需要讀取對話脈絡，只能寫自己的記憶空間 |
| AutoDream | 同上（共享 createAutoMemCanUseTool） | 同上 |
| Session Memory | 只允許 Edit（指定文件） | 只更新一個文件 |
| MagicDocs | 只允許 Edit（指定文件） | 只更新被追蹤的 Magic Doc 文件 |

各子系統的工具集根據其最小需求設計，不繼承主代理的全套工具。

---

## 原則七：Prompt Cache 共享是核心效能策略

```typescript
// extractMemories.ts, autoDream.ts
const cacheSafeParams = createCacheSafeParams(context)
const result = await runForkedAgent({
  cacheSafeParams,
  // ...
})
```

所有背景記憶子系統都使用 forked agent 模式，繼承父對話的 system prompt 和 message prefix。這讓 forked agent 能重用父對話的 prompt cache，而非重建整個上下文。

**測量結果**（extractMemories 日誌）：
```
cache: read=XXXXX create=YYYYY input=ZZZZZ (N% hit)
```

高 cache hit 率是這些背景子系統在實際使用中保持低成本的關鍵。

---

## 原則八：系統不讓模型做不必要的探索

```typescript
// extractMemories/prompts.ts - opener()
`You MUST only use content from the last ~${newMessageCount} messages to update your persistent memories. Do not waste any turns attempting to investigate or verify that content further — no grepping source files, no reading code to confirm a pattern exists, no git commands.`
```

```typescript
// memdir.ts - DIR_EXISTS_GUIDANCE
'This directory already exists — write to it directly with the Write tool (do not run mkdir or check for its existence).'
```

背景子系統有嚴格的 turn 預算（extractMemories 最多 5 turns），必須防止模型花 turn 在「確認環境」或「驗證資訊」上。Prompt 明確說明哪些探索是被禁止的，harness 透過保證（目錄已存在、只處理指定訊息範圍）支持這些約束。

---

## 原則九：記憶的品質優先於數量

```typescript
// memoryTypes.ts - WHAT_NOT_TO_SAVE_SECTION（最後的強制規則）
'These exclusions apply even when the user explicitly asks you to save. If they ask you to save a PR list or activity summary, ask what was *surprising* or *non-obvious* about it — that is the part worth keeping.'
```

即使用戶明確要求，系統也不記錄活動日誌或 PR 清單。引導模型問「什麼是令人驚訝的或非顯而易見的」——這才是值得跨 session 保留的資訊。

這個設計防止記憶系統退化為日誌系統。

---

## 原則十：失敗模式設計（Fail Gracefully, Not Hard）

**ExtractMemories**：
- 提取失敗 → 記 debug log，不通知用戶，游標不前進（下次包含失敗的訊息重試）
- 遠端模式 → 不執行
- 主代理已寫 → 跳過，不是錯誤

**Team Memory Watcher**：
- 永久失敗（no_oauth, 4xx）→ 設定 pushSuppressedReason，停止無意義重試
- 超過 167K push 事件的設計教訓直接影響了抑制機制的誕生

**AutoDream**：
- 失敗 → 回滾鎖的 mtime（讓時間門檻下次繼續有效）
- 用戶中止 → DreamTask 已回滾，不重複

**MEMORY.md 截斷**：
- 超限 → 截斷 + 警告，不拒絕載入。模型看到警告後知道索引不完整，可決定是否整理。

---

## 原則十一：記憶的可信度遞減（Trust Hierarchy）

記憶可信度的優先序（從高到低）：
1. **當前程式碼狀態**（`git log`、讀取文件）
2. **新鮮記憶**（今天/昨天建立的）
3. **較舊記憶**（有過期警告的）
4. **沉澱記憶**（活動快照，repository state summaries）

```typescript
'A memory that summarizes repo state (activity logs, architecture snapshots) is frozen in time. If the user asks about *recent* or *current* state, prefer `git log` or reading the code over recalling the snapshot.'
```

---

## 原則十二：四類型分類法的設計原理

```
user       → 調整溝通方式（服務個人）
feedback   → 改變行為（成功和失敗都記錄）
project    → 理解動機（for whom, why, by when）
reference  → 知道去哪找（指向外部）
```

這個分類法的設計讓每種記憶有明確的「何時讀取」和「如何使用」：
- `user`：任何需要根據對方背景調整的場合
- `feedback`：防止重蹈覆轍（負向）+ 強化已確認有效的方式（正向）
- `project`：提供背景和優先序以避免建議與現實脫節
- `reference`：避免讓模型浪費 turn 在「不知道去哪找」上

**關鍵設計**：`feedback` 同時記錄失敗（「不要」）和成功（「繼續這樣做」）。若只記錄糾正，模型會避免已知的錯誤但逐漸偏離已確認有效的方式。
