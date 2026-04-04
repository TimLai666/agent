# 09 — Moreright、Teleport、DeepLink 功能分析

---

## 1. Moreright（`useMoreRight`）

來源：`src/moreright/useMoreRight.tsx`

### 現狀

目前存在的是**外部 build 的 stub 實作**，真正的 hook 是「internal only」（只存在於 Anthropic 內部 monorepo）。

```typescript
// Stub for external builds — the real hook is internal only.
export function useMoreRight(_args: {
  enabled: boolean;
  setMessages: ...;
  inputValue: string;
  setInputValue: ...;
  setToolJSX: ...;
}): {
  onBeforeQuery: async () => true,    // stub：永遠允許
  onTurnComplete: async () => {},     // stub：無操作
  render: () => null                  // stub：不渲染
}
```

### Hook 介面分析

從 stub 的 type signature 可以推斷真實功能：

| 參數/返回值 | 推斷功能 |
|-----------|---------|
| `enabled: boolean` | 可被動態開關 |
| `setMessages` | 能直接修改對話訊息列表 |
| `inputValue` / `setInputValue` | 能讀取和修改使用者輸入框 |
| `setToolJSX` | 能注入工具 UI 元件 |
| `onBeforeQuery(input, all, n)` | 返回 `boolean`：決定是否允許查詢繼續 |
| `onTurnComplete(all, aborted)` | turn 完成後的回調 |
| `render()` | 渲染額外 UI 元件 |

**推斷**：Moreright 是一個「更多右側功能」的擴展 hook，可能在 UI 右側提供額外面板或功能（可能是 Ant 內部的特殊 UI 層）。`onBeforeQuery` 能攔截並拒絕查詢，說明它有過濾/審查能力。

---

## 2. Teleport（CCR 遠端傳送）

來源：`src/utils/teleport/`（6 個檔案）

### 整體架構

Teleport 是「從本機傳送到 Claude.ai 遠端 session（CCR）」的底層機制，也是 UltraPlan 的基礎設施。

### CCR 環境類型

來源：`src/utils/teleport/environments.ts`

```typescript
type EnvironmentKind = 'anthropic_cloud' | 'byoc' | 'bridge'
```

| 環境類型 | 說明 |
|---------|------|
| `anthropic_cloud` | Anthropic 雲端 CCR 容器 |
| `byoc` | Bring Your Own Cloud（用戶自有雲）CCR Beta（`ccr-byoc-2025-07-29`） |
| `bridge` | Bridge 模式（透過 bridge 連接） |

Environment API：`/v1/environment_providers`（需要 OAuth + 組織 UUID）

### Git Bundle Seeding

來源：`src/utils/teleport/gitBundle.ts`

當建立遠端 CCR session 時，可以將本機 Git repo 打包上傳，讓遠端 container 有完整的程式碼上下文。

Bundle 策略（三層 fallback）：
1. `--all`：完整 bundle（含所有 refs、branches、tags）
2. `HEAD`：只有當前分支完整歷史（捨棄側分支）
3. `squashed-root`：單一 parentless commit（僅快照，無歷史），用於超大 repo

預設 bundle 大小上限：100 MB（可透過 `tengu_ccr_bundle_max_bytes` 調整）

WIP 處理：
- `git stash create` 建立臨時 stash
- 將 stash 打包進 bundle（`refs/seed/stash`）
- 上傳後清除 ref（不污染使用者 repo）

### 重試機制

來源：`src/utils/teleport/api.ts`

```typescript
const TELEPORT_RETRY_DELAYS = [2000, 4000, 8000, 16000]  // 指數退避，4 次重試
```

5xx 錯誤自動重試，4xx 錯誤立即失敗。

### Session URL 解析

來源：`src/constants/product.ts`

```typescript
// URL 格式：https://claude.ai/code/{sessionId}
function getRemoteSessionUrl(sessionId: string, ingressUrl?: string): string
```

支援三種環境：
- Production：`https://claude.ai`
- Staging：`https://claude-ai.staging.ant.dev`
- Local：`http://localhost:4000`

環境偵測：Session ID 包含 `_staging_` / `_local_` 子字串，或 ingress URL 包含對應關鍵字。

### 環境選擇 UI

`src/utils/teleport/environmentSelection.ts` — 提供環境選擇界面，讓使用者在 `anthropic_cloud`、`byoc` 之間選擇。

---

## 3. DeepLink（深度連結）

來源：`src/utils/deepLink/`（5 個檔案）

### 協議格式

```
claude-cli://open?q={prompt}&cwd={path}&repo={owner/repo}
```

### 解析邏輯（`parseDeepLink`）

**安全驗證**：
1. 協議必須是 `claude-cli://`
2. hostname 必須是 `open`
3. `cwd` 必須是絕對路徑
4. `cwd` 不得包含控制字符（ASCII 0x00-0x1F, 0x7F）
5. `repo` 必須符合 `owner/repo` 格式（防止路徑遍歷）
6. `q` 不得包含控制字符（防止命令注入）
7. `q` 最大長度：5000 字符
8. `cwd` 最大長度：4096 字符

**Unicode 清理**：使用 `partiallySanitizeUnicode()` 移除隱藏 Unicode 字符（防止 ASCII smuggling / 隱藏 prompt injection）

### 執行流程（`handleDeepLinkUri`）

```
OS 呼叫 claude --handle-uri <url>
→ parseDeepLink(url)
→ resolveCwd(action)
  → 優先序：explicit cwd > repo 本機路徑 > 家目錄
→ readLastFetchTime(cwd)  (git FETCH_HEAD 年齡，預算計算用)
→ launchInTerminal(process.execPath, { query, cwd, repo, lastFetchMs })
```

### macOS URL Scheme 啟動

```typescript
// 偵測方式：__CFBundleIdentifier === MACOS_BUNDLE_ID
async function handleUrlSchemeLaunch(): Promise<number | null>
```

LaunchServices 啟動時 `__CFBundleIdentifier` 會被設為我們的 bundle ID。透過 `url-handler-napi` 的 `waitForUrlEvent(5000)` 取得 URL。

### 終端啟動器（`terminalLauncher.ts`）

支援的終端（按優先順序）：

**macOS**：
1. iTerm2（`com.googlecode.iterm2`）
2. Ghostty（`com.mitchellh.ghostty`）
3. Kitty（`net.kovidgoyal.kitty`）
4. Alacritty（`org.alacritty`）
5. WezTerm（`com.github.wez.wezterm`）
6. Terminal.app（`com.apple.Terminal`，回退）

**Linux**：
ghostty → kitty → alacritty → wezterm → gnome-terminal → konsole → xfce4-terminal → mate-terminal → tilix → xterm

**Windows**：
Windows Terminal（wt.exe） → PowerShell → cmd.exe

偵測邏輯：
1. 讀取 `config.deepLinkTerminal`（使用者存儲的偏好，在無 TTY 的 LaunchServices context 中是唯一可用信號）
2. 檢查 `TERM_PROGRAM` 環境變數
3. 掃描運行中的進程
4. 掃描已安裝的 App bundle

### Protocol 註冊（`registerProtocol.ts`）

**macOS**：
- Bundle ID：`MACOS_BUNDLE_ID`
- 使用 `.app` bundle + `Info.plist` 的 `CFBundleURLTypes`
- 透過 LaunchServices 系統級 URL scheme 處理

**Linux**：
- `.desktop` 文件 + `xdg-mime` / `update-desktop-database`

**Windows**：
- 登錄表 `HKCU\Software\Classes\claude-cli\...`

---

## 設計亮點

1. **Moreright 的 onBeforeQuery 返回 boolean** → 這是一個攔截閘門，ant 內部版本可能有輸入審查或特殊路由邏輯
2. **DeepLink 的 `q` 長度限制與 Windows cmd.exe 相關**：5000 字符是根據 cmd.exe 的 8191 字符命令行上限計算得出的實用安全上限
3. **Git Bundle 三層 fallback**：確保即使超大 repo 也能以「快照」模式上傳，讓遠端 session 有基本上下文
4. **BYOC beta**：`ccr-byoc-2025-07-29` 表明「Bring Your Own Cloud」是一個正在開發中的付費功能
