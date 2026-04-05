# Memdir 核心系統完整分析

## 一、核心常數與結構

```typescript
// memdir.ts
export const ENTRYPOINT_NAME = 'MEMORY.md'
export const MAX_ENTRYPOINT_LINES = 200
export const MAX_ENTRYPOINT_BYTES = 25_000   // ~125 chars/line × 200 lines
```

MEMORY.md 是「索引文件」而非記憶本身，每個條目格式為：
```
- [Title](file.md) — one-line hook（限 ~150 chars）
```

## 二、記憶文件格式

每個記憶文件採用 YAML frontmatter：
```markdown
---
name: {{memory name}}
description: {{one-line description — used to decide relevance in future conversations, so be specific}}
type: {{user, feedback, project, reference}}
---

{{memory content — for feedback/project types, structure as: rule/fact, then **Why:** and **How to apply:** lines}}
```

`description` 欄位極為關鍵：它是 `findRelevantMemories` 篩選時的主要依據，必須足夠具體讓 LLM 判斷相關性。

## 三、MEMORY.md 截斷機制（truncateEntrypointContent）

```typescript
export function truncateEntrypointContent(raw: string): EntrypointTruncation {
  // 行截斷優先（自然邊界），再做位元組截斷（避免切斷中途行）
  let truncated = wasLineTruncated
    ? contentLines.slice(0, MAX_ENTRYPOINT_LINES).join('\n')
    : trimmed

  if (truncated.length > MAX_ENTRYPOINT_BYTES) {
    const cutAt = truncated.lastIndexOf('\n', MAX_ENTRYPOINT_BYTES)
    truncated = truncated.slice(0, cutAt > 0 ? cutAt : MAX_ENTRYPOINT_BYTES)
  }
  // 附加警告說明觸發原因
}
```

截斷時會同時偵測「行超限」與「位元組超限」，警告訊息精確說明哪個上限被觸發，例：
- `197KB (limit: 25KB) — index entries are too long`
- `287 lines (limit: 200)`

## 四、Memory Prompt 建構流程（buildMemoryLines / buildMemoryPrompt）

`buildMemoryLines()` 組裝的 prompt 結構：
1. `# auto memory`（或自訂 displayName）
2. 記憶目錄路徑 + `DIR_EXISTS_GUIDANCE`
3. 記憶系統目的說明
4. 四種記憶類型區塊（`TYPES_SECTION_INDIVIDUAL`）
5. `## What NOT to save in memory`
6. `## How to save memories`（兩步驟流程）
7. `## When to access memories`
8. `## Before recommending from memory`（新鮮度驗證）
9. 記憶 vs 其他持久化機制的使用時機
10. `## Searching past context`（若 feature flag 啟用）

`buildMemoryPrompt()` 在此基礎上追加 MEMORY.md 的實際內容。

**skipIndex 模式**（`tengu_moth_copse` flag）：省略 MEMORY.md 索引步驟，模型直接寫記憶文件，不維護 index。

## 五、路徑系統（paths.ts）

### isAutoMemoryEnabled() 判斷鏈

```
1. CLAUDE_CODE_DISABLE_AUTO_MEMORY env var → true = 關閉
2. CLAUDE_CODE_SIMPLE (--bare) → 關閉
3. CCR 模式無 CLAUDE_CODE_REMOTE_MEMORY_DIR → 關閉
4. settings.json autoMemoryEnabled 欄位
5. 預設：啟用
```

### getAutoMemPath() 解析鏈（已 memoize 以 projectRoot 為 key）

```
1. CLAUDE_COWORK_MEMORY_PATH_OVERRIDE env var
2. settings.json autoMemoryDirectory（policy > flag > local > user）
3. {memoryBase}/projects/{sanitizePath(gitRoot)}/memory/
```

**安全驗證**（validateMemoryPath）拒絕：
- 非絕對路徑
- 長度 < 3（`/` 根目錄）
- Windows drive root（`C:`）
- UNC paths（`\\server\share`）
- null bytes

### KAIROS 模式的 daily log 路徑

```typescript
export function getAutoMemDailyLogPath(date: Date = new Date()): string {
  return join(getAutoMemPath(), 'logs', yyyy, mm, `${yyyy}-${mm}-${dd}.md`)
}
```

KAIROS（長期存活 assistant session）改為 append-only 模式：每天追加到日誌，不維護 MEMORY.md；由夜間 /dream 技能蒸餾成主題文件。

## 六、記憶年齡系統（memoryAge.ts）

```typescript
// 簡單日數計算，負值夾零（應對時鐘偏移）
export function memoryAgeDays(mtimeMs: number): number {
  return Math.max(0, Math.floor((Date.now() - mtimeMs) / 86_400_000))
}

// 人類可讀：today / yesterday / N days ago
export function memoryAge(mtimeMs: number): string { ... }

// 過期警告文字（>1 天才顯示）
export function memoryFreshnessText(mtimeMs: number): string {
  // "This memory is N days old. Memories are point-in-time observations..."
}

// 包在 <system-reminder> 的過期警告
export function memoryFreshnessNote(mtimeMs: number): string { ... }
```

設計原因：模型不擅長日期計算，「47 days ago」比原始 ISO 時間戳更能觸發過期推理。

## 七、記憶掃描系統（memoryScan.ts）

```typescript
export async function scanMemoryFiles(
  memoryDir: string,
  signal: AbortSignal,
): Promise<MemoryHeader[]> {
  // 遞迴讀取所有 .md，排除 MEMORY.md
  // 只讀前 30 行（FRONTMATTER_MAX_LINES）取 frontmatter
  // 依 mtime 降序排序（最新優先），限 200 個
}

export function formatMemoryManifest(memories: MemoryHeader[]): string {
  // 每行格式：- [type] filename (ISO timestamp): description
}
```

**設計亮點**：單一掃描讀取 frontmatter 同時取 mtime，避免先 stat 再讀的雙倍 syscall。

## 八、相關記憶搜尋（findRelevantMemories.ts）

```typescript
export async function findRelevantMemories(
  query: string,
  memoryDir: string,
  signal: AbortSignal,
  recentTools: readonly string[] = [],
  alreadySurfaced: ReadonlySet<string> = new Set(),
): Promise<RelevantMemory[]>
```

工作流程：
1. `scanMemoryFiles()` 掃描所有記憶的 frontmatter
2. 過濾已顯示的（`alreadySurfaced`，避免重複推薦）
3. 呼叫 Sonnet sideQuery（`querySource: 'memdir_relevance'`），請 LLM 從 manifest 選出最相關的（最多 5 個）
4. 回傳 `{ path, mtimeMs }` 清單

**去雜訊設計**：`recentTools` 參數——若模型已在使用某工具，不推薦該工具的參考文件（避免噪音）；但仍推薦有關該工具已知問題的記憶（活躍使用時正是需要知道 gotchas 的時候）。

## 九、loadMemoryPrompt() 分發邏輯

```typescript
export async function loadMemoryPrompt(): Promise<string | null> {
  // 1. KAIROS 模式 → buildAssistantDailyLogPrompt()
  // 2. TEAMMEM + 啟用 → buildCombinedMemoryPrompt()（team + auto 雙目錄）
  // 3. auto 啟用 → buildMemoryLines()（單目錄）
  // 4. 全部關閉 → null（記錄 telemetry）
}
```

## 十、DIR_EXISTS_GUIDANCE

```typescript
export const DIR_EXISTS_GUIDANCE =
  'This directory already exists — write to it directly with the Write tool (do not run mkdir or check for its existence).'
```

解決「模型浪費 turn 做 ls/mkdir」的問題：harness 在 `ensureMemoryDirExists()` 中確保目錄存在，prompt 中告知模型可直接寫。

## 十一、ensureMemoryDirExists()

```typescript
export async function ensureMemoryDirExists(memoryDir: string): Promise<void> {
  const fs = getFsImplementation()
  try {
    await fs.mkdir(memoryDir)
  } catch (e) {
    // EEXIST 已由 fs.mkdir 處理；真正的錯誤（EACCES 等）記 debug log
    // prompt building 繼續進行，Write tool 會顯示真正的 perm 錯誤
  }
}
```

## 十二、Memory vs 其他持久化（設計邊界）

Prompt 中明確說明何時用記憶，何時用其他機制：
- **Plan**：非瑣碎的實作任務前，與用戶對齊方法論 → 用 Plan，不用 memory
- **Tasks**：分解當前對話的步驟、追蹤進度 → 用 Tasks，不用 memory
- **Memory**：對未來對話有用的資訊

## 十三、TRUSTING_RECALL_SECTION（實驗驗證過）

```typescript
export const TRUSTING_RECALL_SECTION: readonly string[] = [
  '## Before recommending from memory',
  // H1 (eval 2026-03-17): 0/2 → 3/3，透過 appendSystemPrompt 實現
  // 標題「Before recommending」（行動提示點）比「Trusting what you recall」（抽象）好 3/3 vs 0/3
  '- If the memory names a file path: check the file exists.',
  '- If the memory names a function or flag: grep for it.',
  '"The memory says X exists" is not the same as "X exists now."',
]
```

關鍵設計：標題措辭經 eval 驗證——「行動提示點」定位（在模型即將推薦之前）比「抽象標題」更能激活正確行為。
