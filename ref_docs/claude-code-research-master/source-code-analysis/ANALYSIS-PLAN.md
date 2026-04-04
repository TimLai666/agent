# Claude Code CLI 原始碼逆向分析 — 完整執行計畫

> 來源：Claude Code v2.1.88 via npm sourcemap 洩漏（2026-03-31）
> 規模：1,884 檔案 / ~92,500 行 TypeScript/TSX
> 目標：產出一套具研究價值的 Harness Engineering 分析報告集

---

## 背景

2026 年 3 月 31 日，Anthropic 的 Claude Code CLI 原始碼透過 npm registry 的 sourcemap 檔案洩漏。這份程式碼完整揭露了當前最先進 AI coding agent 的內部架構，包括：

- 完整的 system prompt 與動態組裝邏輯
- 36 個工具的定義、描述與安全機制
- Agent/Subagent 架構與 coordinator 模式
- 成本追蹤、限流、token 預估等生產級機制
- 未公開功能：KAIROS 主動模式、Capybara 模型族、Buddy AI 寵物、UltraPlan

### 為什麼這很重要

Harness Engineering 是 2026 年 AI Agent 領域最核心的課題。Anthropic 官方定義：

> **Prompt Engineering 是系統的一個輸入；Harness Engineering 是整個系統。**
>
> `Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions`

Claude Code 是目前業界最成熟的 agent harness 實作之一。逆向分析它的原始碼，等於拿到了一份生產級 harness engineering 的完整教材。

---

## Codebase 結構概覽

```
claude-code-source/
├── src/
│   ├── constants/          # 系統常數、prompts、API limits、beta flags
│   ├── tools/              # 36 個工具定義（prompt + 實作 + 安全）
│   │   ├── AgentTool/      #   含 6 個 built-in agent 定義
│   │   ├── BashTool/       #   含 bashSecurity(2592行) + bashPermissions(2621行)
│   │   ├── SkillTool/      #   Skills 系統入口
│   │   └── ...             #   其餘 33 個工具
│   ├── services/           # 核心服務層
│   │   ├── api/            #   Claude API 呼叫層 (claude.ts 3419行)
│   │   ├── compact/        #   Context compaction
│   │   ├── extractMemories/#   自動記憶提取
│   │   ├── SessionMemory/  #   Session 記憶
│   │   ├── MagicDocs/      #   動態文件系統
│   │   ├── tools/          #   工具執行 & 編排
│   │   ├── policyLimits/   #   團隊策略限制
│   │   ├── analytics/      #   遙測分析
│   │   └── autoDream/      #   夢境整合機制
│   ├── coordinator/        # Coordinator 模式（多 agent 協調）
│   ├── skills/bundled/     # 16 個內建 skills
│   ├── memdir/             # 記憶目錄系統
│   ├── tasks/              # 任務系統（Dream/Local/Remote/Teammate）
│   ├── hooks/              # Hook 系統（權限、建議）
│   ├── utils/
│   │   ├── model/          #   模型配置（16 檔）
│   │   ├── permissions/    #   權限系統
│   │   ├── sandbox/        #   沙箱機制
│   │   ├── swarm/          #   Swarm 多 agent 協作
│   │   ├── computerUse/    #   Computer Use 整合
│   │   ├── ultraplan/      #   UltraPlan 遠端規劃
│   │   ├── memory/         #   記憶工具
│   │   └── bash/           #   Bash 解析器 (4436行 parser + 2679行 AST)
│   ├── buddy/              # Buddy AI 寵物系統
│   ├── voice/              # 語音功能
│   ├── remote/             # 遠端執行
│   ├── screens/            # UI 畫面（REPL.tsx 5005行）
│   ├── main.tsx            # 主入口（4683行）
│   └── bootstrap/          # 啟動狀態（state.ts 1758行）
└── vendor/                 # 原生模組原始碼
```

---

## 執行計畫：10 Phase + 1 總覽

### 執行順序與優先級

| 優先級 | Phase | 主題 | 預估價值 |
|--------|-------|------|----------|
| **P0** | 9 | Harness Engineering 全景分析 | ★★★★★ |
| **P0** | 1 | System Prompt Engineering | ★★★★★ |
| **P0** | 10 | 成本與額度運用機制 | ★★★★★ |
| **P1** | 2 | Tool Definitions 全集 | ★★★★★ |
| **P1** | 3 | Agent 架構與 Coordinator | ★★★★★ |
| **P1** | 6 | 安全與權限深度分析 | ★★★★★ |
| **P2** | 4 | Skills 系統 | ★★★★☆ |
| **P2** | 5 | Memory & Context 管理 | ★★★★☆ |
| **P2** | 7 | API 層、模型配置、核心架構 | ★★★★☆ |
| **P3** | 8 | 特殊功能與隱藏彩蛋 | ★★★☆☆ |
| **最後** | 0 | Executive Summary 總覽 | 整合用 |

---

## Phase 9: Harness Engineering 全景分析（P0 最高優先）

> 以 Harness Engineering 框架逆向分析 Claude Code 的完整架構

### Harness 層級對照表

| Harness 層 | codebase 位置 | 分析重點 |
|---|---|---|
| Agent Loop | `main.tsx`, `REPL.tsx`, `services/api/claude.ts` | model call → tool exec → feedback 核心迴圈 |
| System Prompt 組裝 | `constants/prompts.ts`, `systemPromptSections.ts`, `utils/systemPrompt.ts` | 動態組裝、條件注入、section 排序 |
| Tool Orchestration | `services/tools/toolExecution.ts`, `toolOrchestration.ts` | 工具選擇、排程、並行、結果處理 |
| Context Engineering | `services/compact/`, `memdir/`, `utils/messages.ts` | Context window 管理、compaction、記憶提取 |
| Permission & Security | `BashTool/bashSecurity.ts`, `permissions/`, `hooks/toolPermission/` | 多層防禦、sandbox、read-only |
| Subagent Spawning | `AgentTool/`, `coordinator/`, `tasks/` | Agent 生命週期、coordinator、swarm |
| Observability | `services/analytics/`, `diagnosticTracking.ts`, `cost-tracker.ts` | 遙測、成本、frustration signal |
| Multi-session | `memdir/`, `SessionMemory/`, `autoDream/` | 跨 session 記憶、progress log、dream |
| Experimental | `buddy/`, `ultraplan/`, KAIROS, `moreright/` | 未公開功能 |

### 指令

```
以 Harness Engineering 框架分析 Claude Code 的完整架構。

Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions

核心檔案：
- src/main.tsx（Agent Loop 主迴圈）
- src/screens/REPL.tsx（REPL 互動層）
- src/services/api/claude.ts（API 呼叫層）
- src/services/tools/toolExecution.ts + toolOrchestration.ts（工具編排）
- src/utils/messages.ts + messages/systemInit.ts（訊息組裝）
- src/bootstrap/state.ts（啟動狀態）
- src/coordinator/coordinatorMode.ts（協調器模式）
- src/services/analytics/（遙測觀測）
- src/services/diagnosticTracking.ts

報告格式：
1. Harness 架構全景圖（對照 Anthropic 官方 harness 定義）
2. Agent Loop 完整流程逆向分析（model call → tool exec → feedback）
3. Context Engineering 策略（什麼進 context window、什麼順序、何時壓縮）
4. Tool Orchestration 設計模式（選擇、排程、並行、結果注入）
5. Permission Governance 多層架構
6. Observability 與遙測設計（追蹤什麼指標、frustration signal）
7. Multi-session Continuity 機制
8. 與 Anthropic 官方 "Effective Harnesses" 文章的對照分析
9. 可遷移的 Harness Engineering 設計原則提煉

將報告寫入 reports/09-harness-engineering-analysis.md
```

---

## Phase 1: System Prompt Engineering（P0）

> 完整逆向 Claude Code 的系統提示詞工程

### 核心檔案清單

| 檔案 | 行數 | 內容 |
|------|------|------|
| `src/constants/prompts.ts` | 914 | 主系統提示詞全文 |
| `src/constants/systemPromptSections.ts` | 68 | Prompt section 定義 |
| `src/constants/system.ts` | 95 | 系統常數 |
| `src/utils/systemPrompt.ts` | 123 | System prompt 組裝邏輯 |
| `src/utils/systemPromptType.ts` | — | Prompt 類型定義 |
| `src/utils/messages/systemInit.ts` | 96 | 系統初始化訊息 |
| `src/utils/messages.ts` | 5512 | 訊息處理（focus on system message） |
| `src/constants/cyberRiskInstruction.ts` | 24 | 網路安全風險指令 |
| `src/services/compact/prompt.ts` | 374 | Compaction prompt |

### 指令

```
讀取以下檔案並產出完整分析報告（繁體中文），解析每個 prompt section 的用途、
設計意圖、組裝邏輯：

核心檔案：
- src/constants/prompts.ts
- src/constants/systemPromptSections.ts
- src/constants/system.ts
- src/utils/systemPrompt.ts
- src/utils/systemPromptType.ts
- src/utils/messages/systemInit.ts
- src/utils/messages.ts（focus on system message assembly 部分）
- src/constants/cyberRiskInstruction.ts
- src/services/compact/prompt.ts

報告格式：
1. System Prompt 完整結構圖（哪些 section 按什麼順序組裝）
2. 每個 prompt section 的原文 + 中文解析
3. Prompt 組裝邏輯（條件判斷、動態注入機制）
4. Context window 管理策略（compaction prompt 分析）
5. 安全指令分析（cyber risk, safety valve）
6. 設計模式與可學習的 prompt engineering 技巧

將報告寫入 reports/01-system-prompt-engineering.md
```

---

## Phase 10: 成本與額度運用機制（P0）

> 完整逆向分析 Claude Code 的成本控制、限流、token 經濟學

### 核心檔案清單

| 檔案 | 內容 |
|------|------|
| `src/cost-tracker.ts` | 成本追蹤核心 |
| `src/costHook.ts` | 成本 hook |
| `src/services/rateLimitMessages.ts` | 限流訊息 |
| `src/services/rateLimitMocking.ts` | 限流模擬 |
| `src/services/claudeAiLimits.ts` | Claude AI 額度限制 |
| `src/services/claudeAiLimitsHook.ts` | 額度 hook |
| `src/services/mockRateLimits.ts` | Mock 限流 |
| `src/services/policyLimits/` | 團隊策略限制（全目錄） |
| `src/services/tokenEstimation.ts` | Token 預估 |
| `src/services/api/promptCacheBreakDetection.ts` | Prompt cache break 偵測 |
| `src/services/api/claude.ts` | API 層（focus on caching & cost） |
| `src/constants/apiLimits.ts` | API 限制常數 |
| `src/constants/toolLimits.ts` | 工具限制常數 |
| `src/utils/model/configs.ts` | 模型配置 |
| `src/utils/model/modelCapabilities.ts` | 模型能力定義 |
| `src/commands/cost/` | /cost 命令 |
| `src/commands/usage/` | /usage 命令 |
| `src/commands/stats/` | /stats 命令 |
| `src/services/compact/prompt.ts` | Compaction 作為成本節約手段 |

### 指令

```
完整逆向分析 Claude Code 的成本控制與限流架構。

核心檔案：
- src/cost-tracker.ts
- src/costHook.ts
- src/services/rateLimitMessages.ts
- src/services/rateLimitMocking.ts
- src/services/claudeAiLimits.ts
- src/services/claudeAiLimitsHook.ts
- src/services/mockRateLimits.ts
- src/services/policyLimits/ 全目錄
- src/services/tokenEstimation.ts
- src/services/api/promptCacheBreakDetection.ts
- src/services/api/claude.ts（focus on caching & cost sections）
- src/constants/apiLimits.ts
- src/constants/toolLimits.ts
- src/utils/model/configs.ts + modelCapabilities.ts
- src/commands/cost/ + commands/usage/ + commands/stats/
- src/services/compact/prompt.ts（compaction as cost saving）

報告格式：
1. 成本控制架構全景圖
2. Cost Envelope 實作（per-task 預算、累計追蹤、超限處理）
3. Rate Limiting 完整機制（token bucket、TPM/RPM、組織 vs 使用者層級）
4. Prompt Caching 策略（cache break detection、快取命中最佳化）
5. Token Estimation 預估邏輯
6. Context Compaction 作為成本節約手段
7. Policy Limits 團隊管控機制
8. Model Selection 與成本的關係（fast mode、降級、model routing）
9. 使用者端成本可見性（/cost, /usage, /stats 命令）
10. 可遷移的 AI Agent 成本工程最佳實踐

將報告寫入 reports/10-cost-quota-mechanisms.md
```

---

## Phase 2: Tool Definitions & Prompt 全集（P1）

### 核心檔案

- `src/tools/*/prompt.ts` — 全部 36 個工具的 prompt
- 重點額外讀取：
  - `src/tools/BashTool/bashSecurity.ts` (2592 行)
  - `src/tools/BashTool/bashPermissions.ts` (2621 行)
  - `src/tools/BashTool/readOnlyValidation.ts` (1990 行)
  - `src/tools/PowerShellTool/prompt.ts` + `pathValidation.ts` (2049 行)
  - `src/tools/AgentTool/` 全目錄
  - `src/tools/SkillTool/` 全目錄
  - `src/constants/tools.ts`
  - `src/constants/toolLimits.ts`
  - `src/services/tools/toolExecution.ts` (1745 行)
  - `src/services/tools/toolOrchestration.ts`

### Tool Prompt 尺寸一覽

| 工具 | Prompt 行數 | 重要性 |
|------|------------|--------|
| BashTool | 369 | ★★★★★ |
| AgentTool | 287 | ★★★★★ |
| SkillTool | 241 | ★★★★☆ |
| TodoWriteTool | 184 | ★★★☆☆ |
| EnterPlanModeTool | 170 | ★★★★☆ |
| PowerShellTool | 145 | ★★★☆☆ |
| ScheduleCronTool | 135 | ★★★☆☆ |
| ToolSearchTool | 121 | ★★★☆☆ |
| TeamCreateTool | 113 | ★★★☆☆ |
| 其餘 27 個 | 3-93 | ★★-★★★ |

### 指令

```
讀取所有 36 個 tool 的 prompt.ts 和主要實作檔，產出完整分析報告：

目標目錄：src/tools/*/prompt.ts（全部）
重點額外讀取：
- src/tools/BashTool/bashSecurity.ts
- src/tools/BashTool/bashPermissions.ts
- src/tools/BashTool/readOnlyValidation.ts
- src/tools/PowerShellTool/prompt.ts + pathValidation.ts
- src/tools/AgentTool/ 全目錄
- src/tools/SkillTool/ 全目錄
- src/constants/tools.ts
- src/constants/toolLimits.ts
- src/services/tools/toolExecution.ts
- src/services/tools/toolOrchestration.ts

報告格式：
1. 工具清單總覽表（名稱、用途、prompt 長度、是否有安全限制）
2. 每個工具的完整 prompt 原文 + 設計分析
3. 工具安全機制深度分析（BashTool 命令過濾、路徑驗證等）
4. 工具編排邏輯（execution, orchestration）
5. 工具間的依賴與互動關係

將報告寫入 reports/02-tool-definitions-complete.md
```

---

## Phase 3: Agent 架構與 Coordinator 系統（P1）

### 核心檔案

| 檔案 | 行數 | 內容 |
|------|------|------|
| `src/tools/AgentTool/prompt.ts` | 287 | Agent dispatch prompt |
| `src/tools/AgentTool/built-in/generalPurposeAgent.ts` | 34 | 通用 agent |
| `src/tools/AgentTool/built-in/exploreAgent.ts` | 83 | 探索 agent |
| `src/tools/AgentTool/built-in/planAgent.ts` | 92 | 規劃 agent |
| `src/tools/AgentTool/built-in/claudeCodeGuideAgent.ts` | 205 | 導覽 agent |
| `src/tools/AgentTool/built-in/verificationAgent.ts` | 152 | 驗證 agent |
| `src/tools/AgentTool/built-in/statuslineSetup.ts` | 144 | 狀態列 agent |
| `src/coordinator/coordinatorMode.ts` | 369 | Coordinator 模式 |
| `src/tools/SendMessageTool/prompt.ts` | 49 | Agent 間通訊 |
| `src/tasks/` | — | Task 系統全目錄 |
| `src/utils/swarm/` | — | Swarm 協作全目錄 |
| `src/services/AgentSummary/` | — | Agent 摘要 |

### 指令

```
讀取 Agent 相關所有檔案，產出完整架構分析：

核心檔案：
- src/tools/AgentTool/prompt.ts
- src/tools/AgentTool/built-in/ 全部 6 個 agent 定義
- src/coordinator/coordinatorMode.ts
- src/tools/SendMessageTool/prompt.ts
- src/tasks/ 全目錄（DreamTask, LocalAgentTask, RemoteAgentTask, InProcessTeammateTask）
- src/utils/swarm/ 全目錄
- src/services/AgentSummary/

報告格式：
1. Agent 系統架構圖
2. 每個 built-in agent 的完整 prompt 原文 + 能力分析
3. Agent 生命週期（spawn → execute → return）
4. Coordinator mode 運作機制
5. Swarm/Teammate 多 agent 協作機制
6. Task 系統與 agent 的關係
7. Agent 間通訊（SendMessage）機制

將報告寫入 reports/03-agent-architecture.md
```

---

## Phase 4: Skills 系統（P2）

### 核心檔案

| Skill | 行數 | 功能 |
|-------|------|------|
| `updateConfig.ts` | 475 | 設定更新 |
| `scheduleRemoteAgents.ts` | 447 | 遠端排程 |
| `keybindings.ts` | 339 | 快捷鍵 |
| `loremIpsum.ts` | 282 | Lorem Ipsum |
| `skillify.ts` | 197 | Skill 化 |
| `claudeApi.ts` | 196 | Claude API |
| `batch.ts` | 124 | 批次處理 |
| `debug.ts` | 103 | 除錯 |
| `loop.ts` | 92 | 迴圈執行 |
| `remember.ts` | 82 | 記憶 |
| `stuck.ts` | 79 | 卡住偵測 |
| 其餘 5 個 | 13-75 | 各功能 |

### 指令

```
讀取 Skills 系統所有檔案：

核心檔案：
- src/tools/SkillTool/prompt.ts + 目錄全部
- src/skills/bundled/ 全部 16 個 skill
- src/utils/skills/ 全目錄
- src/hooks/useSkillsChange.ts

報告格式：
1. Skills 系統架構（載入、執行、權限）
2. 每個 bundled skill 的完整內容與分析
3. Skill 設計模式（如何寫好一個 skill）
4. Skills 與 Tools 的區別和互動

將報告寫入 reports/04-skills-system.md
```

---

## Phase 5: Memory & Context 管理系統（P2）

### 核心檔案

| 模組 | 關鍵檔案 | 內容 |
|------|----------|------|
| memdir | `memdir.ts`(507行), `findRelevantMemories.ts`, `memoryTypes.ts`, `memoryScan.ts` | 記憶目錄系統 |
| compact | `prompt.ts`(374行) | Compaction 策略 |
| extractMemories | `prompts.ts` | 自動記憶提取 prompt |
| SessionMemory | `prompts.ts` | Session 記憶 prompt |
| MagicDocs | `prompts.ts` | 動態文件 prompt |
| teamMemorySync | 全目錄 | 團隊記憶同步 |
| autoDream | `consolidationPrompt.ts`(65行), `autoDream.ts`, `config.ts` | 夢境整合 |
| memory utils | `utils/memory/` | 記憶工具函式 |

### 指令

```
讀取記憶體與 context 管理相關檔案：

核心檔案：
- src/memdir/ 全目錄
- src/services/compact/prompt.ts
- src/services/extractMemories/ 全目錄
- src/services/SessionMemory/ 全目錄
- src/services/MagicDocs/ 全目錄
- src/services/teamMemorySync/ 全目錄
- src/utils/memory/ 全目錄
- src/services/autoDream/ 全目錄

報告格式：
1. Memory 系統架構全景圖
2. Memory 類型與生命週期
3. Context compaction 策略與 prompt
4. Memory extraction 自動化機制
5. Session memory vs Team memory
6. AutoDream / consolidation 機制
7. MagicDocs 動態文檔系統

將報告寫入 reports/05-memory-context-system.md
```

---

## Phase 6: 安全與權限深度分析（P1）

### 核心檔案

| 檔案 | 行數 | 內容 |
|------|------|------|
| `BashTool/bashSecurity.ts` | 2592 | Bash 安全過濾 |
| `BashTool/bashPermissions.ts` | 2621 | Bash 權限判斷 |
| `BashTool/readOnlyValidation.ts` | 1990 | 唯讀驗證 |
| `shell/readOnlyCommandValidation.ts` | 1893 | Shell 唯讀驗證 |
| `PowerShellTool/readOnlyValidation.ts` | 1823 | PS 唯讀驗證 |
| `PowerShellTool/pathValidation.ts` | 2049 | PS 路徑驗證 |
| `utils/permissions/filesystem.ts` | 1777 | 檔案系統權限 |
| `constants/cyberRiskInstruction.ts` | 24 | 網路安全指令 |
| `hooks/toolPermission/` | — | 工具權限 hooks |
| `components/permissions/` | — | 權限 UI 元件 |
| `utils/sandbox/` | — | 沙箱機制 |

### 指令

```
讀取安全機制相關所有檔案：

核心檔案：
- src/tools/BashTool/bashSecurity.ts
- src/tools/BashTool/bashPermissions.ts
- src/tools/BashTool/readOnlyValidation.ts
- src/utils/permissions/ 全目錄
- src/utils/sandbox/ 全目錄
- src/hooks/toolPermission/ 全目錄
- src/components/permissions/ 全目錄
- src/constants/cyberRiskInstruction.ts
- src/utils/shell/readOnlyCommandValidation.ts
- src/tools/PowerShellTool/readOnlyValidation.ts + pathValidation.ts

報告格式：
1. 安全架構總覽（多層防禦模型）
2. Bash 命令安全過濾完整規則集
3. 檔案系統權限模型
4. Sandbox 機制
5. 工具層權限控制
6. 唯讀模式實作
7. 安全相關 prompt 指令

將報告寫入 reports/06-security-permissions.md
```

---

## Phase 7: API 層、模型配置、核心架構（P2）

### 核心檔案

| 檔案 | 行數 | 內容 |
|------|------|------|
| `services/api/claude.ts` | 3419 | API 呼叫核心 |
| `utils/model/configs.ts` | — | 模型配置 |
| `utils/model/modelCapabilities.ts` | — | 模型能力 |
| `utils/model/providers.ts` | — | Provider 支援 |
| `utils/model/bedrock.ts` | — | AWS Bedrock |
| `utils/model/aliases.ts` | — | 模型別名 |
| `utils/model/antModels.ts` | — | Anthropic 模型 |
| `constants/betas.ts` | 52 | Beta features |
| `constants/apiLimits.ts` | 94 | API 限制 |
| `bootstrap/state.ts` | 1758 | 啟動狀態 |
| `main.tsx` | 4683 | 主入口 |
| `entrypoints/` | — | 入口點 |

### 指令

```
讀取 API 和核心架構檔案：

核心檔案：
- src/services/api/claude.ts
- src/utils/model/ 全目錄（16 檔）
- src/constants/betas.ts
- src/constants/apiLimits.ts
- src/bootstrap/state.ts
- src/main.tsx
- src/entrypoints/ 全目錄
- src/cost-tracker.ts
- src/services/rateLimitMessages.ts
- src/services/claudeAiLimits.ts
- src/services/policyLimits/ 全目錄

報告格式：
1. 核心啟動流程（bootstrap → main → REPL）
2. API 呼叫層完整分析（請求組裝、回應處理、streaming）
3. 模型配置與切換邏輯（fast mode、model routing）
4. Beta features 完整清單與分析
5. Provider 支援架構（Anthropic / Bedrock / Vertex）
6. 成本追蹤機制
7. 限流策略

將報告寫入 reports/07-api-model-architecture.md
```

---

## Phase 8: 特殊功能與隱藏彩蛋（P3）

### 已知特殊功能

| 功能 | 位置 | 說明 |
|------|------|------|
| **KAIROS** | feature flags / assistant/ | 主動模式，持續監控並主動行動 |
| **Buddy** | `src/buddy/` | Tamagotchi 風格 AI 寵物，18 物種，稀有度分級 |
| **UltraPlan** | `src/utils/ultraplan/` | 遠端 CCR session 用 Opus 4.6 規劃，上限 30 分鐘 |
| **Capybara** | model configs | 隱藏模型族（capybara / capybara-fast） |
| **Computer Use** | `src/utils/computerUse/` | 螢幕操作整合 |
| **AutoDream** | `src/services/autoDream/` | 夢境整合記憶 |
| **Moreright** | `src/moreright/` | 未知功能 |

### 指令

```
讀取所有特殊/有趣的功能模組：

核心檔案：
- src/buddy/ 全目錄（AI 伴侶系統）
- src/services/autoDream/ 全目錄
- src/utils/computerUse/ 全目錄
- src/utils/ultraplan/ 全目錄
- src/voice/ 全目錄
- src/moreright/ 全目錄
- src/utils/teleport/ 全目錄
- src/utils/deepLink/ 全目錄
- src/commands/good-claude/
- src/commands/stickers/
- src/commands/thinkback/
- src/commands/bughunter/
- src/plugins/ 全目錄
- src/constants/betas.ts（feature flags）

報告格式：
1. 每個特殊模組的功能說明
2. KAIROS 主動模式分析（如找到相關 flag）
3. Buddy 系統完整分析（物種、稀有度、互動）
4. UltraPlan 遠端規劃機制
5. Computer Use 整合架構
6. 未公開/實驗性功能完整列表
7. Plugin 系統架構
8. 有趣的彩蛋或隱藏功能

將報告寫入 reports/08-special-features.md
```

---

## Phase 0: Executive Summary 總覽（最後執行）

```
讀取 reports/ 目錄下所有已完成的報告（01-10），產出一份 executive summary：

報告格式：
1. Claude Code Harness 架構一頁總覽圖
2. 十大最重要發現（每個 1-2 段）
3. Harness Engineering 設計原則提煉（可遷移到其他 agent 專案）
4. 成本工程核心心法
5. 安全架構設計模式
6. 未公開功能與發展方向預測
7. 完整的外部參考資料列表
8. 各報告的快速導覽索引

將報告寫入 reports/00-executive-summary.md
```

---

## 外部參考資料（報告撰寫時應交叉引用）

### Anthropic 官方
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — Anthropic 工程團隊的 harness 設計指南

### 社群逆向分析
- [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) — 從 0 到 1 逆向 Claude Code harness 的教學 repo（12 個 session）
- [Kuberwastaken/claude-code](https://github.com/Kuberwastaken/claude-code) — 同批洩漏的分析與 breakdown
- [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) — 系統提示詞逐版本追蹤
- [The Complete Guide to Writing Agent System Prompts](https://www.mynameisfeng.com/blog/the-complete-guide-to-writing-agent-system-prompts-lessons-from-reverse-engineering-claude-code) — 基於 Claude Code 逆向的 prompt 撰寫指南

### Harness Engineering 定義與框架
- [NxCode - What Is Harness Engineering (2026)](https://www.nxcode.io/resources/news/what-is-harness-engineering-complete-guide-2026)
- [harness-engineering.ai](https://harness-engineering.ai/blog/what-is-harness-engineering/) — 學科定義
- [HumanLayer - Skill Issue: Harness Engineering](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)
- [Epsilla - The Third Evolution: Harness Engineering Replaced Prompting](https://www.epsilla.com/blogs/harness-engineering-evolution-prompt-context-autonomous-agents)
- [LangChain - Improving Deep Agents with Harness Engineering](https://blog.langchain.com/improving-deep-agents-with-harness-engineering/)

### 成本與 Token 經濟學
- [AI Agent Cost Optimization: Token Economics (Zylos)](https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics)
- [Claude Code Pricing & Optimization](https://claudefa.st/blog/guide/development/usage-optimization)
- [Claude Code Token Limits (Faros)](https://www.faros.ai/blog/claude-code-token-limits)
- [Anthropic Rate Limits](https://platform.claude.com/docs/en/api/rate-limits)
- [HaaS: Harness as a Service](https://www.vtrivedy.com/posts/claude-code-sdk-haas-harness-as-a-service/)

### 學術
- [Natural-Language Agent Harnesses (arXiv)](https://arxiv.org/html/2603.25723v1)
- [Building AI Coding Agents for the Terminal (arXiv)](https://arxiv.org/html/2603.05344v1)

---

## 執行須知

1. **每個 Phase 開一個獨立 session** 避免 context window 溢出
2. **報告必須包含原文引用** 不只是摘要，要有可驗證的一手資料
3. **建議使用 /thorough 模式** 確保深度和完整度
4. **所有報告寫入 `reports/` 目錄**，最後用 Phase 0 整合
5. **P0 三份報告最優先**：Phase 9 → Phase 1 → Phase 10
6. **交叉引用外部資料**：每份報告在相關段落標注對應的外部參考
