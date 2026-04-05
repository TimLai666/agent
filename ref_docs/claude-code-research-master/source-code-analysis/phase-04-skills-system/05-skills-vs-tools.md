# Skills 與 Tools 的區別、互動機制、設計哲學比較

---

## 一、根本定義差異

### Tools（工具）

Tools 是 Claude 的**原子能力**，對應 Anthropic API 的 `tool_use` / `tool_result` 機制。每個 tool 有固定的 JSON input/output schema，由 TypeScript 程式碼實作，直接與系統資源（文件系統、shell、網路）互動。

```typescript
// Tool 的結構
export const BashTool: Tool<InputSchema, Output> = buildTool({
  name: 'Bash',
  inputSchema: z.object({ command: z.string() }),
  async call({ command }, context) { /* 執行 shell 命令 */ },
})
```

### Skills（技能）

Skills 是 Claude 的**行為模板**，本質是帶有 metadata 的 Markdown prompt。Skill 被呼叫時，其 prompt 被注入對話，告訴模型「如何完成這類任務」，模型再使用可用的 Tools 去執行。

```typescript
// Skill 的結構
registerBundledSkill({
  name: 'simplify',
  allowedTools: [],  // 告知 SkillTool 要解鎖哪些工具
  async getPromptForCommand(args, context) {
    return [{ type: 'text', text: SIMPLIFY_PROMPT }]  // 返回 prompt 內容
  },
})
```

---

## 二、執行機制比較

| 維度 | Tool | Skill |
|------|------|-------|
| API 層 | Anthropic `tool_use` block | 封裝在 SkillTool（也是一個 Tool）|
| 輸入 | JSON（固定 schema） | 字串（skill 名稱 + 可選 args）|
| 輸出 | 結構化 JSON | 模型重新解讀後的行為（不直接返回資料）|
| 執行者 | TypeScript 程式碼 | 模型本身（閱讀 prompt 後行動）|
| 副作用 | 直接（bash 真的執行，file 真的寫入）| 間接（透過模型再呼叫 Tools）|
| 錯誤處理 | try/catch + errorCode | 模型理解 prompt 後自行判斷 |
| 型別安全 | Zod schema 驗證 | 無型別保證（純文字 prompt）|
| 可觀察性 | tool_use / tool_result 在對話中可見 | 新增 messages 或 result 文字 |

---

## 三、互動機制

### 3.1 SkillTool 是 Tool 與 Skill 的橋接器

```
用戶輸入 "simplify my code"
    │
    ▼
模型看到 system-reminder 中的 Skill 清單
    │
    ▼
模型發出 tool_use: { name: "Skill", input: { skill: "simplify" } }
    │
    ▼
SkillTool.validateInput() → 驗證技能存在、可被呼叫
SkillTool.checkPermissions() → 確認權限
SkillTool.call() → 展開技能 prompt
    │
    ├─ [內聯] 返回 newMessages（把技能 prompt 注入對話）
    │       → 模型閱讀 SIMPLIFY_PROMPT
    │       → 模型呼叫 AgentTool（三個 review agents）
    │       → 模型呼叫 Bash（git diff）
    │       → 模型呼叫 Edit（修復問題）
    │
    └─ [分叉] 啟動獨立子 agent
            → 子 agent 閱讀技能 prompt
            → 子 agent 使用工具執行任務
            → 返回 result 字串給父 agent
```

### 3.2 allowedTools 的作用

Skill 的 `allowedTools` 透過 `contextModifier` 注入到對話上下文：

```typescript
// SkillTool.call() 的返回值
return {
  data: { success: true, commandName, allowedTools },
  newMessages,
  contextModifier(ctx) {
    // 擴展 alwaysAllowRules：技能指定的工具不再需要逐次確認
    const previousGetAppState = ctx.getAppState
    return {
      ...ctx,
      getAppState() {
        const appState = previousGetAppState()
        return {
          ...appState,
          toolPermissionContext: {
            ...appState.toolPermissionContext,
            alwaysAllowRules: {
              ...appState.toolPermissionContext.alwaysAllowRules,
              command: [...new Set([
                ...(appState.toolPermissionContext.alwaysAllowRules.command || []),
                ...allowedTools,
              ])],
            },
          },
        }
      },
    }
  },
}
```

**效果：** 技能呼叫後，在當次對話的剩餘部分，`allowedTools` 中的工具不再需要用戶授權。

### 3.3 model / effort 覆寫

```typescript
// SkillTool.call() — model 覆寫
if (model) {
  modifiedContext = {
    ...modifiedContext,
    options: {
      ...modifiedContext.options,
      mainLoopModel: resolveSkillModelOverride(model, ctx.options.mainLoopModel),
    },
  }
}

// SkillTool.call() — effort 覆寫
if (effort !== undefined) {
  modifiedContext = {
    ...modifiedContext,
    getAppState() { return { ...appState, effortValue: effort } },
  }
}
```

技能可以要求不同的模型（如更強的 Opus）或思考深度，這些透過 `contextModifier` 影響後續的模型呼叫。

---

## 四、內聯 vs 分叉執行的設計哲學

### 內聯執行（預設）

Skill prompt 透過 `newMessages` 注入主對話，模型在同一個對話線程中閱讀和執行。

**優點：**
- 模型可以在執行中詢問用戶（`AskUserQuestion`）
- 技能可以修改主對話的工具授權（contextModifier 有效）
- 用戶可以隨時中斷或重定向

**適合：**
- 需要中途用戶輸入的工作流（skillify、remember、update-config）
- 需要修改主對話狀態的技能
- 互動式任務

### 分叉執行（`context: 'fork'`）

技能在獨立子 agent 中執行，有自己的 token budget 和 message history。

**優點：**
- 不消耗主對話的 context window
- 並行時不相互干擾
- 結果以字串形式返回（清晰的接口）

**適合：**
- 自含式、無需中途用戶輸入的任務
- 長時間執行的任務（如完整的代碼分析）
- 需要隔離 context 的任務

**原始碼中的分叉技能：** 目前從代碼看，`context: 'fork'` 是 `BundledSkillDefinition` 的可選屬性，由 skill 在 `registerBundledSkill` 時設定。

---

## 五、Tools vs Skills 的權限模型

### Tool 的權限

Tool 由 `checkPermissions()` 控制，每次呼叫都走完整的 allow/deny/ask 流程：

```typescript
// 每個 Tool 有自己的 checkPermissions
async checkPermissions({ command }, context): Promise<PermissionDecision> {
  // 檢查 deny rules, allow rules, 模式匹配 ...
}
```

### Skill 的權限

Skill 有兩層權限：

1. **SkillTool 本身的權限**（呼叫技能是否需要確認）：
   ```typescript
   // settings.json
   { "permissions": { "allow": ["Skill(update-config)"] } }
   ```

2. **技能內部使用的工具的權限**（透過 `allowedTools` 解鎖）：
   - 技能列出的 `allowedTools` 在技能執行後自動允許
   - 安全屬性檢查：只包含「安全工具」的技能自動允許，無需用戶確認

**自動允許條件（`skillHasOnlySafeProperties`）：**

```typescript
// 只用了 'Read', 'Grep', 'Glob' 等唯讀工具 → 自動允許
// 有 'Bash', 'Write', 'Edit' 等寫入工具 → 詢問用戶
```

---

## 六、設計哲學比較

### Tools 的設計哲學：確定性與原子性

- **確定性**：相同輸入 → 相同操作（Bash 執行同一命令）
- **原子性**：每個 Tool 做一件事，做完返回結果
- **可組合**：多個 Tool 的輸出是下一個的輸入
- **可驗證**：結果是結構化資料，可以 schema 驗證

Tools 是「機器語言」：精確、無歧義、可預測。

### Skills 的設計哲學：意圖與靈活性

- **意圖導向**：描述「應該做什麼」而非「如何做」
- **靈活性**：允許模型根據上下文調整執行策略
- **知識封裝**：將領域知識（hooks 驗證流程、代碼品質標準）嵌入 prompt
- **人機協作**：技能可以暫停詢問用戶（`AskUserQuestion`）

Skills 是「需求規格書」：指定目標，讓模型選擇工具和策略。

### 互補關係

```
用戶意圖（模糊）
    │
    ▼
Skill（理解意圖、提供流程指引）
    │
    ▼
Tools（執行具體操作）
    │
    ▼
結果（確定性輸出）
```

Skill 解決「做什麼」，Tool 解決「怎麼做」。Skill 是 orchestrator，Tool 是 executor。

---

## 七、擴展性比較

### 如何新增 Tool

1. 實作 `Tool<InputSchema, Output>` 介面
2. 提供 `inputSchema`、`outputSchema`、`call()` 實作
3. 在工具列表中註冊
4. 配置 permission checking

需要修改 TypeScript 程式碼，需要了解 Tool 系統的底層機制。

### 如何新增 Skill

**Bundled Skill（TypeScript）：**
1. 在 `src/skills/bundled/` 建立文件
2. 實作 `getPromptForCommand` 函數
3. 呼叫 `registerBundledSkill()`
4. 在 `index.ts` 中 import 並呼叫

**User/Project Skill（Markdown）：**
1. 建立 `~/.claude/skills/<name>/SKILL.md`
2. 寫 frontmatter（`allowed-tools`, `when_to_use` 等）
3. 寫 prompt 內容

**Skill 的門檻遠低於 Tool**，普通用戶可以用 `/skillify` 指令從 session 中直接生成 skill。

---

## 八、Skill 系統的三個獨特能力

### 8.1 技能遞迴（Skill Calling Skill）

技能可以呼叫其他技能：

```
# batch.ts WORKER_INSTRUCTIONS
After you finish implementing the change:
1. Invoke the Skill tool with skill: "simplify" to review and clean up your changes.
```

batch 技能產生的 worker agents 被指示執行 simplify 技能，形成兩層技能組合。

### 8.2 技能 + Agent 工具組合

技能可以編排多個 AgentTool 呼叫：

```
# simplify.ts
Use the AgentTool to launch all three agents concurrently in a single message.
```

技能本身不做具體工作，而是指揮多個 sub-agents 並行工作，最後聚合結果。

### 8.3 技能的自我生成（Skill Generation）

`skillify` 技能本身就是「生成技能的技能」：
- 分析 session 歷史
- 訪談用戶
- 生成 SKILL.md 文件

這是 meta-level 的 skill 設計：系統能夠學習和固化用戶的工作流。

---

## 九、工作流中的分工

| 任務類型 | 應使用 | 原因 |
|---------|--------|------|
| 讀取/寫入文件 | Tool（Read/Write/Edit）| 確定性操作 |
| 執行 shell 命令 | Tool（Bash）| 確定性、需要輸出 |
| 配置 settings.json | Skill（update-config）| 需要知識（hooks 語法、合併規則）|
| 代碼品質審查 | Skill（simplify）| 需要判斷和並行協調 |
| 大規模 migration | Skill（batch）| 需要研究、計劃、並行執行 |
| 鍵盤快捷鍵設定 | Skill（keybindings-help）| 需要知識（可用 context/action 清單）|
| 一次性自定義工作流 | User Skill（SKILL.md）| 封裝領域知識 |
| 底層系統整合 | Tool | 需要直接 API 呼叫 |
