# Phase 6 — 07 工具權限 Hook 系統

## 架構概覽

```
bashToolHasPermission() / checkReadPermissionForTool() 等
        │ 返回 PermissionResult { behavior: 'ask' }
        ▼
createPermissionContext()
        │ 建立 PermissionContext 物件
        ▼
handlePermission()  ─────┬─── interactiveHandler.ts（主 agent）
                          ├─── coordinatorHandler.ts（協調器）
                          └─── swarmWorkerHandler.ts（swarm worker）
```

## PermissionContext 物件

`createPermissionContext()` 回傳一個富物件，包含所有需要的操作方法：

```typescript
type PermissionContext = {
  tool: ToolType
  input: Record<string, unknown>
  toolUseContext: ToolUseContext
  messageId: string
  toolUseID: string

  // 日誌方法
  logDecision(args, opts?): void
  logCancelled(): void

  // 權限操作
  persistPermissions(updates: PermissionUpdate[]): Promise<boolean>
  resolveIfAborted(resolve): boolean
  cancelAndAbort(feedback?, isAbort?, contentBlocks?): PermissionDecision
  buildAllow(updatedInput, opts?): PermissionAllowDecision
  buildDeny(message, decisionReason): PermissionDenyDecision

  // Classifier 整合（feature flag: BASH_CLASSIFIER）
  tryClassifier(pendingCheck, updatedInput): Promise<PermissionDecision | null>

  // Hook 執行
  runHooks(permissionMode, suggestions, updatedInput?, ...): Promise<PermissionDecision | null>

  // 使用者互動
  handleUserAllow(updatedInput, updates, feedback?, ...): Promise<PermissionAllowDecision>
  handleHookAllow(finalInput, updates, ...): Promise<PermissionAllowDecision>
  pushToQueue(item): void
  updateQueueItem(patch): void
}
```

## PermissionRequest Hook 系統

### executePermissionRequestHooks()

位於 `src/utils/hooks.ts`，在顯示許可對話框前先詢問 hook。

Hook 設定格式（settings.json）：
```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "type": "command",
        "command": "/path/to/my-hook",
        "matcher": "Bash",
        "timeout": 60
      }
    ]
  }
}
```

Hook 回傳值：
```typescript
// 允許
{ permissionRequestResult: { behavior: 'allow', updatedInput?: ... } }

// 拒絕
{ permissionRequestResult: { behavior: 'deny', message?: string, interrupt?: boolean } }
```

`interrupt: true` → abort 整個 session（不只是這個工具呼叫）

### Hook 執行流程

```typescript
async runHooks(permissionMode, suggestions, updatedInput?, ...): Promise<PermissionDecision | null> {
  for await (const hookResult of executePermissionRequestHooks(...)) {
    if (hookResult.permissionRequestResult?.behavior === 'allow') {
      return await this.handleHookAllow(...)
    }
    if (hookResult.permissionRequestResult?.behavior === 'deny') {
      this.logDecision({ decision: 'reject', source: { type: 'hook' } })
      if (decision.interrupt) {
        toolUseContext.abortController.abort()
      }
      return this.buildDeny(message, { type: 'hook', hookName: 'PermissionRequest', reason: message })
    }
  }
  return null  // Hook 未決定，繼續正常流程
}
```

## 互動式許可對話框（interactiveHandler.ts）

### 並發安全設計：ResolveOnce

```typescript
function createResolveOnce<T>(resolve: (value: T) => void): ResolveOnce<T> {
  let claimed = false
  let delivered = false
  return {
    resolve(value: T) { if (delivered) return; delivered = true; claimed = true; resolve(value) },
    isResolved() { return claimed },
    claim(): boolean { if (claimed) return false; claimed = true; return true },
  }
}
```

`claim()` 是原子性的 check-and-mark，防止多個非同步源（hook/classifier/user）競爭解析同一個 Promise。

### 五個並發決策源

```
1. Hook 結果（背景執行）
2. Classifier 結果（背景執行，先 check-and-mark 再 await）
3. 使用者點擊 Allow
4. 使用者點擊 Reject（或 Esc 取消）
5. AbortController 訊號
```

### awaitAutomatedChecksBeforeDialog

某些情況下（如可能是 false positive 的 safety check），在顯示對話框前先等待自動化檢查完成，避免使用者看到對話框後 classifier 才回來說可以允許。

### Channel Permission（手機/遠端批准）

```typescript
// 透過 MCP channel 讓使用者在手機上批准
if (channelCallbacks) {
  // 發送到 channel，等待 "yes {requestId}" 回覆
  // 本地決定後 unsubscribe（stale replies 會被過濾掉）
}
```

---

## 三種 Handler

### interactiveHandler.ts（主 agent 互動模式）

- 推送到 React 許可佇列（Ink UI）
- 並行執行：hook + classifier + user interaction
- 支援 Bridge callbacks（VS Code extension）
- 支援 Channel callbacks（手機批准）

### coordinatorHandler.ts（swarm 協調器）

- 轉發許可請求給人類操作員（透過 MCP 通知）
- 等待人類回覆
- Timeout 後升級為 deny

### swarmWorkerHandler.ts（swarm worker）

- 嘗試 classifier auto-approve（`awaitClassifierAutoApproval`）
- 若 classifier 不允許 → 轉發給協調器
- 協調器決定後回傳

---

## 許可決策日誌（permissionLogging.ts）

### logPermissionDecision()

統一的決策日誌函數，同時觸發：
1. **Statsig 分析事件**：`tengu_tool_use_permission_request_decision`
2. **OTel 遙測**：code edit 工具的 counter
3. **Code edit metrics**：`getCodeEditToolDecisionCounter()`

**決策來源標籤：**
```
hook           → 由 hook 決定
user_permanent → 使用者點擊且選擇永久儲存
user_temporary → 使用者點擊但只允許一次
classifier     → AI classifier 自動決定
config         → 來自設定檔的靜態規則
user_abort     → 使用者按 Esc 取消
user_reject    → 使用者明確拒絕
```

**Code editing 工具語言偵測：**
當工具是 `Edit`, `Write`, `NotebookEdit` 時，從 file path 推斷程式語言，記錄到 OTel 以分析各語言的批准率。

---

## 許可更新持久化

### applyPermissionUpdates() / persistPermissionUpdates()

```typescript
// 永久儲存（寫入 settings.json）
if (updates.some(update => supportsPersistence(update.destination))) {
  persistPermissionUpdates(updates)
}

// Session 內生效（更新記憶體中的 toolPermissionContext）
setToolPermissionContext(applyPermissionUpdates(appState.toolPermissionContext, updates))
```

儲存目標（destination）：
- `session`：只在當前 session 有效
- `project`（localSettings）：寫入 `.claude/settings.local.json`
- `user`（userSettings）：寫入 `~/.claude/settings.json`

---

## Classifier 審批整合

### setClassifierApproval() / setYoloClassifierApproval()

```typescript
// TRANSCRIPT_CLASSIFIER 功能：記錄 classifier 的批准決定
// 後續 yolo（acceptEdits）模式可直接使用 classifier 結果，不再提示
setClassifierApproval(toolUseID, matchedRule)
```

### classifierCheckInProgress UI 指示器

當 classifier 正在背景執行時，UI 顯示「checking...」指示器：

```typescript
ctx.updateQueueItem({ classifierCheckInProgress: true })   // 開始
clearClassifierIndicator()                                  // 完成後清除
```

---

## 安全設計要點

1. **Hook 失敗不自動允許**：hook 拋出例外 → 繼續標準流程（不 deny 也不 allow）
2. **Classifier 失敗不 deny**：classifier 呼叫失敗 → 讓使用者決定（安全默認）
3. **多源競爭保護**：ResolveOnce 確保只有第一個決策源生效
4. **Interrupt propagation**：hook 返回 `interrupt: true` → abort controller 觸發，整個 session 停止
5. **Stale channel reply**：手機批准回覆晚於本地決定時，tryConsumeReply 找不到 entry → 當作普通聊天訊息處理
