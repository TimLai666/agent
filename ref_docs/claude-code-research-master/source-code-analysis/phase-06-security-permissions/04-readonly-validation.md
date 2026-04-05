# Phase 6 — 04 唯讀模式實作

## 三份實作比較

| 面向 | BashTool/readOnlyValidation.ts | utils/shell/readOnlyCommandValidation.ts | PowerShellTool/readOnlyValidation.ts |
|------|-------------------------------|------------------------------------------|--------------------------------------|
| 對象 | Bash 命令（POSIX shell） | 共享工具函數庫 | PowerShell cmdlet |
| 解析器 | shell-quote (splitCommand) | validateFlags() | PS AST parser |
| 命令集 | COMMAND_ALLOWLIST + READONLY_COMMAND_REGEXES | GIT/GH/Docker/ripgrep 定義 | CMDLET_ALLOWLIST |
| 旗標驗證 | 旗標白名單（FlagArgType） | 同左（共用） | PowerShell 參數白名單 |
| 路徑提取 | 有（檢查寫入路徑） | 無（由呼叫者處理） | 有（CMDLET_PATH_CONFIG） |

---

## BashTool/readOnlyValidation.ts

### 入口函數：checkReadOnlyConstraints()

```typescript
export function checkReadOnlyConstraints(
  input: z.infer<typeof BashTool.inputSchema>,
  compoundCommandHasCd: boolean,
): PermissionResult
```

**執行流程：**

1. `tryParseShellCommand(command)` 失敗 → passthrough（交給上層處理）
2. `bashCommandIsSafe_DEPRECATED()` 非 passthrough → passthrough（命令含危險模式）
3. 拆分子命令，逐一判斷：
   - `containsUnquotedExpansion()` → passthrough（含未引號的 `$`/`` ` ``/`$(` 展開）
   - `isCommandSafeViaFlagParsing()` → true（白名單匹配）
   - READONLY_COMMAND_REGEXES 匹配 + git 危險旗標排除 → true
   - 其他 → false（非唯讀）
4. 所有子命令唯讀 → allow；任一非唯讀 → passthrough
5. 額外檢查：`commandWritesToGitInternalPaths()` → passthrough（防沙箱逃脫）

### COMMAND_ALLOWLIST（bash 版）

主要包含的命令（旗標白名單精確控制）：

| 命令 | 安全旗標重點 | 排除的危險旗標 |
|------|------------|--------------|
| `xargs` | `-I`, `-n`, `-P`, `-L`, `-0`, `-t` | `-i`, `-e`（optional-arg 解析差異） |
| `sed` | `-e`, `-n`, `-r`, `-E` | `-i`（in-place 寫入）；需 sedCommandIsAllowedByAllowlist |
| `sort` | `-k`, `-t`, `-u`, `-n`, 等 | `-o`（輸出到檔案） |
| `grep` | 完整旗標集 | — |
| `base64` | `-d`, `-w`, `-i` | `respectsDoubleDash: false`（macOS） |
| `ps` | 標準 UNIX 旗標 | BSD-style `e`（顯示環境變數） |
| `netstat` | 顯示旗標 | — |
| `file`, `man`, `help` | 各自安全旗標 | `man -P`（任意 pager 執行） |
| `sha256sum`, `sha1sum` | 驗證旗標 | — |
| `fd`, `fdfind` | 搜尋旗標 | `-x/--exec`, `-X/--exec-batch`, `-l/--list-details` |

另外引入共用的：`GIT_READ_ONLY_COMMANDS`、`GH_READ_ONLY_COMMANDS`、`DOCKER_READ_ONLY_COMMANDS`、`RIPGREP_READ_ONLY_COMMANDS`、`PYRIGHT_READ_ONLY_COMMANDS`、`EXTERNAL_READONLY_COMMANDS`

### containsUnquotedExpansion()

防止 `$VAR`、`$(cmd)`、`` `cmd` `` 等展開繞過旗標白名單：

```
uniq --skip-chars=0$_   → bash 展開 $_ 為上個命令最後引數
                         → 繞過 uniq 旗標驗證
```

### READONLY_COMMAND_REGEXES

用 regex 匹配的補充唯讀命令（不在 COMMAND_ALLOWLIST 中）。

**git 額外封鎖（所有 git 命令套用）：**
```typescript
// 以下旗標無論在哪個 git 子命令都封鎖：
if (testCommand.includes('git')) {
  if (/\s-c[\s=]/.test(testCommand))          return false  // 任意 config 注入 → RCE
  if (/\s--exec-path[\s=]/.test(testCommand)) return false  // git 執行路徑覆蓋
  if (/\s--config-env[\s=]/.test(testCommand)) return false // 環境變數 config 注入
}
```

### Git 裸 repo 沙箱逃脫保護

```typescript
// 攻擊模式：
// mkdir -p objects refs hooks &&
// echo '#!/bin/bash\nmalicious' > hooks/pre-commit &&
// touch HEAD &&
// git status   ← 觸發 hooks/pre-commit

function commandWritesToGitInternalPaths(command: string): boolean
```

偵測複合命令中是否同時含有：
1. 寫入 `HEAD`, `objects/`, `refs/`, `hooks/` 的操作
2. 後續執行 git 命令

任一情況 → passthrough（非唯讀，需要許可）

---

## utils/shell/readOnlyCommandValidation.ts（共用函數庫）

### 核心：validateFlags()

```typescript
export function validateFlags(
  args: string[],
  safeFlags: Record<string, FlagArgType>,
  { respectsDoubleDash = true }: { respectsDoubleDash?: boolean } = {},
): boolean
```

`FlagArgType`：`'none'` | `'string'` | `'number'` | `'char'` | `'{}'` | `'EOF'` | `'string-nocheck'`

遇到未知旗標 → 回傳 false（命令危險）

### GIT_READ_ONLY_COMMANDS（完整子命令白名單）

```
git diff       git log        git show       git shortlog
git status     git blame      git ls-files   git config --get
git ls-remote  git remote     git remote show  git branch
git tag        git reflog     git stash list   git rev-parse
git cat-file   git merge-base git describe     git archive
git grep       git check-attr git check-ignore git worktree
```

**特別安全處理（git diff / git log）：**
```
-S/-G/-O 必須是 'string'（非 'none'）
原因：git -S 需要必填引數。若設為 'none'，
`git diff -S -- --output=/tmp/pwned` 中
validator 以為 -S 無引數，跳過 `--`，
而 git 將 `--` 當 -S 的引數，解析 --output= → 任意檔案寫入
```

**git ls-remote 排除 `--server-option`：**
```
這是網路 WRITE 原語（傳送任意字串到 remote git server）
即使不含命令替換，也可外洩資料到攻擊者控制的 remote
```

### EXTERNAL_READONLY_COMMANDS（其他外部命令）

```
curl / wget（加 -o 則需路徑驗證）
jq（旗標：-r, -c, -e, -n, -s, -R, -C，排除 -f/--from-file）
cat, ls, wc, head, tail, echo
tr, cut, awk, uniq, diff
find（排除 -exec, -execdir, -delete, -ok, -okdir）
stat, realpath, readlink
lsof, which, whoami, id, hostname
env, printenv（僅特定旗標）
```

### containsVulnerableUncPath()

```typescript
export function containsVulnerableUncPath(path: string): boolean
```

偵測 Windows UNC 路徑模式：
- `\\server\share` 格式（可存取網路資源）
- 防止 WebDAV 攻擊和憑證洩漏

---

## PowerShellTool/readOnlyValidation.ts

### CMDLET_ALLOWLIST（物件用 Object.create(null) 防原型污染）

**檔案系統唯讀 cmdlet：**
```
Get-ChildItem (gci/ls/dir/gls)
Get-Item (gi)
Get-Content (gc/cat/type)
Get-PSDrive
Get-Location (gl/pwd)
Resolve-Path
Convert-Path
Split-Path / Join-Path
Test-Path
```

**環境/系統 cmdlet：**
```
Get-Process (gps/ps)
Get-Service (gsv)
Get-Variable (gv)
Get-ChildItem Env: (環境變數)
Get-Command (gcm)
Get-Help (help/man)
Get-Member (gm)
Get-History (h/history)
```

**特殊防護：argLeaksValue()**

```typescript
export function argLeaksValue(_cmd: string, element?: ParsedCommandElement): boolean
```

針對 `Write-Output`, `Start-Sleep` 等 cmdlet，防止以下模式外洩環境變數：
- `Write-Output $env:SECRET` — Variable 類型引數
- `Start-Sleep $env:SECRET` — 型別強制轉換錯誤訊息中洩漏

只允許：`StringConstant` 和 `Parameter` 類型（literal + flag names）

**Cmdlet 別名對應：**
```typescript
export const COMMON_ALIASES: Record<string, string> = Object.assign(
  Object.create(null),
  {
    ls: 'get-childitem', dir: 'get-childitem', gci: 'get-childitem',
    cat: 'get-content',  type: 'get-content',  gc: 'get-content',
    ps: 'get-process',   gps: 'get-process',
    pwd: 'get-location', gl: 'get-location',
    // ...
  }
)
```

### 判斷邏輯

```typescript
// Pipeline 判斷：拆分 | 後的每個 segment
const segments = getPipelineSegments(statement)
for (const segment of segments) {
  // 取第一個 token 為 cmdlet 名稱
  const cmdletName = normalize(getFirstToken(segment))

  // 查找 CMDLET_ALLOWLIST（含別名解析）
  const config = CMDLET_ALLOWLIST[resolveAlias(cmdletName)]
  if (!config) return false  // 未知 cmdlet → 非唯讀

  // 驗證 flags/parameters
  if (!validatePowerShellFlags(segment, config)) return false
}
```

---

## 三者共同設計原則

1. **旗標白名單（非黑名單）**：不知道的旗標一律拒絕
2. **可接受的 false positive**：安全優先，合法用法可手動 approve
3. **防 git config 注入**：三者均有 `-c`, `--exec-path`, `--config-env` 的保護
4. **引號感知**：在 validated args 前確認無未引號展開
5. **複合命令處理**：逐子命令驗證，任一非唯讀即回傳非唯讀
