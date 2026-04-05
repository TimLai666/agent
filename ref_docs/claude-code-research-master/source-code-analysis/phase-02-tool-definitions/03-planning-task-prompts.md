# 03 — 規劃/任務工具 Prompt 集

> 涵蓋：EnterPlanMode、ExitPlanMode、TaskCreate、TaskUpdate、TaskList、TaskGet、TaskStop、TodoWrite

---

## 1. EnterPlanModeTool（EnterPlanMode）

**檔案**：`src/tools/EnterPlanModeTool/prompt.ts`（170 行）
**動態選擇**：`USER_TYPE === 'ant'` 用 `getEnterPlanModeToolPromptAnt()`，否則 `getEnterPlanModeToolPromptExternal()`

---

### Prompt — 外部使用者版

```
Use this tool proactively when you're about to start a non-trivial implementation task. Getting user
sign-off on your approach before writing code prevents wasted effort and ensures alignment.

## When to Use This Tool

Prefer using EnterPlanMode for implementation tasks unless they're simple. Use it when ANY of these
conditions apply:

1. New Feature Implementation: Adding meaningful new functionality
   - Example: "Add a logout button" — where should it go? What happens on click?
   - Example: "Add form validation" — what rules? What error messages?

2. Multiple Valid Approaches: The task can be solved in several different ways
   - Example: "Add caching to the API" — Redis, in-memory, file-based, etc.

3. Code Modifications: Changes that affect existing behavior or structure

4. Architectural Decisions: Choosing between patterns or technologies

5. Multi-File Changes: The task will likely touch more than 2-3 files

6. Unclear Requirements: You need to explore before understanding the full scope

7. User Preferences Matter: If you would use AskUserQuestion to clarify, use EnterPlanMode instead

## When NOT to Use This Tool

Only skip EnterPlanMode for simple tasks:
- Single-line or few-line fixes (typos, obvious bugs, small tweaks)
- Adding a single function with clear requirements
- Tasks where the user has given very specific, detailed instructions
- Pure research/exploration tasks (use the Agent tool with explore agent instead)

## What Happens in Plan Mode [omitted if isPlanModeInterviewPhaseEnabled()]

In plan mode, you'll:
1. Thoroughly explore the codebase using Glob, Grep, and Read tools
2. Understand existing patterns and architecture
3. Design an implementation approach
4. Present your plan to the user for approval
5. Use AskUserQuestion if you need to clarify approaches
6. Exit plan mode with ExitPlanMode when ready to implement

## Important Notes

- This tool REQUIRES user approval — they must consent to entering plan mode
- If unsure whether to use it, err on the side of planning
- Users appreciate being consulted before significant changes are made to their codebase
```

### Prompt — ant 使用者版（更嚴格的閾值）

```
Use this tool when a task has genuine ambiguity about the right approach and getting user input before
coding would prevent significant rework.

## When to Use This Tool

Plan mode is valuable when the implementation approach is genuinely unclear. Use it when:

1. Significant Architectural Ambiguity: Multiple reasonable approaches exist and the choice meaningfully
   affects the codebase

2. Unclear Requirements: You need to explore and clarify before you can make progress

3. High-Impact Restructuring: The task will significantly restructure existing code

## When NOT to Use This Tool

Skip plan mode when you can reasonably infer the right approach:
- The task is straightforward even if it touches multiple files
- The user's request is specific enough that the implementation path is clear
- Adding a feature with an obvious implementation pattern
- Bug fixes where the fix is clear once you understand the bug
- Research/exploration tasks (use Agent tool instead)
- The user says "can we work on X" or "let's do X" — just get started

When in doubt, prefer starting work and using AskUserQuestion for specific questions.
```

### 比較分析

| 維度 | 外部版 | ant 版 |
|---|---|---|
| 觸發門檻 | 任何非簡單任務（7 條觸發規則） | 真正模糊不清時才用 |
| 多檔案任務 | 觸發（>2-3 檔） | **不觸發** |
| 用戶說「讓我們做 X」 | 無說明 | 直接開始做，不進計畫模式 |
| 預設態度 | 「有疑問就計畫」 | 「有疑問就詢問，不要全面計畫」|

---

## 2. ExitPlanModeTool（ExitPlanMode）

**檔案**：`src/tools/ExitPlanModeTool/prompt.ts`（29 行）

### Prompt 原文（`EXIT_PLAN_MODE_V2_TOOL_PROMPT`）

```
Use this tool when you are in plan mode and have finished writing your plan to the plan file and are
ready for user approval.

## How This Tool Works
- You should have already written your plan to the plan file specified in the plan mode system message
- This tool does NOT take the plan content as a parameter — it will read the plan from the file you wrote
- This tool simply signals that you're done planning and ready for the user to review and approve
- The user will see the contents of your plan file when they review it

## When to Use This Tool
IMPORTANT: Only use this tool when the task requires planning the implementation steps of a task that
requires writing code. For research tasks where you're gathering information, searching files, reading
files or in general trying to understand the codebase — do NOT use this tool.

## Before Using This Tool
Ensure your plan is complete and unambiguous:
- If you have unresolved questions, use AskUserQuestion first (in earlier phases)
- Once your plan is finalized, use THIS tool to request approval

Important: Do NOT use AskUserQuestion to ask "Is this plan okay?" — that's exactly what THIS tool does.
ExitPlanMode inherently requests user approval of your plan.

## Examples

1. "Search for and understand the implementation of vim mode" — Do NOT use (research only)
2. "Help me implement yank mode for vim" — USE after planning implementation steps
3. "Add a new feature to handle user authentication" — use AskUserQuestion first if auth method unclear,
   then use ExitPlanMode after clarifying
```

### 分析

| 特點 | 說明 |
|---|---|
| 間接模式（v2） | 不接受 plan content 參數，讀取預先寫好的 plan file |
| 研究任務例外 | 只用於需要寫程式碼的計畫，純研究禁止使用 |
| 與 AskUserQuestion 邊界 | ExitPlanMode 隱含「請用戶審批」；AskUserQuestion 用於澄清需求 |

---

## 3. TaskCreateTool（TaskCreate）

**檔案**：`src/tools/TaskCreateTool/prompt.ts`（56 行）

### Prompt 原文（`getPrompt()`，含 swarms 模式變化）

```
Use this tool to create a structured task list for your current coding session. This helps you track
progress, organize complex tasks, and demonstrate thoroughness to the user.

## When to Use This Tool

Use this tool proactively in these scenarios:
- Complex multi-step tasks — When a task requires 3 or more distinct steps
- Non-trivial and complex tasks [and potentially assigned to teammates — swarms mode]
- Plan mode — When using plan mode, create a task list to track the work
- User explicitly requests todo list
- User provides multiple tasks (numbered or comma-separated)
- After receiving new instructions — Immediately capture user requirements as tasks
- When you start working on a task — Mark it as in_progress BEFORE beginning work
- After completing a task — Mark it as completed and add any new follow-up tasks

## When NOT to Use This Tool

Skip using this tool when:
- There is only a single, straightforward task
- The task is trivial and tracking it provides no organizational benefit
- The task can be completed in less than 3 trivial steps
- The task is purely conversational or informational

NOTE: do not use this tool if there is only one trivial task to do.

## Task Fields

- subject: A brief, actionable title in imperative form (e.g., "Fix authentication bug in login flow")
- description: What needs to be done
- activeForm (optional): Present continuous form shown in the spinner when the task is in_progress

All tasks are created with status `pending`.

## Tips

- Create tasks with clear, specific subjects that describe the outcome
- After creating tasks, use TaskUpdate to set up dependencies (blocks/blockedBy) if needed
- [swarms] Include enough detail for another agent to understand and complete the task
- [swarms] New tasks start with no owner — use TaskUpdate with `owner` to assign
- Check TaskList first to avoid creating duplicate tasks
```

---

## 4. TaskUpdateTool（TaskUpdate）

**檔案**：`src/tools/TaskUpdateTool/prompt.ts`（77 行）

### Prompt 原文（`PROMPT`）

```
Use this tool to update a task in the task list.

## When to Use This Tool

Mark tasks as resolved:
- When you have completed the work described in a task
- IMPORTANT: Always mark your assigned tasks as resolved when you finish them
- After resolving, call TaskList to find your next task

- ONLY mark a task as completed when you have FULLY accomplished it
- If you encounter errors, blockers, or cannot finish, keep the task as in_progress
- When blocked, create a new task describing what needs to be resolved
- Never mark a task as completed if:
  - Tests are failing
  - Implementation is partial
  - You encountered unresolved errors
  - You couldn't find necessary files or dependencies

Delete tasks: Setting status to `deleted` permanently removes the task

Update task details: When requirements change or become clearer

## Fields You Can Update

- status: The task status (see Status Workflow below)
- subject: Change the task title (imperative form)
- description: Change the task description
- activeForm: Present continuous form shown in spinner when in_progress
- owner: Change the task owner (agent name)
- metadata: Merge metadata keys (set a key to null to delete it)
- addBlocks: Mark tasks that cannot start until this one completes
- addBlockedBy: Mark tasks that must complete before this one can start

## Status Workflow

Status progresses: `pending` → `in_progress` → `completed`
Use `deleted` to permanently remove a task.

## Staleness

Make sure to read a task's latest state using `TaskGet` before updating it.

## Examples

{"taskId": "1", "status": "in_progress"}
{"taskId": "1", "status": "completed"}
{"taskId": "1", "status": "deleted"}
{"taskId": "1", "owner": "my-name"}
{"taskId": "2", "addBlockedBy": ["1"]}
```

---

## 5. TaskListTool（TaskList）

**檔案**：`src/tools/TaskListTool/prompt.ts`（49 行）

### Prompt 原文（`getPrompt()`，含 swarms 模式變化）

```
Use this tool to list all tasks in the task list.

## When to Use This Tool

- To see what tasks are available to work on (status: 'pending', no owner, not blocked)
- To check overall progress on the project
- To find tasks that are blocked and need dependencies resolved
- [swarms] Before assigning tasks to teammates, to see what's available
- After completing a task, to check for newly unblocked work
- Prefer working on tasks in ID order (lowest ID first)

## Output

Returns a summary of each task:
- id: Task identifier (use with TaskGet, TaskUpdate)
- subject: Brief description of the task
- status: 'pending', 'in_progress', or 'completed'
- owner: Agent ID if assigned, empty if available
- blockedBy: List of open task IDs that must be resolved first

Use TaskGet with a specific task ID to view full details.

## Teammate Workflow [swarms mode only]

When working as a teammate:
1. After completing your current task, call TaskList to find available work
2. Look for tasks with status 'pending', no owner, and empty blockedBy
3. Prefer tasks in ID order (lowest ID first) — earlier tasks often set up context
4. Claim an available task using TaskUpdate (set `owner` to your name)
5. If blocked, focus on unblocking tasks or notify the team lead
```

---

## 6. TaskGetTool（TaskGet）

**檔案**：`src/tools/TaskGetTool/prompt.ts`（24 行）

### Prompt 原文（`PROMPT`）

```
Use this tool to retrieve a task by its ID from the task list.

## When to Use This Tool

- When you need the full description and context before starting work on a task
- To understand task dependencies (what it blocks, what blocks it)
- After being assigned a task, to get complete requirements

## Output

Returns full task details:
- subject: Task title
- description: Detailed requirements and context
- status: 'pending', 'in_progress', or 'completed'
- blocks: Tasks waiting on this one to complete
- blockedBy: Tasks that must complete before this one can start

## Tips

- After fetching a task, verify its blockedBy list is empty before beginning work.
- Use TaskList to see all tasks in summary form.
```

---

## 7. TaskStopTool（TaskStop）

**檔案**：`src/tools/TaskStopTool/prompt.ts`（8 行）

### Prompt 原文（`DESCRIPTION`）

```
- Stops a running background task by its ID
- Takes a task_id parameter identifying the task to stop
- Returns a success or failure status
- Use this tool when you need to terminate a long-running task
```

---

## 8. TodoWriteTool（TodoWrite）

**檔案**：`src/tools/TodoWriteTool/prompt.ts`（184 行）

### Prompt 原文（`PROMPT`）— 節選重要部分

```
Use this tool to create and manage a structured task list for your current coding session.
This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.

## When to Use This Tool

1. Complex multi-step tasks — 3 or more distinct steps
2. Non-trivial and complex tasks — require careful planning
3. User explicitly requests todo list
4. User provides multiple tasks (numbered or comma-separated)
5. After receiving new instructions — Immediately capture user requirements as todos
6. When you start working on a task — Mark it as in_progress BEFORE beginning work. Ideally only ONE
   task as in_progress at a time
7. After completing a task — Mark it as completed and add follow-up tasks discovered during implementation

## When NOT to Use This Tool

1. There is only a single, straightforward task
2. The task is trivial and tracking provides no organizational benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Task States and Management

1. Task States:
   - pending: Task not yet started
   - in_progress: Currently working on (limit to ONE task at a time)
   - completed: Task finished successfully

   IMPORTANT: Task descriptions must have two forms:
   - content: The imperative form (e.g., "Run tests", "Build the project")
   - activeForm: The present continuous form (e.g., "Running tests", "Building the project")

2. Task Management:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Exactly ONE task must be in_progress at any time
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant

3. Task Completion Requirements:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, keep the task as in_progress
   - Never mark a task as completed if:
     - Tests are failing
     - Implementation is partial
     - You encountered unresolved errors
     - You couldn't find necessary files or dependencies

4. Task Breakdown:
   - Always provide both forms: content + activeForm
```

### DESCRIPTION（工具描述，顯示在工具 schema）

```
Update the todo list for the current session. To be used proactively and often to track progress and
pending tasks. Make sure that at least one task is in_progress at all times. Always provide both
content (imperative) and activeForm (present continuous) for each task.
```

---

## 規劃/任務工具整體關係圖

```
EnterPlanMode
  └─ 探索 codebase（Read/Glob/Grep）
  └─ AskUserQuestion（澄清）
  └─ 寫 plan file
  └─ ExitPlanMode（送審）

TaskCreate → TaskList → TaskGet → TaskUpdate（in_progress）
                                    └─ 完成 → TaskUpdate（completed）
                                    └─ 阻塞 → TaskCreate（新阻塞任務）
                                    └─ 停止 → TaskStop

TodoWrite（單一 session 的輕量版，無 team 協調）
```

---

## Task vs TodoWrite 對比

| 維度 | Task 系列 | TodoWrite |
|---|---|---|
| 多 agent 支援 | 是（owner/blockedBy/team 概念） | 否（單 session）|
| 依賴關係 | 有（blocks/blockedBy） | 無 |
| 狀態機 | pending → in_progress → completed / deleted | 同左 |
| 兩種文字格式 | subject（imperative） + activeForm | content + activeForm |
| 何時用 | 多 agent 協作或明確任務追蹤 | 個人複雜 session 快速追蹤 |
