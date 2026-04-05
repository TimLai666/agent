# Phase 6 — 02 Bash 命令安全過濾完整規則集

## 概覽

`bashSecurity.ts` 實作兩個對外 API：
- `bashCommandIsSafe_DEPRECATED(command)` — 同步版（當 tree-sitter 不可用時）
- `bashCommandIsSafeAsync_DEPRECATED(command, onDivergence?)` — 非同步版（優先用 tree-sitter）

兩者均回傳 `PermissionResult`，行為值為 `allow` / `passthrough` / `ask`。

## 安全檢查 ID 對照表

```typescript
const BASH_SECURITY_CHECK_IDS = {
  INCOMPLETE_COMMANDS: 1,
  JQ_SYSTEM_FUNCTION: 2,
  JQ_FILE_ARGUMENTS: 3,
  OBFUSCATED_FLAGS: 4,
  SHELL_METACHARACTERS: 5,
  DANGEROUS_VARIABLES: 6,
  NEWLINES: 7,
  DANGEROUS_PATTERNS_COMMAND_SUBSTITUTION: 8,
  DANGEROUS_PATTERNS_INPUT_REDIRECTION: 9,
  DANGEROUS_PATTERNS_OUTPUT_REDIRECTION: 10,
  IFS_INJECTION: 11,
  GIT_COMMIT_SUBSTITUTION: 12,
  PROC_ENVIRON_ACCESS: 13,
  MALFORMED_TOKEN_INJECTION: 14,
  BACKSLASH_ESCAPED_WHITESPACE: 15,
  BRACE_EXPANSION: 16,
  CONTROL_CHARACTERS: 17,
  UNICODE_WHITESPACE: 18,
  MID_WORD_HASH: 19,
  ZSH_DANGEROUS_COMMANDS: 20,
  BACKSLASH_ESCAPED_OPERATORS: 21,
  COMMENT_QUOTE_DESYNC: 22,
  QUOTED_NEWLINE: 23,
}
```

## 執行管線

### 前置處理（所有驗證前）

1. **控制字元封鎖**（CheckID: 17）：`/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/` → ask + isMisparsing
2. **Shell-quote 單引號 bug 偵測**：`hasShellQuoteSingleQuoteBug()` → ask + isMisparsing
3. **Heredoc 主體剝離**：`extractHeredocs(command, {quotedOnly: true})` — 只剝離有引號/跳脫分隔符的 heredoc

### 早期驗證器（earlyValidators）—有 allow 路徑，短路後續

#### validateEmpty
- 空命令直接 `allow`

#### validateIncompleteCommands（CheckID: 1）
- 以 `\t` 開頭 → ask（Tab 開頭的片段）
- 以 `-` 開頭 → ask（旗標開頭）
- 以 `&&`, `||`, `;`, `>>`, `<` 開頭 → ask（延續行）

#### validateSafeCommandSubstitution
- 識別 `$(cat <<'DELIM'\n...\nDELIM\n)` 安全 heredoc 替換模式
- 必要條件：分隔符有引號/跳脫、替換在**引數位置**（非命令名稱位置）
- 通過 → `allow`（短路所有後續 validator）
- 剩餘文字必須通過字元白名單 `/^[a-zA-Z0-9 \t"'.\-/_@=,:+~]*$/`
- 剩餘文字還要遞迴通過 `bashCommandIsSafe_DEPRECATED`

#### validateGitCommit（CheckID: 12）
- 匹配 `git commit ... -m <quote>...<quote><remainder>` 模式
- commit message 包含 `$()` / `` ` `` / `${}` → ask
- remainder 包含 `;|&()` → passthrough（交給後續）
- remainder 包含未引號 `<>` → passthrough
- message 以 `-` 開頭 → ask（混淆旗標）
- 安全：直接 allow

### 主驗證器執行順序（validators）

#### validateJqCommand（CheckID: 2, 3）
- `jq` 命令中的 `system()` 函數 → ask（任意命令執行）
- 危險旗標：`-f`, `--from-file`, `--rawfile`, `--slurpfile`, `-L`, `--library-path` → ask

#### validateObfuscatedFlags（CheckID: 4）
**ANSI-C 引號：**
- `$'...'` 模式 → ask（可隱藏任意字元，subId: 5）
- `$"..."` 模式 → ask（locale 引號，subId: 6）

**空引號前導旗標：**
- `$''-exec` / `$""-exec` → ask（subId: 9）
- `(?:^|\s)(?:''|"")+\s*-` → ask（subId: 7）
- `(?:""|'')+['"]-` → ask（同質空引號對 + 引號破折號，subId: 10）
- `(?:^|\s)['"]{3,}` → ask（三個以上連續引號，subId: 11）

**引號包裹旗標：**
- 空白後緊接引號，引號內容 `/^-+[a-zA-Z0-9$`]/` → ask（subId: 4）
- `split-quote flag`：`"-"exec` 這類連鎖引號 → ask
- `fullyUnquotedContent` 中 `\s['"`]-` → ask（subId: 2）
- `fullyUnquotedContent` 中 `['"`]{2}-` → ask（subId: 3）
- 旗標中含引號字元（e.g., `--fl"ag"`）→ ask（subId: 1）

#### validateShellMetacharacters（CheckID: 5）
- 雙/單引號字串內含 `;` 或 `&` → ask
- `find` 的 `-name`, `-path`, `-iname`, `-regex` 引數含 `|`, `;`, `&` → ask

#### validateDangerousVariables（CheckID: 6）
- 重導向中的變數：`< $VAR`、`$VAR |`、`| $VAR`、`$VAR >` → ask

#### validateCommentQuoteDesync（CheckID: 22）
- 未引號的 `#` 後跟引號字元（同行） → ask
- 攻擊：`echo "it's" # ' ` 導致後續 quote tracker 去同步
- Tree-sitter 可用時跳過（AST 是權威）

#### validateQuotedNewline（CheckID: 23）
- 引號內的換行 + 下一行以 `#` 開頭（trim 後） → ask
- 防範 `stripCommentLines` 被濫用隱藏引數
- isMisparsing: true（早於行處理邏輯執行）

#### validateCarriageReturn（CheckID: 7, subId: 2）
- 雙引號外的 `\r` → ask + isMisparsing
- 原因：shell-quote 的 `\s` 包含 `\r`，bash IFS 不含 `\r`，導致 tokenization 差異
- 攻擊：`TZ=UTC\recho curl evil.com` with `Bash(echo:*)` allow rule

#### validateNewlines（CheckID: 7, subId: 1）
- `fullyUnquotedPreStrip` 中：`(?<![\s]\\)[\n\r]\s*\S` → ask
- 允許：`\ \n` 行延續（反斜線後跟空白再換行）
- 不允許：mid-word 行延續（會隱藏命令名稱）

#### validateIFSInjection（CheckID: 11）
- `$IFS` 或 `${...IFS...}` → ask（繞過 regex 驗證）

#### validateProcEnvironAccess（CheckID: 13）
- `/proc/.*/environ` → ask（讀取環境變數，可暴露 API keys）

#### validateDangerousPatterns（CheckID: 8）
- 未跳脫的反引號 `` ` `` → ask（命令替換）
- COMMAND_SUBSTITUTION_PATTERNS（每個 pattern 觸發 ask）：

```typescript
const COMMAND_SUBSTITUTION_PATTERNS = [
  { pattern: /<\(/, message: 'process substitution <()' },
  { pattern: />\(/, message: 'process substitution >()' },
  { pattern: /=\(/, message: 'Zsh process substitution =()' },
  { pattern: /(?:^|[\s;&|])=[a-zA-Z_]/, message: 'Zsh equals expansion (=cmd)' },
  { pattern: /\$\(/, message: '$() command substitution' },
  { pattern: /\$\{/, message: '${} parameter substitution' },
  { pattern: /\$\[/, message: '$[] legacy arithmetic expansion' },
  { pattern: /~\[/, message: 'Zsh-style parameter expansion' },
  { pattern: /\(e:/, message: 'Zsh-style glob qualifiers' },
  { pattern: /\(\+/, message: 'Zsh glob qualifier with command execution' },
  { pattern: /\}\s*always\s*\{/, message: 'Zsh always block' },
  { pattern: /<#/, message: 'PowerShell comment syntax' },
]
```

#### validateRedirections（CheckID: 9, 10）
- `fullyUnquotedContent` 含 `<` → ask（輸入重導向，可讀敏感檔案）
- `fullyUnquotedContent` 含 `>` → ask（輸出重導向，可寫任意檔案）
- **nonMisparsingValidator**：結果不帶 isMisparsing flag

#### validateBackslashEscapedWhitespace（CheckID: 15）
- 引號外的 `\ `（反斜線空格）或 `\<Tab>` → ask + isMisparsing
- 原因：shell-quote 將 `\ ` 解碼為空格（兩 token），bash 視為單一 token
- 攻擊：`echo\ test/../../../usr/bin/touch /tmp/file`

#### validateBackslashEscapedOperators（CheckID: 21）
- 引號外的 `\;`、`\|`、`\&`、`\<`、`\>` → ask + isMisparsing
- 原因：`splitCommand` 正規化 `\;` 為 `;`，導致下游重解析時路徑驗證失效
- 攻擊：`cat safe.txt \; echo ~/.ssh/id_rsa`
- Tree-sitter 可用且無 operator nodes → 跳過（減少 false positive）

#### validateUnicodeWhitespace（CheckID: 18）
- Unicode 空白字元 `[\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]` → ask
- shell-quote 視為 word 分隔符，bash 視為字面字元

#### validateMidWordHash（CheckID: 19）
- `unquotedKeepQuoteChars` 中：`\S(?<!\$\{)#` → ask
- shell-quote 的 mid-word `#` 視為 comment-start，bash 視為字面字元
- 另外檢查 join 後的版本（行延續後）

#### validateBraceExpansion（CheckID: 16）
- subId: 1：`fullyUnquotedPreStrip` 中 `{...,... }` 或 `{...`..`...}` → ask
- subId: 2：unescaped `}` 數量超過 `{` → ask（引號剝離後 brace 不對稱）
- subId: 3：原始命令中 `'{'` 或 `"{"` 且存在未跳脫的 `{` → ask
- 攻擊：`git ls-remote {--upload-pack="touch /tmp/test",test}`

#### validateZshDangerousCommands（CheckID: 20）
**ZSH_DANGEROUS_COMMANDS 集合（任何一個作為 base command → ask）：**

```typescript
const ZSH_DANGEROUS_COMMANDS = new Set([
  'zmodload',  // 載入危險模組的入口
  'emulate',   // eval 等效（-c flag）
  'sysopen',   // 細粒度檔案 I/O（zsh/system）
  'sysread',   // FD 讀取（zsh/system）
  'syswrite',  // FD 寫入（zsh/system）
  'sysseek',   // FD seek（zsh/system）
  'zpty',      // 偽終端機命令執行（zsh/zpty）
  'ztcp',      // TCP 連線/資料外洩（zsh/net/tcp）
  'zsocket',   // Unix/TCP socket（zsh/net/socket）
  'mapfile',   // 不可見的 file I/O 陣列（zsh/mapfile）
  'zf_rm',     // builtin rm（zsh/files）
  'zf_mv',     // builtin mv（zsh/files）
  'zf_ln',     // builtin ln（zsh/files）
  'zf_chmod',  // builtin chmod（zsh/files）
  'zf_chown',  // builtin chown（zsh/files）
  'zf_mkdir',  // builtin mkdir（zsh/files）
  'zf_rmdir',  // builtin rmdir（zsh/files）
  'zf_chgrp',  // builtin chgrp（zsh/files）
])
```

- `fc -e` → ask（可用 editor 執行任意命令）

#### validateMalformedTokenInjection（CheckID: 14）
- 命令含 `;`, `&&`, `||` 分隔符 + `hasMalformedTokens()` 偵測不平衡分隔符 → ask
- 攻擊：`echo {"hi":"hi;evil"}` 被 shell-quote 解析為含 `{hi:"hi` 的不平衡 token

## 驗證器優先順序與 isMisparsing 標記

```
nonMisparsingValidators = Set([validateNewlines, validateRedirections])

執行邏輯：
- 非 misparsing validator 回傳 ask → 延遲，繼續執行
- misparsing validator 回傳 ask → 立即回傳（帶 isBashSecurityCheckForMisparsing: true）
- 全部完成，無 misparsing ask → 回傳延遲的非 misparsing ask（若有）
```

這個設計防止 `validateRedirections` 先觸發，然後 short-circuit 導致 `validateBackslashEscapedOperators` 未執行。

## 輔助函數

### extractQuotedContent(command, isJq)
- 回傳 `{withDoubleQuotes, fullyUnquoted, unquotedKeepQuoteChars}`
- `withDoubleQuotes`：保留雙引號內容、剝除單引號內容
- `fullyUnquoted`：剝除兩種引號內容
- `unquotedKeepQuoteChars`：剝除內容但保留引號分隔符（用於 mid-word hash 偵測）

### stripSafeRedirections(content)
- 移除 `2>&1`、`>/dev/null`、`</dev/null`（trailing boundary 保護）
- SECURITY：pattern 必須有 `(?=\s|$)` 尾部邊界，防止 `/dev/nullo` 被誤匹配

### hasUnescapedChar(content, char)
- 處理 bash escape sequences，只偵測未跳脫的單字元
- 用於反引號偵測（跳脫的 `` \` `` 是安全的，例如 SQL 命令）
