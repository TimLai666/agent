# 03 — UltraPlan 遠端規劃機制分析

## 概覽

UltraPlan 是一個「超級規劃模式」——當使用者輸入中包含關鍵字 `ultraplan` 時，Claude Code 會將任務轉發到遠端 CCR（Claude Code Remote）容器執行，在瀏覽器中展示計畫，待使用者批准後再返回本機執行。同類機制還有 `ultrareview`（超級審查模式）。

架構位置：`src/utils/ultraplan/`（2 個檔案）、`src/commands/ultraplan.tsx`

---

## 關鍵字觸發機制

來源：`src/utils/ultraplan/keyword.ts`

### `findUltraplanTriggerPositions(text)`

掃描使用者輸入，找出有效的 `ultraplan` 觸發位置。

### 排除規則（不觸發）

| 情況 | 原因 |
|------|------|
| 在反引號/雙引號/角括號/大括號/方括號/括號/單引號中 | 是程式碼或字串字面量 |
| 緊接 `/`、`\`、`-` 之前或之後 | 是路徑或識別符（`src/ultraplan/foo.ts`） |
| 後面跟 `.` + 單字字符 | 是檔案名稱（`ultraplan.tsx`） |
| 後面跟 `?` | 疑問句（詢問功能而非調用） |
| 輸入以 `/` 開頭 | 是 slash command（`/rename ultraplan foo`） |

### 輸入轉換

```typescript
// "please ultraplan this" → "please plan this"
replaceUltraplanKeyword(text)
```

關鍵字被替換為 `plan`（保留使用者的大小寫），轉發給遠端時語法保持正確。

---

## CCR Session 流程

來源：`src/utils/ultraplan/ccrSession.ts`

### 整體流程

```
1. 使用者輸入包含 "ultraplan"
2. 替換關鍵字為 "plan"
3. 建立 CCR 遠端 session（plan mode）
4. 瀏覽器開啟 claude.ai/code/{sessionId}
5. 遠端 Claude 執行規劃，進入 plan_ready 狀態
6. 使用者在瀏覽器審查計畫
7a. 批准 → 遠端執行，或
7b. "Teleport back" → 計畫文字傳回本機執行
```

### CCR Session 狀態機

```
running → (turn ends, no ExitPlanMode) → needs_input
needs_input → (user replies in browser) → running
running → (ExitPlanMode emitted, no result yet) → plan_ready
plan_ready → (rejected) → running
plan_ready → (approved) → poll resolves
```

### ExitPlanModeScanner（純狀態機）

`ExitPlanModeScanner` 是無 I/O 的純狀態分類器，消費 `SDKMessage[]` batch 並回傳 `ScanResult`：

```typescript
type ScanResult =
  | { kind: 'approved'; plan: string }
  | { kind: 'teleport'; plan: string }
  | { kind: 'rejected'; id: string }
  | { kind: 'pending' }
  | { kind: 'terminated'; subtype: string }
  | { kind: 'unchanged' }
```

**優先順序**：approved > terminated > rejected > pending > unchanged

一個 batch 可能同時包含「批准的 tool_result」和後續的「result(error)」——掃描器優先保留批准計畫。

---

## Teleport Sentinel

```typescript
export const ULTRAPLAN_TELEPORT_SENTINEL = '__ULTRAPLAN_TELEPORT_LOCAL__'
```

當使用者在瀏覽器點擊「teleport back to terminal」時，瀏覽器的 PlanModal 會在 ExitPlanMode 的 `deny` tool_result 中嵌入這個 sentinel，計畫文字跟在下一行。

這讓本機端能區分：
- 正常用戶拒絕（重新規劃）
- 「帶回本機執行」（teleport）

---

## Poll 機制

| 設定 | 值 | 說明 |
|------|-----|------|
| `POLL_INTERVAL_MS` | 3000 | 每 3 秒輪詢一次 |
| `MAX_CONSECUTIVE_FAILURES` | 5 | 連續失敗 5 次才放棄 |

### 超時錯誤類型

| 錯誤原因 | 說明 |
|---------|------|
| `terminated` | 遠端 session 異常終止 |
| `timeout_pending` | 計畫出現了但超時未批准 |
| `timeout_no_plan` | ExitPlanMode 從未到達（container 啟動失敗？） |
| `extract_marker_missing` | 批准的 tool_result 中缺少標記 |
| `network_or_unknown` | 網路錯誤 |
| `stopped` | 呼叫者主動停止 |

---

## 計畫文字萃取

### 批准（approved）
從 tool_result 內容中尋找標記：
```
## Approved Plan:\n<text>
## Approved Plan (edited by user):\n<text>
```

### Teleport
從 deny tool_result 中尋找 sentinel：
```
__ULTRAPLAN_TELEPORT_LOCAL__\n<plan text>
```

---

## 執行目標

`PollResult.executionTarget`：
- `'remote'`：使用者在瀏覽器批准，遠端 CCR 繼續執行
- `'local'`：使用者點擊 teleport，計畫傳回本機終端執行

---

## 類似機制：Ultrareview

`findUltrareviewTriggerPositions()` / `hasUltrareviewKeyword()` 採用完全相同的關鍵字偵測邏輯，觸發 `ultrareview` 超級審查模式（推測為：遠端執行 code review）。

---

## 設計亮點

1. **純狀態機**：`ExitPlanModeScanner` 無副作用，可用合成事件做離線重播和單元測試
2. **Needs_input 偵測**：不依賴 threadstore 的 `result(success)` 事件（不持久化），改用 session status API 的 `idle` 狀態
3. **競爭條件處理**：同一 batch 內「批准 + 後續崩潰」時，優先保留批准計畫
4. **網路容錯**：5 次連續失敗才放棄，支援短暫網路中斷
