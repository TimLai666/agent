# Phase 6 — 05 檔案系統權限模型

## 核心檔案：src/utils/permissions/filesystem.ts

### 危險檔案與目錄黑名單

```typescript
export const DANGEROUS_FILES = [
  '.gitconfig', '.gitmodules',
  '.bashrc', '.bash_profile',
  '.zshrc', '.zprofile', '.profile',
  '.ripgreprc',
  '.mcp.json', '.claude.json',
] as const

export const DANGEROUS_DIRECTORIES = [
  '.git',
  '.vscode',
  '.idea',
  '.claude',
] as const
```

**特例**：`.claude/worktrees/` 是結構性路徑（Claude 存放 git worktrees），跳過 `.claude` 保護。

---

## 路徑安全函數

### normalizeCaseForComparison(path)

```typescript
export function normalizeCaseForComparison(path: string): string {
  return path.toLowerCase()
}
```

**作用**：防止 macOS/Windows 大小寫不敏感檔案系統的繞過攻擊：
- `.cLauDe/Settings.locaL.json` → 統一小寫後被識別為危險路徑

### hasSuspiciousWindowsPathPattern(path)

偵測 Windows 特有的路徑繞過模式（所有平台都檢查，因 NTFS 可掛載在 Linux/macOS）：

| 模式 | 攻擊向量 |
|------|---------|
| NTFS Alternate Data Streams（`:` after pos 2） | `file.txt:stream` 繞過路徑匹配 |
| 8.3 短名稱（`~\d`） | `GIT~1`, `CLAUDE~1` 繞過 `.git` 保護 |
| Long path prefix（`\\?\`, `\\.\`, `//?/`, `//./`） | 繞過 MAX_PATH 限制 |
| 尾部點/空格（`[.\s]+$`）| `.git.`, `.claude ` 在 Windows 等同 `.git` |
| DOS device names（`.CON`, `.PRN` 等） | 特殊設備映射 |
| 三個以上連續點（`.../`, `/...`） | 路徑遍歷偽裝 |
| UNC 路徑（`\\server\`, `//server/`） | 網路資源存取 |

注意：NTFS ADS 的 `:` 語法只在 Windows/WSL 平台檢查（Linux 上 NTFS 用 xattr）。

### checkPathSafetyForAutoEdit(path, precomputedPathsToCheck?)

```typescript
export function checkPathSafetyForAutoEdit(
  path: string,
  precomputedPathsToCheck?: readonly string[],
):
  | { safe: true }
  | { safe: false; message: string; classifierApprovable: boolean }
```

**檢查順序：**
1. `hasSuspiciousWindowsPathPattern()` → 不可 classifier 批准
2. `isClaudeConfigFilePath()` → 可 classifier 批准（`classifierApprovable: true`）
3. `isDangerousFilePathToAutoEdit()` → 可 classifier 批准

**symlink 防繞過**：同時檢查原始路徑和 `getPathsForPermissionCheck(path)` 解析後路徑。

---

## 工作目錄邊界

### pathInAllowedWorkingPath(path, context, precomputedPathsToCheck?)

```typescript
export function pathInAllowedWorkingPath(
  path: string,
  toolPermissionContext: ToolPermissionContext,
  precomputedPathsToCheck?: readonly string[],
): boolean
```

**機制：**
1. 解析輸入路徑（含 symlink）
2. 解析所有 working directories（含 symlink，memoized）
3. `pathsToCheck.every(pathToCheck => workingPaths.some(wp => pathInWorkingPath(pathToCheck, wp)))`

注意：**所有**解析版本都必須在允許的工作目錄內。

### pathInWorkingPath(path, workingPath)

```typescript
export function pathInWorkingPath(path: string, workingPath: string): boolean
```

**處理：**
- 展開 `~` 和相對路徑
- macOS symlink 正規化：`/private/var/` → `/var/`、`/private/tmp/` → `/tmp/`
- 大小寫正規化（防止 mixed-case 繞過）
- 使用 POSIX relative path：如果 relative 包含 `../` 則在工作目錄外

---

## 規則匹配系統

### matchingRuleForInput(path, context, toolType, behavior)

```typescript
export function matchingRuleForInput(
  path: string,
  toolPermissionContext: ToolPermissionContext,
  toolType: 'edit' | 'read',
  behavior: 'allow' | 'deny' | 'ask',
): PermissionRule | null
```

**路徑模式解析（patternWithRoot）：**

| 前綴 | 解析規則 |
|------|---------|
| `//path` | 絕對路徑（`//foo` → `/foo`） |
| `~/path` | 相對於 `homedir()` |
| `/path` | 相對於 settings 檔案所在目錄 |
| `./path` | 去除 `./` 前綴，相對於 CWD |
| `path` | 相對於 CWD |

**Windows 特殊處理：**`//c/Users/...` 格式識別為 POSIX 磁碟路徑，轉換為 `C:\Users\...`。

**ignore 函式庫**：使用 gitignore 語義進行模式匹配，`/**` 後綴被移除（ignore 自動處理目錄遞歸）。

---

## 讀取許可：checkReadPermissionForTool()

**檢查順序（12 步）：**

1. UNC 路徑早期封鎖（`\\` 或 `//` 開頭）
2. Windows 可疑路徑模式
3. Read deny rule（最高優先，防止 allow rule 繞過）
4. 內部可讀路徑（`checkReadableInternalPath`：session memory、plan files、project dir）
5. Edit deny rule（edit deny 也阻止讀取）
6. Edit allow rule（edit allow 隱含 read allow）
7. Read allow rule
8. 在工作目錄內 → allow
9. Read ask rule → ask
10. `checkPathSafetyForAutoEdit` + acceptEdits 模式判斷
11. Claude temp dir 等特殊路徑
12. 預設 → ask

**關鍵安全點**：Read deny rule 必須在所有 allow 路徑之前（#3），防止「edit access implies read」邏輯被 deny 繞過。

---

## 特殊路徑系統

### Claude Temp Dir（getClaudeTempDir）

```
Unix:    /tmp/claude-{uid}/   （per-user，UID 防衝突）
Windows: {TEMP}/claude/
```

Memoized（解析 macOS `/tmp` → `/private/tmp` symlink）。

### Session Memory Dir

```
{projectDir}/{sessionId}/session-memory/
```

使用 `normalize()` 防止 `..` 路徑遍歷。

### Scratchpad Dir（tengu_scratch feature gate）

```
/tmp/claude-{uid}/{sanitized-cwd}/{sessionId}/scratchpad/
```

建立時使用 `0o700` 權限（owner-only）。

### Bundled Skills Root

```
/tmp/claude-{uid}/bundled-skills/{VERSION}/{nonce}/
```

`nonce = randomBytes(16).toString('hex')` — 防止攻擊者預建目錄樹（shared `/tmp` sticky bit 攻擊）。

---

## 寫入許可：checkWritePermissionForTool()

與讀取許可類似，但：
1. 額外檢查 `isClaudeConfigFilePath`（config files 需要明確許可）
2. 路徑安全評估 → `checkPathSafetyForAutoEdit`（包含危險路徑黑名單）
3. sandbox 路徑白名單（`isPathInSandboxWriteAllowlist`）

### Ignore Pattern 生成：getFileReadIgnorePatterns()

為 file listing（如 ls）提供 deny pattern，隱藏被 deny rule 保護的路徑。
防止 Claude 在列表中「看見」不該讀取的檔案。

---

## 模式優先順序摘要

```
讀取：
  UNC block > Windows suspicious > Read deny > Internal readable >
  Edit deny > Edit allow > Read allow > In working dir >
  Read ask > autoEdit safety > temp/internal paths > ask

寫入：
  UNC block > Windows suspicious > Write deny > Internal writable >
  Dangerous path block > Edit deny > Edit allow > In working dir >
  Sandbox allowlist > Edit ask > autoEdit safety > ask
```
