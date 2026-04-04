# MagicDocs 動態文檔系統

## 一、系統定位

MagicDocs 是一個針對**用戶 repo 內的特定文件**自動更新的機制。與 Auto Memory（記憶系統）和 Session Memory（session 快照）不同，MagicDocs 維護的是用戶專案中的文件文件，這些文件可以被提交到 git、團隊共享。

**目前僅限 Anthropic 內部用戶**（`process.env.USER_TYPE === 'ant'`）。

## 二、觸發條件：Magic Doc 標頭

任何文件只需在第一行加入：
```markdown
# MAGIC DOC: [title]
_可選的 italic 指令說明（緊接在標頭後）_
```

當 FileReadTool 讀取到此格式的文件，即自動進入追蹤清單。

```typescript
const MAGIC_DOC_HEADER_PATTERN = /^#\s*MAGIC\s+DOC:\s*(.+)$/im
const ITALICS_PATTERN = /^[_*](.+?)[_*]\s*$/m
```

```typescript
export function detectMagicDocHeader(
  content: string,
): { title: string; instructions?: string } | null {
  // 1. 匹配 MAGIC DOC: 標頭
  // 2. 查找緊隨其後的 italic 行（允許一個空白行）
  // 3. 若有 italic → instructions（文件特定的更新指令）
}
```

## 三、追蹤機制

```typescript
const trackedMagicDocs = new Map<string, MagicDocInfo>()

type MagicDocInfo = {
  path: string
}
```

```typescript
export function registerMagicDoc(filePath: string): void {
  if (!trackedMagicDocs.has(filePath)) {
    trackedMagicDocs.set(filePath, { path: filePath })
  }
}
```

每個文件路徑只追蹤一次（不重複），但更新時重新讀取最新內容。

## 四、初始化與 Hook 註冊

```typescript
export async function initMagicDocs(): Promise<void> {
  if (process.env.USER_TYPE === 'ant') {
    registerFileReadListener((filePath: string, content: string) => {
      const result = detectMagicDocHeader(content)
      if (result) {
        registerMagicDoc(filePath)
      }
    })
    registerPostSamplingHook(updateMagicDocs)
  }
}
```

`registerFileReadListener`：FileReadTool 每次讀取文件後回呼，自動偵測並追蹤 Magic Doc。

## 五、更新時機

```typescript
const updateMagicDocs = sequential(async function (context: REPLHookContext): Promise<void> {
  // 只在主 REPL 線程運行
  if (querySource !== 'repl_main_thread') return

  // 只在對話 idle（最後一輪無工具呼叫）時更新
  const hasToolCalls = hasToolCallsInLastAssistantTurn(messages)
  if (hasToolCalls) return

  for (const docInfo of Array.from(trackedMagicDocs.values())) {
    await updateMagicDoc(docInfo, context)
  }
})
```

`sequential()` 包裝確保多個 Magic Doc 依序更新，不並行（避免競態）。

## 六、更新執行流程

```typescript
async function updateMagicDoc(docInfo, context): Promise<void> {
  // 1. 複製 FileStateCache（隔離，讓 FileReadTool 不返回 file_unchanged stub）
  const clonedReadFileState = cloneFileStateCache(toolUseContext.readFileState)
  clonedReadFileState.delete(docInfo.path)

  // 2. 重新讀取文件（偵測標頭是否仍存在）
  const result = await FileReadTool.call({ file_path: docInfo.path }, clonedToolUseContext)

  // 3. 重新偵測標頭（文件可能被修改移除標頭）
  const detected = detectMagicDocHeader(currentDoc)
  if (!detected) {
    trackedMagicDocs.delete(docInfo.path)  // 不再是 Magic Doc，移除追蹤
    return
  }

  // 4. 建立更新 prompt（含最新 title 和 instructions）
  const userPrompt = await buildMagicDocsUpdatePrompt(
    currentDoc, docInfo.path, detected.title, detected.instructions
  )

  // 5. 執行 runAgent（Magic Docs 使用 runAgent 而非 runForkedAgent）
  for await (const _message of runAgent({
    agentDefinition: getMagicDocsAgent(),  // 只允許 Edit 工具
    forkContextMessages: messages,
    override: { systemPrompt, userContext, systemContext },
    ...
  })) {}
}
```

**注意**：Magic Docs 使用 `runAgent` + `forkContextMessages`（不是 `runForkedAgent`），因為它需要使用 `runAgent` 的特定功能。

## 七、工具限制

```typescript
function getMagicDocsAgent(): BuiltInAgentDefinition {
  return {
    agentType: 'magic-docs',
    tools: [FILE_EDIT_TOOL_NAME],  // 只允許 Edit
    model: 'sonnet',
    ...
  }
}

const canUseTool = async (tool, input) => {
  if (tool.name === FILE_EDIT_TOOL_NAME && filePath === docInfo.path) {
    return allow
  }
  return deny(`only ${FILE_EDIT_TOOL_NAME} is allowed for ${docInfo.path}`)
}
```

比 Session Memory 更嚴格：只允許 Edit 特定文件。

## 八、更新 Prompt 哲學（getUpdatePromptTemplate）

```
DOCUMENTATION PHILOSOPHY - READ CAREFULLY:
- BE TERSE. High signal only. No filler words or unnecessary elaboration.
- Documentation is for OVERVIEWS, ARCHITECTURE, and ENTRY POINTS - not detailed code walkthroughs
- Do NOT duplicate information that's already obvious from reading the source code
- Focus on: WHY things exist, HOW components connect, WHERE to start reading, WHAT patterns are used
- Skip: detailed implementation steps, exhaustive API docs, play-by-play narratives
```

**What TO document**：
- 高層架構和系統設計
- 非顯而易見的模式、慣例、gotchas
- 關鍵入口點
- 重要設計決策的理由
- 關鍵依賴或整合點

**What NOT to document**：
- 從程式碼本身顯而易見的東西
- 函數/參數的詳盡清單
- 逐步實作細節
- 已在 CLAUDE.md 或其他文件中有的資訊

## 九、文件特定指令（Custom Instructions）

```markdown
# MAGIC DOC: My Architecture Overview
_Focus on external API integrations and the event flow between services_
```

Italic 行的內容成為「文件特定更新指令」，優先於一般規則：

```typescript
const customInstructions = instructions
  ? `DOCUMENT-SPECIFIC UPDATE INSTRUCTIONS:
The document author has provided specific instructions...
"${instructions}"
These instructions take priority over the general rules below.`
  : ''
```

## 十、自訂 Prompt 支援

可在 `~/.claude/magic-docs/prompt.md` 放置自訂 prompt，使用 `{{variable}}` 語法：
```
{{docContents}}        — 文件當前內容
{{docPath}}            — 文件路徑
{{docTitle}}           — 文件標題
{{customInstructions}} — 文件特定指令（已格式化）
```

## 十一、核心設計原則

1. **狀態即時性（Keep CURRENT）**：維護當前狀態，而非變更日誌
   - 在原地更新資訊，不追加「Previously...」或「Updated to...」
   - 刪除不再相關的內容
   - 修正錯誤（錯字、格式、過時資訊）

2. **標頭不可變**：`# MAGIC DOC: {title}` 必須原樣保留，這是 Magic Doc 的識別標誌

3. **只在有實質更新時才執行**：「If there's nothing substantial to add, simply respond with a brief explanation and do not call any tools」

4. **隔離操作**：複製 FileStateCache 確保讀取最新內容，不被 dedup cache 影響
