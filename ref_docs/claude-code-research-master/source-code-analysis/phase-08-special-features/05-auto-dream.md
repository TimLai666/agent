# 05 — AutoDream 夢境整合機制分析

## 概覽

AutoDream（代號：`tengu_onyx_plover`）是 Claude Code 的**後台記憶整合系統**。當累積足夠多的 session 後，它會自動在背景啟動一個 forked agent 執行「夢境」（Dream）——審查近期 session transcript、更新記憶檔案，讓下一次 session 能更快速定位。

架構位置：`src/services/autoDream/`（4 個檔案）

---

## 啟動時機

AutoDream 在啟動時由 `backgroundHousekeeping` 初始化（`initAutoDream()`），每個 REPL turn 結束後由 `stopHooks.ts` 觸發 `executeAutoDream()`。

---

## 三層閘門（最便宜的先檢查）

### 1. 靜態閘門（Gate）

```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false    // KAIROS 模式有自己的 dream 機制
  if (getIsRemoteMode()) return false    // 遠端模式不執行
  if (!isAutoMemoryEnabled()) return false  // 自動記憶功能需開啟
  return isAutoDreamEnabled()
}
```

### 2. 時間閘門（Time Gate）

```typescript
const hoursSince = (Date.now() - lastAt) / 3_600_000
if (hoursSince < cfg.minHours) return
```

預設：`minHours = 24`（至少 24 小時未整合）

### 3. Session 閘門（Session Gate）

```typescript
if (sessionIds.length < cfg.minSessions) return
```

預設：`minSessions = 5`（至少 5 個 session 自上次整合後）

掃描節流：`SESSION_SCAN_INTERVAL_MS = 10 分鐘`（時間閘門通過但 session 不足時，防止每個 turn 都掃描）

---

## 配置來源

Feature value：`tengu_onyx_plover`（GrowthBook）

```typescript
type AutoDreamConfig = {
  enabled: boolean   // 在 config.ts 中讀取
  minHours: number   // 預設 24
  minSessions: number  // 預設 5
}
```

使用者可在 `settings.json` 明確設定 `autoDreamEnabled` 覆蓋 GrowthBook 預設。

---

## 執行流程

```
1. 計算距上次整合的時間（readLastConsolidatedAt）
2. 列出自上次整合後修改的 session（listSessionsTouchedSince）
3. 排除當前 session（mtime 永遠是最新的）
4. 嘗試取得整合鎖（tryAcquireConsolidationLock）
5. 啟動 forked agent（runForkedAgent）
6. 監控進度（makeDreamProgressWatcher）
7. 完成後記錄摘要到主對話（appendSystemMessage）
```

---

## Forked Agent 配置

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: prompt })],
  cacheSafeParams: createCacheSafeParams(context),
  canUseTool: createAutoMemCanUseTool(memoryRoot),  // 限制工具權限
  querySource: 'auto_dream',
  forkLabel: 'auto_dream',
  skipTranscript: true,    // 不寫入對話記錄
  overrides: { abortController },
  onMessage: makeDreamProgressWatcher(taskId, setAppState),
})
```

### 工具限制（Tool Constraints）

AutoDream forked agent 的 Bash 被限制為**唯讀指令**：
`ls`, `find`, `grep`, `cat`, `stat`, `wc`, `head`, `tail` 等

不允許任何寫入、重定向或修改狀態的操作。

---

## Dream Prompt（整合提示詞）

來源：`src/services/autoDream/consolidationPrompt.ts`

四個階段：

### Phase 1 — Orient（定向）
- `ls` 記憶目錄
- 讀取 entrypoint（索引檔）
- 瀏覽現有主題檔案

### Phase 2 — Gather recent signal（收集近期信號）
優先順序：
1. 每日日誌（`logs/YYYY/MM/YYYY-MM-DD.md`）
2. 已漂移的記憶（與現有程式碼矛盾的事實）
3. Transcript 搜尋（僅針對性 grep，不全讀）

### Phase 3 — Consolidate（整合）
- 合併新信號到現有主題檔案（而非創建重複檔案）
- 將相對日期轉換為絕對日期
- 刪除已矛盾的事實

### Phase 4 — Prune and index（修剪和索引）
- 更新 entrypoint，維持在 `MAX_ENTRYPOINT_LINES` 行以內（~25KB）
- 每個索引條目一行、不超過 ~150 字符
- 刪除過時、錯誤或已被取代的記憶指標

---

## 進度監控

`makeDreamProgressWatcher` 監聽 forked agent 的每條訊息：
- 收集 text 區塊（agent 的推理摘要）
- 計算 tool_use 次數
- 追蹤被修改的檔案路徑（FileEdit / FileWrite 工具）

---

## 鎖機制（Consolidation Lock）

- 使用檔案鎖防止多個進程同時整合
- 整合完成後：更新 lock 的 mtime（作為「上次整合時間」的記錄）
- 整合失敗後：`rollbackConsolidationLock(priorMtime)` 回滾到之前的時間，讓下次時間閘門再次通過
- 使用者中止（abort）後：不回滾（DreamTask.kill 已處理）

---

## Analytics 事件

| 事件 | 觸發時機 |
|------|---------|
| `tengu_auto_dream_fired` | 開始執行，記錄距上次的小時數和 session 數 |
| `tengu_auto_dream_completed` | 完成，記錄 cache 用量和輸出 token 數 |
| `tengu_auto_dream_failed` | 失敗 |

---

## 設計亮點

1. **KAIROS 分離**：KAIROS 模式有自己的 disk-skill dream，互不干擾
2. **非侵入性**：`skipTranscript: true` 確保夢境過程不出現在對話記錄中
3. **Session 掃描節流**：防止時間閘門通過但 session 不足時每個 turn 都掃描
4. **「夢境」比喻**：像人類在睡眠中整理記憶，在背景靜默整合，不干擾主對話
5. **防 force 濫用**：`isForced()` 始終返回 `false`（ant-only test override），確保生產環境無法強制觸發
