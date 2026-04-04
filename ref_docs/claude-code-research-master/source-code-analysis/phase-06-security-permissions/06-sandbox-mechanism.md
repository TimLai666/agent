# Phase 6 — 06 Sandbox 沙箱機制

## 架構

```
Claude Code
    │
    ├── SandboxManager（sandbox-adapter.ts）
    │     ├── 讀取 settings 轉換為 SandboxRuntimeConfig
    │     ├── 呼叫 BaseSandboxManager（@anthropic-ai/sandbox-runtime）
    │     └── 提供 isSandboxingEnabled(), isAutoAllowBashIfSandboxedEnabled()
    │
    └── @anthropic-ai/sandbox-runtime
          ├── Linux: bwrap (bubblewrap)
          ├── macOS: sandbox-exec
          └── WSL2+: bwrap
```

## 啟用條件

```typescript
function isSandboxingEnabled(): boolean {
  // 1. 平台必須支援（macOS / Linux / WSL2+，不含 WSL1）
  if (!isSupportedPlatform()) return false

  // 2. 依賴檢查（bwrap/sandbox-exec + ripgrep）
  if (checkDependencies().errors.length > 0) return false

  // 3. enabledPlatforms 限制（undocumented，企業用）
  if (!isPlatformInEnabledList()) return false

  // 4. 使用者 settings.sandbox.enabled
  return getSandboxEnabledSetting()
}
```

## Settings → SandboxRuntimeConfig 轉換

### 網路配置

```typescript
// WebFetch allow rules → allowedDomains
// WebFetch deny rules → deniedDomains
// allowManagedSandboxDomainsOnly: true → 只使用 policySettings 的域名
network: {
  allowedDomains,
  deniedDomains,
  allowUnixSockets,
  allowAllUnixSockets,
  allowLocalBinding,
  httpProxyPort,
  socksProxyPort,
}
```

### 檔案系統配置

**allowWrite（預設允許）：**
```
'.'                              # 當前目錄
getClaudeTempDir()               # /tmp/claude-{uid}/（Shell.ts CWD 追蹤）
worktreeMainRepoPath             # git worktree 主 repo（若有）
additionalDirectories            # --add-dir CLI 旗標
Edit allow rules paths           # 使用者設定的寫入 allow
sandbox.filesystem.allowWrite    # sandbox 特定寫入允許
```

**denyWrite（強制封鎖）：**
```
settings.json files              # 所有 settings 檔案（防沙箱逃脫）
getManagedSettingsDropInDir()    # managed settings 目錄
.claude/skills (originalCwd)     # skills 目錄（與 commands/agents 同等保護）
.claude/skills (cwd if differs)  # cd 後的 skills 目錄
Edit deny rules paths            # 使用者設定的寫入 deny
bareGitRepoFiles (if exist)      # HEAD/objects/refs/hooks/config（若存在）
sandbox.filesystem.denyWrite     # sandbox 特定寫入拒絕
```

**denyRead：**
```
Read deny rules paths            # 使用者設定的讀取 deny
sandbox.filesystem.denyRead      # sandbox 特定讀取拒絕
```

**allowRead：**
```
sandbox.filesystem.allowRead     # sandbox 特定讀取允許
# allowManagedReadPathsOnly: true 時只取 policySettings
```

### 裸 Repo 保護（bareGitRepoFiles）

```typescript
// 攻擊：git is_git_directory() 把含 HEAD+objects+refs 的目錄視為裸 repo
// 攻擊者在 cwd 種植這些檔案 + core.fsmonitor hook → 沙箱外 git 執行觸發 RCE

const bareGitRepoFiles = ['HEAD', 'objects', 'refs', 'hooks', 'config']
// 存在的檔案 → denyWrite（唯讀綁定，阻止修改）
// 不存在的 → bareGitRepoScrubPaths（沙箱後清除，防種植）
```

`scrubBareGitRepoFiles()` 在每個沙箱命令後清除可能被種植的裸 repo 檔案。

## 路徑語義（兩套規則）

### Permission Rule 路徑語義（resolvePathPatternForSandbox）

用於 `Edit(...)` / `Read(...)` 規則的路徑：

```
//path → /path（絕對路徑）
/path  → {settingsFileDir}/path（相對於 settings 目錄）
~/path → pass-through（sandbox-runtime 處理）
./path → pass-through（sandbox-runtime 處理）
```

### Sandbox Filesystem 設定路徑語義（resolveSandboxFilesystemPath）

用於 `sandbox.filesystem.allowWrite` 等設定：

```
//path → /path（保持相容）
/path  → 直接絕對路徑（不是 settings-relative！Issue #30067 修復）
~/path → expandPath() 展開
./path → 相對於 settingsFileDir
```

**為什麼不同？** Permission rules 的 `/path` 是「相對 settings 目錄」的歷史慣例，但 sandbox 設定的使用者期望 `/Users/foo/.cargo` 就是絕對路徑。

## autoAllowBashIfSandboxed 功能

當 sandbox 和此設定都啟用時，沙箱環境內的 Bash 命令只需通過 deny/ask rule 檢查即可自動允許：

```typescript
function checkSandboxAutoAllow(input, toolPermissionContext): PermissionResult {
  // 1. 全命令精確 deny
  // 2. 全命令前綴 deny
  // 3. 複合命令：逐子命令檢查 deny（deny 優先於 ask）
  // 4. Ask rule（收集後在所有 deny 確認後回傳）
  // 5. 無 deny → auto allow
}
```

**注意**：複合命令的子命令 deny 檢查必須在全命令 ask 之前，防止 ask rule 降級 deny 至 ask。

## 沙箱後清理

```typescript
export async function cleanupAfterCommand(
  exitCode: number,
  command: string,
): Promise<void> {
  scrubBareGitRepoFiles()  // 同步（Shell.ts:367 限制）
}
```

## UnsandboxedCommands 允許設定

```typescript
function areUnsandboxedCommandsAllowed(): boolean {
  return settings?.sandbox?.allowUnsandboxedCommands ?? true
}
```

某些命令（如 `git fetch`、`npm install`）可能需要比 sandbox 允許範圍更廣的網路存取，此設定允許它們繞過沙箱。

## 依賴檢查

```typescript
const checkDependencies = memoize((): SandboxDependencyCheck => {
  return BaseSandboxManager.checkDependencies({
    command: rgPath,  // ripgrep 是 sandbox-runtime 的依賴
    args: rgArgs,
  })
})
```

Memoized 因為依賴狀態在 session 內不會改變。

## Sandbox UI 狀態

`sandbox-ui-utils.ts` 提供 UI 用的沙箱狀態查詢函數，顯示沙箱是否啟用、是否自動允許等資訊。
