# 02 — Prompt 組裝邏輯分析

> 來源：`src/utils/systemPrompt.ts`、`src/constants/systemPromptSections.ts`、`src/constants/prompts.ts`（`getSystemPrompt` 函式）

---

## 一、核心資料結構

### 1.1 SystemPrompt 型別（`systemPromptType.ts`）

```typescript
export type SystemPrompt = readonly string[] & {
  readonly __brand: 'SystemPrompt'
}

export function asSystemPrompt(value: readonly string[]): SystemPrompt {
  return value as SystemPrompt
}
```

**設計意圖：** 使用 TypeScript 的 Branded Type 模式。`SystemPrompt` 在執行期只是 `string[]`，但型別系統層面強制區分「已組裝的 system prompt」與「任意字串陣列」，防止未經 `asSystemPrompt()` 包裝的字串陣列被傳入需要 SystemPrompt 的地方。

---

### 1.2 SystemPromptSection（`systemPromptSections.ts`）

```typescript
type ComputeFn = () => string | null | Promise<string | null>

type SystemPromptSection = {
  name: string
  compute: ComputeFn
  cacheBreak: boolean
}

export function systemPromptSection(name: string, compute: ComputeFn): SystemPromptSection {
  return { name, compute, cacheBreak: false }
}

export function DANGEROUS_uncachedSystemPromptSection(
  name: string,
  compute: ComputeFn,
  _reason: string,
): SystemPromptSection {
  return { name, compute, cacheBreak: true }
}
```

**兩種 Section 的差異：**

| 類型 | `cacheBreak` | 使用時機 |
|------|-------------|---------|
| `systemPromptSection` | `false` | 大多數 section，計算一次後緩存，直到 `/clear` 或 `/compact` |
| `DANGEROUS_uncachedSystemPromptSection` | `true` | 值會在 turn 間變化的 section，如 MCP 連線狀態 |

**`DANGEROUS_` 前綴設計：** 故意加前綴讓開發者意識到這會破壞 prompt cache，迫使填寫 `_reason` 參數（雖然 runtime 不使用），作為自文件化的機制。

---

### 1.3 Section 緩存機制（`resolveSystemPromptSections`）

```typescript
export async function resolveSystemPromptSections(
  sections: SystemPromptSection[],
): Promise<(string | null)[]> {
  const cache = getSystemPromptSectionCache()

  return Promise.all(
    sections.map(async s => {
      if (!s.cacheBreak && cache.has(s.name)) {
        return cache.get(s.name) ?? null
      }
      const value = await s.compute()
      setSystemPromptSectionCacheEntry(s.name, value)
      return value
    }),
  )
}
```

**緩存邏輯：**
1. 如果 `cacheBreak: false` 且緩存有值 → 直接返回緩存值（跳過重新計算）
2. 否則 → 執行 `compute()` 並存入緩存
3. 所有 section 並行計算（`Promise.all`）

**緩存失效：**
```typescript
export function clearSystemPromptSections(): void {
  clearSystemPromptSectionState()
  clearBetaHeaderLatches()
}
```
在 `/clear` 和 `/compact` 時同時清除 section 緩存和 beta header latches（確保新對話重新評估 AFK/fast-mode 等狀態）。

---

## 二、主組裝函式（`getSystemPrompt`）

```typescript
export async function getSystemPrompt(
  tools: Tools,
  model: string,
  additionalWorkingDirectories?: string[],
  mcpClients?: MCPServerConnection[],
): Promise<string[]> {
  // 1. Simple 模式快速路徑
  if (isEnvTruthy(process.env.CLAUDE_CODE_SIMPLE)) {
    return [
      `You are Claude Code, Anthropic's official CLI for Claude.\n\nCWD: ${getCwd()}\nDate: ${getSessionStartDate()}`,
    ]
  }

  // 2. 並行計算初始資訊
  const [skillToolCommands, outputStyleConfig, envInfo] = await Promise.all([
    getSkillToolCommands(cwd),
    getOutputStyleConfig(),
    computeSimpleEnvInfo(model, additionalWorkingDirectories),
  ])

  const settings = getInitialSettings()
  const enabledTools = new Set(tools.map(_ => _.name))

  // 3. Proactive 模式特殊路徑
  if ((feature('PROACTIVE') || feature('KAIROS')) && proactiveModule?.isProactiveActive()) {
    return [
      `\nYou are an autonomous agent...${CYBER_RISK_INSTRUCTION}`,
      getSystemRemindersSection(),
      await loadMemoryPrompt(),
      envInfo,
      getLanguageSection(settings.language),
      isMcpInstructionsDeltaEnabled() ? null : getMcpInstructionsSection(mcpClients),
      getScratchpadInstructions(),
      getFunctionResultClearingSection(model),
      SUMMARIZE_TOOL_RESULTS_SECTION,
      getProactiveSection(),
    ].filter(s => s !== null)
  }

  // 4. 動態 section 定義
  const dynamicSections = [
    systemPromptSection('session_guidance', () =>
      getSessionSpecificGuidanceSection(enabledTools, skillToolCommands),
    ),
    systemPromptSection('memory', () => loadMemoryPrompt()),
    systemPromptSection('ant_model_override', () => getAntModelOverrideSection()),
    systemPromptSection('env_info_simple', () =>
      computeSimpleEnvInfo(model, additionalWorkingDirectories),
    ),
    systemPromptSection('language', () => getLanguageSection(settings.language)),
    systemPromptSection('output_style', () => getOutputStyleSection(outputStyleConfig)),
    DANGEROUS_uncachedSystemPromptSection(
      'mcp_instructions',
      () => isMcpInstructionsDeltaEnabled() ? null : getMcpInstructionsSection(mcpClients),
      'MCP servers connect/disconnect between turns',
    ),
    systemPromptSection('scratchpad', () => getScratchpadInstructions()),
    systemPromptSection('frc', () => getFunctionResultClearingSection(model)),
    systemPromptSection('summarize_tool_results', () => SUMMARIZE_TOOL_RESULTS_SECTION),
    // ANT-only: 數值長度錨點
    ...(process.env.USER_TYPE === 'ant'
      ? [systemPromptSection('numeric_length_anchors', () =>
          'Length limits: keep text between tool calls to ≤25 words. Keep final responses to ≤100 words unless the task requires more detail.',
        )]
      : []),
    // TOKEN_BUDGET feature flag
    ...(feature('TOKEN_BUDGET')
      ? [systemPromptSection('token_budget', () =>
          'When the user specifies a token target (e.g., "+500k", "spend 2M tokens")...',
        )]
      : []),
    // KAIROS/KAIROS_BRIEF feature flag
    ...(feature('KAIROS') || feature('KAIROS_BRIEF')
      ? [systemPromptSection('brief', () => getBriefSection())]
      : []),
  ]

  // 5. 並行解析動態 sections
  const resolvedDynamicSections = await resolveSystemPromptSections(dynamicSections)

  // 6. 組裝最終陣列
  return [
    // --- 靜態部分（可緩存）---
    getSimpleIntroSection(outputStyleConfig),
    getSimpleSystemSection(),
    outputStyleConfig === null || outputStyleConfig.keepCodingInstructions === true
      ? getSimpleDoingTasksSection()
      : null,
    getActionsSection(),
    getUsingYourToolsSection(enabledTools),
    getSimpleToneAndStyleSection(),
    getOutputEfficiencySection(),
    // === 邊界標記 ===
    ...(shouldUseGlobalCacheScope() ? [SYSTEM_PROMPT_DYNAMIC_BOUNDARY] : []),
    // --- 動態部分（Registry 管理）---
    ...resolvedDynamicSections,
  ].filter(s => s !== null)
}
```

---

## 三、靜態/動態邊界設計

### 邊界標記常數

```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```

**用途：** 告知快取系統哪些 prompt 內容可以跨組織（cross-org）快取。邊界前的靜態內容使用 `scope: 'global'` 緩存，邊界後的動態內容包含用戶/Session 特定資訊，不快取。

**程式碼注釋：**
```
// WARNING: Do not remove or reorder this marker without updating cache logic in:
// - src/utils/api.ts (splitSysPromptPrefix)
// - src/services/api/claude.ts (buildSystemPromptBlocks)
```

### 為何靜態部分可全局快取？

靜態部分的所有函式都不依賴：
- 當前工作目錄
- 用戶 session 資訊
- 啟用的工具集合（除了 `getUsingYourToolsSection`，但它有獨立分析）

而動態部分包含：`session_guidance`（依賴 `enabledTools`）、`memory`（用戶私有）、`env_info_simple`（含 cwd）、`language`（用戶設定）等。

---

## 四、有效系統提示詞組裝（`buildEffectiveSystemPrompt`）

這是更高層次的組裝函式，決定「使用哪個 prompt」：

```typescript
export function buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  toolUseContext,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt,
  overrideSystemPrompt,
}: {...}): SystemPrompt {
  // 優先級 0: Override（完全覆蓋）
  if (overrideSystemPrompt) {
    return asSystemPrompt([overrideSystemPrompt])
  }

  // 優先級 1: Coordinator 模式
  if (
    feature('COORDINATOR_MODE') &&
    isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE) &&
    !mainThreadAgentDefinition
  ) {
    const { getCoordinatorSystemPrompt } = require('../coordinator/coordinatorMode.js')
    return asSystemPrompt([
      getCoordinatorSystemPrompt(),
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ])
  }

  // 取得 Agent 的 system prompt（若有定義）
  const agentSystemPrompt = mainThreadAgentDefinition
    ? isBuiltInAgent(mainThreadAgentDefinition)
      ? mainThreadAgentDefinition.getSystemPrompt({ toolUseContext })
      : mainThreadAgentDefinition.getSystemPrompt()
    : undefined

  // 優先級 2a: Proactive 模式 + Agent → 附加到 default prompt
  if (agentSystemPrompt && (feature('PROACTIVE') || feature('KAIROS')) && isProactiveActive()) {
    return asSystemPrompt([
      ...defaultSystemPrompt,
      `\n# Custom Agent Instructions\n${agentSystemPrompt}`,
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ])
  }

  // 優先級 2b/3/4: Agent > Custom > Default，再加 appendSystemPrompt
  return asSystemPrompt([
    ...(agentSystemPrompt
      ? [agentSystemPrompt]
      : customSystemPrompt
        ? [customSystemPrompt]
        : defaultSystemPrompt),
    ...(appendSystemPrompt ? [appendSystemPrompt] : []),
  ])
}
```

### 完整優先級表

| 優先級 | 條件 | 使用的 Prompt |
|--------|------|--------------|
| 0 | `overrideSystemPrompt` 存在 | 僅使用 override，完全替換 |
| 1 | `COORDINATOR_MODE` feature + env | coordinator prompt + appendSystemPrompt |
| 2a | proactive 模式 + agent 定義 | default + agent（附加模式） |
| 2b | 有 agent 定義（非 proactive）| agent prompt 替換 default |
| 3 | 有 `--system-prompt` | custom prompt 替換 default |
| 4 | 預設 | default system prompt |
| +∞ | 所有非 override 情境 | 最後附加 appendSystemPrompt |

**關鍵設計：** Proactive 模式下 agent prompt 是「附加」（append）而非「替換」（replace），因為 proactive 的基礎 prompt 已經很精簡，agent 只需在上面補充領域特定行為。非 proactive 模式則 agent 完全替換 default。

---

## 五、條件注入的維度

系統提示詞中有多個維度的條件注入：

### 5.1 Feature Flags（編譯期死程式碼消除）

```typescript
const getCachedMCConfigForFRC = feature('CACHED_MICROCOMPACT') ? require('...') : null
const proactiveModule = feature('PROACTIVE') || feature('KAIROS') ? require('...') : null
const BRIEF_PROACTIVE_SECTION = feature('KAIROS') || feature('KAIROS_BRIEF') ? require('...') : null
const DISCOVER_SKILLS_TOOL_NAME = feature('EXPERIMENTAL_SKILL_SEARCH') ? require('...') : null
```

使用 `bun:bundle` 的 `feature()` 函式進行編譯期 dead code elimination（DCE）。非 ant 構建中，`feature('PROACTIVE')` 等永遠是 `false`，整個分支在 bundle 時被移除。

### 5.2 環境變數（執行期）

| 環境變數 | 作用 |
|---------|------|
| `process.env.USER_TYPE === 'ant'` | ANT 員工特殊指令 |
| `CLAUDE_CODE_SIMPLE` | 極簡 prompt 模式 |
| `CLAUDE_CODE_COORDINATOR_MODE` | Coordinator 模式 |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | Attribution header |

### 5.3 工具集合（執行期）

```typescript
const enabledTools = new Set(tools.map(_ => _.name))
const hasAskUserQuestionTool = enabledTools.has(ASK_USER_QUESTION_TOOL_NAME)
const hasSkills = skillToolCommands.length > 0 && enabledTools.has(SKILL_TOOL_NAME)
const hasAgentTool = enabledTools.has(AGENT_TOOL_NAME)
```

根據當前工具集動態生成 Session-specific guidance。

### 5.4 用戶設定（執行期）

- `settings.language` → `getLanguageSection()`
- `outputStyleConfig` → 修改 intro section 和是否顯示 coding instructions
- `outputStyleConfig.keepCodingInstructions` → 是否保留 `getSimpleDoingTasksSection()`

---

## 六、MCP 指令整合

```typescript
export function getMcpInstructions(mcpClients: MCPServerConnection[]): string | null {
  const connectedClients = mcpClients.filter(
    (client): client is ConnectedMCPServer => client.type === 'connected',
  )
  const clientsWithInstructions = connectedClients.filter(client => client.instructions)

  if (clientsWithInstructions.length === 0) return null

  const instructionBlocks = clientsWithInstructions
    .map(client => `## ${client.name}\n${client.instructions}`)
    .join('\n\n')

  return `# MCP Server Instructions\n\n...\n\n${instructionBlocks}`
}
```

**`DANGEROUS_uncachedSystemPromptSection` 使用原因：**
MCP 伺服器可以在 turn 之間連接/斷開，所以 MCP 指令段必須每次重新計算（不快取）。

**MCP Instructions Delta（`isMcpInstructionsDeltaEnabled()`）：**
當啟用時，MCP 指令透過「持久化的 `mcp_instructions_delta` attachments」傳遞，而非每次重新計算。這避免了晚連接的 MCP 伺服器破壞 prompt cache。

---

## 七、Session-Specific Guidance 的條件複雜性

```typescript
function getSessionSpecificGuidanceSection(
  enabledTools: Set<string>,
  skillToolCommands: Command[],
): string | null {
  // ...
  // Verification Agent 合約（ANT-ONLY A/B 測試）
  hasAgentTool &&
  feature('VERIFICATION_AGENT') &&
  getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', false)
    ? `The contract: when non-trivial implementation happens on your turn, independent adversarial verification must happen before you report completion...`
    : null,
}
```

這段中的 Verification Agent 有三重條件：
1. `hasAgentTool`：工具可用
2. `feature('VERIFICATION_AGENT')`：編譯期 feature flag
3. `getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', false)`：GrowthBook 遠端 A/B 測試（預設 false，外部不啟用）

---

## 八、`getSessionSpecificGuidanceSection` 在 Dynamic Boundary 之後的原因

```typescript
/**
 * Session-variant guidance that would fragment the cacheScope:'global'
 * prefix if placed before SYSTEM_PROMPT_DYNAMIC_BOUNDARY. Each conditional
 * here is a runtime bit that would otherwise multiply the Blake2b prefix
 * hash variants (2^N). See PR #24490, #24171 for the same bug class.
 */
function getSessionSpecificGuidanceSection(...) { ... }
```

這段程式碼注釋說明了一個關鍵的效能考量：如果把這些條件判斷（`hasAskUserQuestionTool`、`isForkSubagentEnabled()` 等）放到靜態部分，每個 boolean 條件都會產生 2 個不同的 prompt 前綴 hash，N 個條件就有 2^N 個變體，大幅降低 cache hit rate。所以這些條件必須放在 Dynamic Boundary 之後。

---

## 九、組裝流程時序圖

```
getSystemPrompt()
├── [並行] getSkillToolCommands() + getOutputStyleConfig() + computeSimpleEnvInfo()
├── [條件] CLAUDE_CODE_SIMPLE → 返回簡單版本
├── [條件] PROACTIVE/KAIROS → 返回 proactive 版本
├── 定義 dynamicSections 陣列（包含所有 section 定義）
├── [並行] resolveSystemPromptSections(dynamicSections)
│   ├── 從 cache 取 non-cacheBreak sections
│   └── 重新計算 cacheBreak sections
└── 組裝最終陣列：
    [靜態 sections] + [BOUNDARY_MARKER] + [動態 sections]
    ↓
    .filter(s => s !== null)
    → string[]
```
