# AutoDream 夢境整合機制

## 一、系統定位

AutoDream 是一個**跨 session 的記憶鞏固系統**，類比「睡眠中的記憶整合」。當累積足夠多的 session 且距離上次整合時間夠長，系統自動啟動一個背景 forked agent，回顧日誌與記憶文件，進行精煉與組織。

**觸發時機**：每次 query loop 結束後（與 `executeExtractMemories` 相同的 stopHooks 位置），但透過時間門檻和 session 計數門檻限制執行頻率。

## 二、三層門檻設計（Gate Order：最便宜優先）

```typescript
// 1. 時間門檻：距離上次整合多少小時？（一次 stat 操作）
let lastAt = await readLastConsolidatedAt()
const hoursSince = (Date.now() - lastAt) / 3_600_000
if (hoursSince < cfg.minHours) return  // 預設 24 小時

// 2. Session 門檻：上次整合後有幾個新 session？
const sessionIds = await listSessionsTouchedSince(lastAt)
const filtered = sessionIds.filter(id => id !== currentSession)  // 排除當前
if (filtered.length < cfg.minSessions) return  // 預設 5 個 session

// 3. 鎖定門檻：沒有其他 process 正在整合
const priorMtime = await tryAcquireConsolidationLock()
if (priorMtime === null) return  // 已被鎖定
```

**掃描節流**（`SESSION_SCAN_INTERVAL_MS = 10 分鐘`）：時間門檻通過後，session 掃描也有自己的節流，避免每個 turn 都做 listdir 操作。

## 三、可設定門檻（GrowthBook）

```typescript
const DEFAULTS: AutoDreamConfig = {
  minHours: 24,     // 24 小時
  minSessions: 5,   // 5 個 sessions
}

// 從 tengu_onyx_plover flag 讀取，帶防禦性驗證
function getConfig(): AutoDreamConfig {
  const raw = getFeatureValue_CACHED_MAY_BE_STALE<Partial<AutoDreamConfig> | null>('tengu_onyx_plover', null)
  return {
    minHours: typeof raw?.minHours === 'number' && Number.isFinite(raw.minHours) && raw.minHours > 0
      ? raw.minHours : DEFAULTS.minHours,
    // ...
  }
}
```

**啟用控制**（`config.ts`）：
```typescript
export function isAutoDreamEnabled(): boolean {
  const setting = getInitialSettings().autoDreamEnabled
  if (setting !== undefined) return setting  // settings.json 覆蓋
  const gb = getFeatureValue_CACHED_MAY_BE_STALE<{ enabled?: unknown } | null>('tengu_onyx_plover', null)
  return gb?.enabled === true
}
```

## 四、KAIROS 模式排除

```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false  // KAIROS 模式用 disk-skill dream（不同機制）
  if (getIsRemoteMode()) return false
  if (!isAutoMemoryEnabled()) return false
  return isAutoDreamEnabled()
}
```

KAIROS（長期 assistant session）有自己的夜間 /dream skill，不使用 AutoDream。

## 五、鎖機制（consolidationLock）

```typescript
let priorMtime: number | null
priorMtime = await tryAcquireConsolidationLock()
// 返回 null = 已被鎖定（其他 session 正在整合）
// 返回 priorMtime = 鎖定成功，回傳鎖文件的前一個 mtime（用於回滾）
```

**失敗回滾**：
```typescript
await rollbackConsolidationLock(priorMtime)
// 將鎖文件 mtime 恢復為 priorMtime
// 讓下次時間門檻繼續有效（防止永久跳過整合）
```

## 六、整合 Prompt（buildConsolidationPrompt）

```typescript
export function buildConsolidationPrompt(
  memoryRoot: string,
  transcriptDir: string,
  extra: string,
): string {
  return `# Dream: Memory Consolidation

Memory directory: ${memoryRoot}
${DIR_EXISTS_GUIDANCE}

Session transcripts: ${transcriptDir} (large JSONL files — grep narrowly, don't read whole files)
---

## Phase 1 — Orient
- ls 記憶目錄
- 讀取 MEMORY.md
- 瀏覽現有主題文件（避免重複）
- 如有 logs/ 或 sessions/，查看近期條目

## Phase 2 — Gather recent signal
1. 日誌文件（logs/YYYY/MM/YYYY-MM-DD.md）— append-only 流
2. 可能漂移的現有記憶（與當前程式碼狀態矛盾的事實）
3. Transcript 搜尋（最後手段）：grep -rn "<narrow term>" ${transcriptDir}/ --include="*.jsonl" | tail -50

## Phase 3 — Consolidate
- 合併新信號到現有主題文件（避免近似重複）
- 轉換相對日期為絕對日期
- 刪除被推翻的事實

## Phase 4 — Prune and index
- 更新 MEMORY.md（維持 <200 行 <25KB）
- 移除過時指標
- 壓縮過長的索引條目（把細節移到主題文件）

Return a brief summary of what you consolidated, updated, or pruned.`
}
```

**工具約束**（寫在 extra 參數中，自動夢境才有）：
```
**Tool constraints for this run:** Bash is restricted to read-only commands...
Sessions since last consolidation (N):
- <session-id-1>
- <session-id-2>
...
```

## 七、任務進度追蹤（DreamTask）

AutoDream 是少數有 UI 進度顯示的背景子系統：

```typescript
const taskId = registerDreamTask(setAppState, {
  sessionsReviewing: sessionIds.length,
  priorMtime,
  abortController,
})
```

```typescript
function makeDreamProgressWatcher(taskId, setAppState): (msg: Message) => void {
  return msg => {
    // 每條 assistant 訊息：
    // - text blocks → 顯示給用戶看的推理/摘要
    // - tool_use blocks → 計數顯示（N 個工具操作）
    // - Edit/Write 的 file_path → 追蹤觸碰的文件（用於完成摘要）
    addDreamTurn(taskId, { text, toolUseCount }, touchedPaths, setAppState)
  }
}
```

用戶可從任務對話框中止 AutoDream：
```typescript
const abortController = new AbortController()
// 若用戶中止，DreamTask.kill 已回滾鎖；不重複回滾
if (abortController.signal.aborted) {
  logForDebugging('[autoDream] aborted by user')
  return
}
```

## 八、完成後的記憶通知

```typescript
completeDreamTask(taskId, setAppState)
const dreamState = context.toolUseContext.getAppState().tasks?.[taskId]
if (appendSystemMessage && isDreamTask(dreamState) && dreamState.filesTouched.length > 0) {
  appendSystemMessage({
    ...createMemorySavedMessage(dreamState.filesTouched),
    verb: 'Improved',  // 區別於 ExtractMemories 的 'Saved'
  })
}
```

「Improved N memories」（而非「Saved N memories」）—— 這是鞏固/精煉，不是新建。

## 九、閉包初始化模式

```typescript
let runner: ((context, appendSystemMessage) => Promise<void>) | null = null

export function initAutoDream(): void {
  let lastSessionScanAt = 0  // 閉包狀態

  runner = async function runAutoDream(context, appendSystemMessage) {
    // ... 三層門檻 + 鎖 + 執行
  }
}

export async function executeAutoDream(context, appendSystemMessage): Promise<void> {
  await runner?.(context, appendSystemMessage)
}
```

與 `initExtractMemories()` 相同的閉包模式：`initAutoDream()` 在啟動時和每個測試的 `beforeEach` 中呼叫。

## 十、與 /dream 指令的關係

AutoDream 和手動的 `/dream` skill 使用相同的 `buildConsolidationPrompt()`，但：
- `/dream`：在主 loop 中執行（正常工具權限）
- AutoDream：forked agent（受限工具 `createAutoMemCanUseTool`）
- AutoDream 的 extra 包含工具限制說明（避免 /dream 看到誤導性提示）

## 十一、與 KAIROS daily log 的關係

KAIROS 模式下的記憶架構：
```
新記憶 → 追加到 logs/YYYY/MM/YYYY-MM-DD.md（append-only）
                ↓
    [夜間 /dream skill（非 AutoDream）]
                ↓
    精煉到主題文件 + 更新 MEMORY.md
```

AutoDream 的 Phase 1 也處理 `logs/` 子目錄，因此可以在非 KAIROS 模式下整合 KAIROS 遺留的日誌（或反向相容）。
