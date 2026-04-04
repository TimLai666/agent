# Team Memory 同步機制

## 一、系統定位

Team Memory 讓同一 GitHub repo 的所有 Claude Code 用戶共享記憶。個人記憶（private）和團隊記憶（team）並存，各有 `MEMORY.md` 索引。

```
記憶目錄結構（啟用 Team Memory 時）：
~/.claude/projects/{sanitized-git-root}/memory/
├── MEMORY.md                  ← 個人記憶索引
├── user_profile.md
├── feedback_style.md
├── project_context.md
└── team/
    ├── MEMORY.md              ← 團隊共享記憶索引
    ├── patterns.md
    └── incidents.md
```

## 二、啟用條件

```typescript
export function isTeamMemoryEnabled(): boolean {
  if (!isAutoMemoryEnabled()) return false    // 依賴 Auto Memory
  return getFeatureValue_CACHED_MAY_BE_STALE('tengu_herring_clock', false)
}
```

Team Memory 是 Auto Memory 的子系統，Auto Memory 關閉時 Team Memory 自動關閉。

## 三、路徑系統（teamMemPaths.ts）

```typescript
export function getTeamMemPath(): string {
  return (join(getAutoMemPath(), 'team') + sep).normalize('NFC')
}

export function getTeamMemEntrypoint(): string {
  return join(getAutoMemPath(), 'team', 'MEMORY.md')
}
```

Team Memory 目錄始終是 Auto Memory 目錄的 `team/` 子目錄。建立 team 目錄時，Auto Memory 目錄也因 recursive mkdir 而自動建立。

## 四、路徑安全驗證（PSR M22186）

Team Memory 的路徑驗證特別嚴格，因為需要防止符號連結攻擊：

### validateTeamMemWritePath()（雙層驗證）

```typescript
export async function validateTeamMemWritePath(filePath: string): Promise<string> {
  // 第一層：字串層級（快速拒絕顯而易見的穿越）
  const resolvedPath = resolve(filePath)
  if (!resolvedPath.startsWith(teamDir)) throw PathTraversalError

  // 第二層：符號連結解析（防止 symlink escape）
  const realPath = await realpathDeepestExisting(resolvedPath)
  if (!await isRealPathWithinTeamDir(realPath)) throw PathTraversalError
}
```

### realpathDeepestExisting()（遞迴找最深已存在的祖先）

```typescript
async function realpathDeepestExisting(absolutePath: string): Promise<string> {
  // 從目標路徑向上走，直到找到可以 realpath() 的祖先
  // 特殊處理：
  // - ENOENT：可能是懸掛符號連結 → 用 lstat 確認
  // - ELOOP：符號連結迴圈 → 直接報錯
  // - EACCES/EIO：無法驗證容納性 → fail closed
}
```

**設計原理（PSR M22186）**：`path.resolve()` 不解析符號連結。攻擊者若能在 teamDir 內放置指向 `~/.ssh/authorized_keys` 的符號連結，會通過 resolve() 的容納性檢查但實際寫到 ssh key。realpath() 解析後再比對才能發現逃逸。

### sanitizePathKey()（相對路徑鍵的安全檢查）

```typescript
function sanitizePathKey(key: string): string {
  // 1. null bytes（C 系統呼叫截斷）
  // 2. URL 編碼穿越（%2e%2e%2f = ../）
  // 3. Unicode 正規化攻擊（全形 ．．／ NFKC → ../）
  // 4. 反斜線（Windows 路徑分隔符作為穿越向量）
  // 5. 絕對路徑
}
```

## 五、同步協定（teamMemorySync/index.ts）

### API 端點

```
GET  /api/claude_code/team_memory?repo={owner/repo}             → 完整資料
GET  /api/claude_code/team_memory?repo={owner/repo}&view=hashes → 僅 checksums
PUT  /api/claude_code/team_memory?repo={owner/repo}             → 上傳（upsert）
404 = 尚無資料
```

### 同步語意

- **Pull**：伺服器內容覆蓋本地（server wins per-key）
- **Push**：只上傳本地 hash 與 `serverChecksums` 不同的文件（delta upload）
- **不傳播刪除**：本地刪除文件不會從伺服器移除，下次 pull 會還原

### SyncState（會話級可變狀態）

```typescript
export type SyncState = {
  lastKnownChecksum: string | null         // ETag（用於條件請求）
  serverChecksums: Map<string, string>      // 每個 key 的 sha256 hash
  serverMaxEntries: number | null           // 從 413 響應中學習的上限
}
```

所有可變狀態集中在 `SyncState`，由呼叫者建立並傳遞，讓函數保持純粹，測試易於隔離。

## 六、Push 機制（delta upload + 衝突處理）

```typescript
// 只上傳本地 hash 與 serverChecksums 不同的 keys
const delta = localEntries.filter(([key, content]) => {
  const localHash = hashContent(content)
  return localHash !== state.serverChecksums.get(key)
})
```

### 413 Too Many Entries（結構化錯誤處理）

```typescript
// 從 413 響應中解析 max_entries，緩存到 SyncState
// 後續 push 依此截斷，讓伺服器的 org 級限制生效
const serverMaxEntries = parsed.data.error.details.max_entries
state.serverMaxEntries = serverMaxEntries
```

### 412 衝突解決

```typescript
// 輕量探測（只取 checksums，不下載完整內容）
const hashResult = await fetchTeamMemoryHashes(state, repoSlug)
// 更新 serverChecksums，重新計算 delta，重試 push
```

### PUT Body 大小限制

```typescript
const MAX_PUT_BODY_BYTES = 200_000
const MAX_FILE_SIZE_BYTES = 250_000
// Gateway 在 ~256-512KB 處拒絕；200KB 留有餘量
// 超過限制的批次分割為多個順序 PUT（server upsert-merge 語意確保安全）
```

## 七、檔案監控（teamMemorySync/watcher.ts）

```typescript
// fs.watch（非 chokidar）
// 原因：chokidar 4+ 去掉 fsevents；Bun fs.watch 的 fallback 用 kqueue，
// 每個文件一個 fd → 500 個文件 = 500 個永久持有的 fd
// fs.watch + recursive:true：macOS 用 FSEvents（O(1) fd），Linux 用 inotify（O(subdirs)）
watcher = watch(teamDir, { persistent: true, recursive: true }, handleEvent)
```

### 防抖機制

```typescript
const DEBOUNCE_MS = 2000  // 最後一次變更後 2 秒才 push

function schedulePush(): void {
  if (pushSuppressedReason !== null) return  // 永久失敗時停止重試
  hasPendingChanges = true
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    if (pushInProgress) { schedulePush(); return }
    currentPushPromise = executePush()
  }, DEBOUNCE_MS)
}
```

### 永久失敗抑制（pushSuppressedReason）

```typescript
export function isPermanentFailure(r: TeamMemorySyncPushResult): boolean {
  // no_oauth / no_repo：請求前的客戶端檢查失敗，重試無意義
  // 4xx（除 409/429）：客戶端錯誤（404 無 repo, 413 條目過多, 403 無權限）
  // 409（Conflict）= 暫時衝突，下次 pull 後 push 可能成功
  // 429（Rate Limit）= 速率限制，防抖本身就是退避
}
```

一旦判定為永久失敗，`pushSuppressedReason` 設定後不再重試，直到：
- 文件刪除（`ENOENT` 偵測 → 清除抑制，重試 push）
- session 重啟

**設計動機**：觀察到無 OAuth 的設備在 2.5 天內發出 167K push 事件（無限重試迴圈）。

### 通知機制

```typescript
export async function notifyTeamMemoryWrite(): Promise<void> {
  if (!syncState) return
  schedulePush()  // 文件寫入後顯式觸發
}
```

PostToolUse hooks 呼叫此函數，確保 fs.watch 可能漏掉的寫入也會觸發 push（同一 tick 的首次寫入可能不觸發 watch event）。

## 八、Secret Scanner（teamMemSecretGuard.ts）

Push 前自動掃描，防止 API keys 等機密資料上傳到伺服器：

```typescript
// 使用 gitleaks 規則偵測常見機密格式
// SkippedSecretFile: { path, ruleId, label }
// 記錄到 telemetry 但不包含機密值本身
```

## 九、Combined Memory Prompt（teamMemPrompts.ts）

啟用 Team Memory 時，buildCombinedMemoryPrompt() 顯示雙目錄說明：

```
# Memory

You have a persistent, file-based memory system with two directories:
- private directory at `{autoDir}`
- shared team directory at `{teamDir}`

## Memory scope
- private: 個人記憶，只在你和當前用戶之間持久化
- team: 共享給專案內所有用戶，每次 session 開始時同步

## Types of memory
（四種類型，每種有 <scope> 標籤標示預設範圍）

## How to save memories
步驟1：寫到對應目錄的主題文件
步驟2：更新對應目錄的 MEMORY.md 索引
```

**新增安全限制**：Team Memory 禁止保存敏感資料（API keys, credentials）。

## 十、版本與類型系統（utils/memory/types.ts）

```typescript
export const MEMORY_TYPE_VALUES = [
  'User',     // 用戶上下文記憶
  'Project',  // 從 CLAUDE.md 等載入
  'Local',    // 本地設定
  'Managed',  // 管理的記憶
  'AutoMem',  // Auto Memory（memdir 系統）
  ...(feature('TEAMMEM') ? (['TeamMem'] as const) : []),
] as const
```

這是 UI 顯示層的類型，與 `memoryTypes.ts` 的四類（user/feedback/project/reference）是不同層次的分類。
