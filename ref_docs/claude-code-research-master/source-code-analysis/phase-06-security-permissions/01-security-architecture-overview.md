# Phase 6 — 01 安全架構總覽

## 多層防禦模型

Claude Code 的安全架構採用縱深防禦（Defense-in-Depth），分為七個層次：

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: AI-Level Policy (cyberRiskInstruction.ts)         │
│  → 模型層指令，限制進攻性安全行為                              │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Structural Parse Gate (bashPermissions.ts)        │
│  → Tree-sitter AST 解析：too-complex / semantic-fail → ask  │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Bash Security Validators (bashSecurity.ts)        │
│  → 23 個靜態分析 validator：注入、混淆、misparsing            │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Permission Rule Engine (bashPermissions.ts)       │
│  → deny / ask / allow 規則匹配（exact / prefix / wildcard）  │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: Path Constraint Checks (pathValidation.ts)        │
│  → 工作目錄邊界、危險路徑（.git/.claude/.ssh 等）             │
├─────────────────────────────────────────────────────────────┤
│  Layer 6: Read-Only Validation (readOnlyValidation.ts)      │
│  → 命令白名單（git/gh/docker/ripgrep 等）及旗標安全性         │
├─────────────────────────────────────────────────────────────┤
│  Layer 7: OS Sandbox (sandbox-adapter.ts)                   │
│  → bwrap/sandbox-runtime 檔案系統 + 網路隔離                  │
└─────────────────────────────────────────────────────────────┘
```

## 層次說明

### Layer 1：AI 模型指令層
- 檔案：`src/constants/cyberRiskInstruction.ts`
- 作用：在 system prompt 層級告訴模型哪些安全請求可協助、哪些必須拒絕
- 涵蓋：授權滲透測試、CTF、防禦用途允許；破壞技術、DoS、供應鏈攻擊拒絕

### Layer 2：結構解析閘門
- 主要入口：`bashToolHasPermission()` in `bashPermissions.ts`
- Tree-sitter AST 解析命令結構：
  - `too-complex`：包含命令替換、控制流、不可靜態分析的模式 → 強制 ask
  - `semantic-fail`：eval、zsh builtins、危險命令名稱 → ask
  - `simple`：乾淨解析，繼續後續層次

### Layer 3：靜態安全驗證器
- 23 個 validator，按 ID 1–23 編號（BASH_SECURITY_CHECK_IDS）
- 分為 `earlyValidators`（快速允許路徑）和主 `validators`
- 分類：`misparsingValidators`（語法差異攻擊）和 `nonMisparsingValidators`（一般危險模式）
- 詳見 `02-bash-security-rules.md`

### Layer 4：權限規則引擎
- 三類規則：`deny`（封鎖）、`ask`（詢問）、`allow`（允許）
- 匹配模式：exact（精確）、prefix（前綴 `cmd:*`）、wildcard（通配符）
- 規則來源：cliArg / command / session / userSettings / projectSettings / policySettings / localSettings / flagSettings
- 詳見 `03-bash-permissions-model.md`

### Layer 5：路徑約束檢查
- 工作目錄白名單（project cwd + additionalDirectories）
- 危險路徑保護：`.git`、`.claude`、`~/.ssh`、`/etc` 等
- 符號連結解析防繞過

### Layer 6：唯讀驗證
- 唯讀命令白名單（旗標級別精確控制）
- 涵蓋 Bash / PowerShell / Shell 三個工具
- 詳見 `04-readonly-validation.md`

### Layer 7：OS 沙箱
- 基於 `@anthropic-ai/sandbox-runtime`（Linux bwrap / macOS sandbox）
- 檔案系統讀寫隔離、網路域名白名單
- 詳見 `06-sandbox-mechanism.md`

## 決策流程圖

```
命令輸入
   │
   ▼
[AST Parse] ──too-complex──► ask
   │ simple
   ▼
[checkSemantics] ──fail──► ask (+ deny 優先)
   │ ok
   ▼
[Sandbox Auto-Allow?] ──yes + no deny rule──► allow
   │
   ▼
[Exact Match Rule] ──deny/ask/allow──► return
   │ passthrough
   ▼
[Classifier (deny/ask rules)] ──high confidence match──► deny/ask
   │
   ▼
[Command Operator Permissions] ──pipe/redirect──► recursive check
   │
   ▼
[Legacy Misparsing Gate] (tree-sitter unavailable only)
   │
   ▼
[Subcommand Fanout: foreach subcommand]
   │
   ├── [checkCommandAndSuggestRules]
   │     ├── Exact match check
   │     ├── Prefix/wildcard rule check
   │     ├── bashCommandIsSafe (injection check)
   │     ├── checkPathConstraints
   │     ├── checkSedConstraints
   │     ├── checkPermissionMode
   │     └── isReadOnly → allow
   │
   └── 最終 passthrough → 權限提示對話框
```

## 關鍵設計決策

1. **Fail-Closed 原則**：無法解析 → 要求許可（不是自動允許）
2. **Deny 優先**：deny 規則在所有允許路徑之前檢查
3. **多環境 env var 剝離**：Allow 規則只剝離安全 env var；Deny 規則剝離所有 env var（防繞過）
4. **複合命令保護**：前綴規則不匹配複合命令（`Bash(cd:*)` 不能匹配 `cd /path && rm -rf`）
5. **符號連結解析**：所有路徑同時檢查原始路徑和解析後路徑

## 跨工具安全統一

| 工具 | 安全機制 |
|------|---------|
| BashTool | AST parse + 23 validators + 規則引擎 + path constraints |
| PowerShellTool | cmdlet allowlist + AST parser + path validation |
| FileReadTool | filesystem.ts 規則匹配 + UNC/Windows 路徑保護 |
| FileEditTool | 危險路徑黑名單 + 工作目錄邊界 |
| WebFetchTool | 網路域名白名單（通過 sandbox 或 permission rules） |
