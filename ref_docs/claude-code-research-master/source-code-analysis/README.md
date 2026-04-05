# Claude Code CLI 原始碼逆向分析報告集

> 基於 Claude Code v2.1.88（2026-03-31 npm sourcemap 洩漏）
> 75 份分類報告 | 10 大領域 | ~884KB 分析內容

---

## 目錄

### Phase 9: Harness Engineering 全景分析 ⭐ P0

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [Agent Loop 分析](phase-09-harness-engineering/01-agent-loop-analysis.md) | 逆向 query.js 完整執行路徑，揭示「模型呼叫 → 工具執行 → feedback 回注」循環的精確控制流程 |
| 02 | [Context Engineering 策略](phase-09-harness-engineering/02-context-engineering.md) | 解析 system prompt 組裝、messages 正規化、prompt cache 管理的多層處理管道 |
| 03 | [Tool Orchestration 設計模式](phase-09-harness-engineering/03-tool-orchestration.md) | toolOrchestration.ts 與 toolExecution.ts 構成的多階段、多重防護工具調度系統深度分析 |
| 04 | [Observability 與遙測設計](phase-09-harness-engineering/04-observability-telemetry.md) | Analytics/Events、OpenTelemetry、Diagnostic Tracking 三層可觀測性架構全景 |
| 05 | [Coordinator 模式運作機制](phase-09-harness-engineering/05-coordinator-mode.md) | 主 agent 扮演協調者、透過 Agent 工具派遣 worker 並行執行任務的多 agent 協調系統 |
| 06 | [啟動流程與生命週期分析](phase-09-harness-engineering/06-bootstrap-lifecycle.md) | 高度優化的並行啟動流水線，最小化 time-to-first-render 與 time-to-first-API-call 的完整機制 |
| 07 | [Harness 設計原則（可遷移知識庫）](phase-09-harness-engineering/07-harness-design-principles.md) | 從真實生產系統提煉的可遷移 Harness Engineering 設計原則，定義 Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions |

---

### Phase 1: System Prompt Engineering ⭐ P0

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [主系統提示詞完整原文與逐段解析](phase-01-system-prompt/01-main-system-prompt.md) | 完整還原 prompts.ts（914 行）的主系統提示詞，逐段中文解析身份宣告、能力邊界、行為規範 |
| 02 | [Prompt 組裝邏輯分析](phase-01-system-prompt/02-prompt-assembly-logic.md) | 解析 getSystemPrompt 函式如何動態組合 system prompt 的核心資料結構與條件分支 |
| 03 | [Context Compaction Prompt 分析](phase-01-system-prompt/03-compaction-prompt.md) | compact/prompt.ts（374 行）的完整解析，揭示對話壓縮提示詞的設計目標與三種壓縮模式 |
| 04 | [輔助 Prompt 集合分析](phase-01-system-prompt/04-utility-prompts.md) | 記憶提取、Session Memory、MagicDocs、Buddy 寵物、Chrome 整合等五類輔助 prompt 完整原文 |
| 05 | [安全指令分析](phase-01-system-prompt/05-safety-instructions.md) | cyberRiskInstruction.ts 的 CYBER_RISK_INSTRUCTION 完整解析，揭示網路安全操作的強制限制 |
| 06 | [Prompt Engineering 設計模式](phase-01-system-prompt/06-prompt-engineering-patterns.md) | 從所有 prompt 原始碼提煉的可直接應用的設計模式，包含三明治強化、角色綁定等核心技巧 |

---

### Phase 10: Cost & Quota Management ⭐ P0

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [成本追蹤架構全景](phase-10-cost-quota/01-cost-tracking-architecture.md) | cost-tracker.ts 與 costHook.ts 構成的「即時累積 → 持久化 → 恢復」完整成本狀態管理迴路 |
| 02 | [Rate Limiting 機制](phase-10-cost-quota/02-rate-limiting-mechanism.md) | 以 HTTP response header 為資料來源的三層額度管控架構：資料解析、狀態管理、UI 呈現 |
| 03 | [Prompt Caching 策略](phase-10-cost-quota/03-prompt-caching-strategy.md) | promptCacheBreakDetection.ts 的兩階段偵測與原因診斷系統，以及快取命中最佳化設計 |
| 04 | [Token Estimation 預估邏輯](phase-10-cost-quota/04-token-estimation.md) | 三種層次的 token 計數策略：API 精確計數、快速估算、字元比例換算，按需選擇精準度 |
| 05 | [Policy Limits 團隊管控機制](phase-10-cost-quota/05-policy-limits.md) | 組織層級功能管控系統，允許管理員動態禁用特定功能，採用 fail open + 背景輪詢設計 |
| 06 | [Model Selection 與成本關係](phase-10-cost-quota/06-model-cost-relationship.md) | configs.ts 跨平台模型 ID 映射與 modelCost.ts 定價表的關聯，以及 fast mode 計費層次分析 |
| 07 | [Context Compaction 作為成本節約手段](phase-10-cost-quota/07-compaction-as-cost-saving.md) | 自動對話壓縮機制如何透過減少 input token 數量實現成本控制的完整策略分析 |
| 08 | [使用者端成本工具](phase-10-cost-quota/08-user-facing-cost-tools.md) | /cost、/usage、/stats 三個命令的定位差異與實作分析，服務不同資訊需求 |

---

### Phase 2: Tool Definitions 工具系統

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [36 個工具總覽表](phase-02-tool-definitions/01-tool-overview-table.md) | 從 src/tools/*/prompt.ts 提煉的完整工具分類與說明總表 |
| 02 | [核心工具 Prompt 原文集](phase-02-tool-definitions/02-core-tool-prompts.md) | BashTool、AgentTool、SkillTool、FileEditTool 等 8 個核心工具的 prompt 完整原文 |
| 03 | [規劃/任務工具 Prompt 集](phase-02-tool-definitions/03-planning-task-prompts.md) | EnterPlanMode、TaskCreate、TaskUpdate、TodoWrite 等規劃工具的 prompt 完整原文 |
| 04 | [Agent 通訊工具 Prompt 集](phase-02-tool-definitions/04-agent-communication-prompts.md) | AgentTool、SendMessageTool、ToolSearchTool、EnterWorktreeTool 等 agent 通訊工具的完整原文 |
| 05 | [外部工具 Prompt 集](phase-02-tool-definitions/05-external-tools-prompts.md) | WebFetchTool、WebSearchTool、MCPTool、ScheduleCronTool 等外部整合工具的 prompt 原文 |
| 06 | [團隊/設定工具 Prompt 集](phase-02-tool-definitions/06-team-config-prompts.md) | TeamCreateTool、ConfigTool、SkillTool、SleepTool、LSPTool 等管理工具的 prompt 完整集 |
| 07 | [工具執行與編排邏輯分析](phase-02-tool-definitions/07-tool-execution-orchestration.md) | toolExecution.ts（1745 行）+ toolOrchestration.ts（189 行）的工具調度機制深度解析 |
| 08 | [Tool Prompt 設計模式](phase-02-tool-definitions/08-tool-design-patterns.md) | 從 36 個工具 prompt 提煉的設計原則，包含工具偏好金字塔等核心設計模式 |

---

### Phase 3: Agent Architecture

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [Agent 系統架構全景圖](phase-03-agent-architecture/01-agent-system-overview.md) | Claude Code Agent 系統三個主要層次的完整架構圖與組件說明 |
| 02 | [Built-in Agents 完整分析](phase-03-agent-architecture/02-built-in-agents.md) | src/tools/AgentTool/built-in/ 下 6 個內建 agent 的 BuiltInAgentDefinition 完整解析 |
| 03 | [Agent 生命週期分析](phase-03-agent-architecture/03-agent-lifecycle.md) | 從 Spawn 到終止的完整 agent 生命週期，包含工具權限繼承與隔離環境管理 |
| 04 | [Coordinator Mode 完整逆向](phase-03-agent-architecture/04-coordinator-mode.md) | coordinatorMode.ts（369 行）的完整逆向，揭示主 agent 從執行者轉換為調度者的機制 |
| 05 | [Swarm/Teammate 多 Agent 協作機制](phase-03-agent-architecture/05-swarm-teammate.md) | src/utils/swarm/（14 個檔案）的 Team Lead 協調多 Teammate 並行執行任務的完整架構 |
| 06 | [Task 系統分析](phase-03-agent-architecture/06-task-system.md) | src/tasks/ 中追蹤所有非同步工作的核心機制與 TaskState union 型別設計 |
| 07 | [Agent 間通訊](phase-03-agent-architecture/07-agent-communication.md) | Claude Code agent 間通訊的三個層次：直接呼叫、訊息傳遞、共享狀態 |

---

### Phase 6: Security & Permissions

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [安全架構總覽](phase-06-security-permissions/01-security-architecture-overview.md) | 縱深防禦（Defense-in-Depth）七層安全模型的完整架構圖與各層職責 |
| 02 | [Bash 命令安全過濾完整規則集](phase-06-security-permissions/02-bash-security-rules.md) | bashSecurity.ts 的同步/非同步 API 實作，以及 tree-sitter 解析器整合的安全過濾規則 |
| 03 | [Bash 權限判斷模型](phase-06-security-permissions/03-bash-permissions-model.md) | bashToolHasPermission() 主入口的完整權限判斷邏輯與條件分支 |
| 04 | [唯讀模式實作](phase-06-security-permissions/04-readonly-validation.md) | BashTool、shell 共用函數庫、PowerShellTool 三份唯讀驗證實作的比較分析 |
| 05 | [檔案系統權限模型](phase-06-security-permissions/05-filesystem-permissions.md) | DANGEROUS_FILES 黑名單與 filesystem.ts 的完整檔案系統存取控制機制 |
| 06 | [Sandbox 沙箱機制](phase-06-security-permissions/06-sandbox-mechanism.md) | SandboxManager 的架構設計與沙箱隔離的實作方式 |
| 07 | [工具權限 Hook 系統](phase-06-security-permissions/07-tool-permission-hooks.md) | 從 bashToolHasPermission 返回 ask 行為到 UI 呈現的完整 permission hook 處理管道 |
| 08 | [安全設計模式提煉](phase-06-security-permissions/08-security-design-patterns.md) | 從 Claude Code 安全架構提煉的可遷移設計模式，含縱深防禦等核心模式 |

---

### Phase 4: Skills System

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [Skills 系統架構分析](phase-04-skills-system/01-skills-architecture.md) | Skills 作為「可程式化指令擴充」機制的系統概覽，包含工具授權與子 agent 隔離環境設計 |
| 02 | [SkillTool Prompt 完整原文與分析](phase-04-skills-system/02-skill-tool-prompt.md) | src/tools/SkillTool/prompt.ts（241 行）的完整原文解析 |
| 03 | [Bundled Skills 完整目錄](phase-04-skills-system/03-bundled-skills-catalog.md) | 16 個內建 bundled skills 的完整目錄，含條件載入規則與各 skill 功能說明 |
| 04 | [Skill 設計模式：從原始碼提煉](phase-04-skills-system/04-skill-design-patterns.md) | 從 16 個 bundled skills 提煉的高品質 skill 設計模式與反模式 |
| 05 | [Skills 與 Tools 的區別、互動機制、設計哲學](phase-04-skills-system/05-skills-vs-tools.md) | Skills 與 Tools 的根本定義差異、互動機制與設計哲學的系統性比較 |

---

### Phase 5: Memory & Context

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [Memory 系統架構全景圖](phase-05-memory-context/01-memory-architecture-overview.md) | 多層次、多機制並存的持久化記憶架構全景，核心設計目標與系統層次結構 |
| 02 | [Memdir 核心系統完整分析](phase-05-memory-context/02-memdir-system.md) | MEMORY.md 索引、MAX_ENTRYPOINT_LINES 限制等核心常數與 memdir.ts 架構的完整分析 |
| 03 | [Context Compaction 策略與 Prompt 分析](phase-05-memory-context/03-context-compaction.md) | compact/prompt.ts（374 行）的三種 compact 模式與觸發條件的完整解析 |
| 04 | [自動記憶提取機制（ExtractMemories）](phase-05-memory-context/04-memory-extraction.md) | 以 forked agent 模式在 query loop 結束後自動提取記憶的背景子系統完整分析 |
| 05 | [Session Memory 系統](phase-05-memory-context/05-session-memory.md) | 與跨 session Auto Memory 不同的 session 即時快照筆記系統，兩者定位對比與實作分析 |
| 06 | [MagicDocs 動態文檔系統](phase-05-memory-context/06-magic-docs.md) | 針對用戶 repo 內特定文件自動更新的機制，目前限 Anthropic 內部用戶（USER_TYPE=ant） |
| 07 | [Team Memory 同步機制](phase-05-memory-context/07-team-memory.md) | 讓同一 GitHub repo 所有用戶共享記憶的 Team Memory，個人與團隊記憶並存架構 |
| 08 | [AutoDream 夢境整合機制](phase-05-memory-context/08-auto-dream.md) | 跨 session 記憶鞏固系統，累積足夠 session 後自動啟動背景 forked agent 執行記憶精煉 |
| 09 | [Memory 設計原則提煉](phase-05-memory-context/09-memory-design-principles.md) | 從原始碼提煉的記憶系統設計原則，包含「只儲存不可推導資訊」等核心哲學 |

---

### Phase 7: API & Model Architecture

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [API 呼叫層完整分析](phase-07-api-model-architecture/01-api-layer-analysis.md) | src/services/api/claude.ts（3419 行）的模組角色與核心 API 呼叫架構完整解析 |
| 02 | [模型配置系統](phase-07-api-model-architecture/02-model-configuration.md) | configs.ts、model.ts、modelOptions.ts、modelStrings.ts 構成的配置層次結構 |
| 03 | [Provider 支援架構](phase-07-api-model-architecture/03-model-providers.md) | providers.ts、bedrock.ts、modelCapabilities.ts 的 Provider 型別與偵測機制 |
| 04 | [Beta Features 完整清單與分析](phase-07-api-model-architecture/04-beta-features.md) | betas.ts 中所有 Beta Header 常數的完整清單與啟用條件分析 |
| 05 | [啟動流程分析](phase-07-api-model-architecture/05-bootstrap-flow.md) | bootstrap/state.ts（1758 行）的全域狀態架構與初始化序列 |
| 06 | [入口點分析](phase-07-api-model-architecture/06-entrypoints.md) | cli.tsx、init.ts、mcp.ts、sdk/ 等所有入口點的角色與差異分析 |
| 07 | [模型選擇與路由邏輯](phase-07-api-model-architecture/07-model-selection-routing.md) | 模型別名系統、allowlist、驗證、deprecated 模型遷移的完整路由邏輯 |

---

### Phase 8: Special Features 特殊功能

| # | 報告 | 摘要 |
|---|------|------|
| 01 | [Buddy AI 寵物系統完整分析](phase-08-special-features/01-buddy-ai-pet.md) | src/buddy/（6 個檔案）的 ASCII art 精靈伴侶系統，包含 feature flag 與互動機制 |
| 02 | [Computer Use 整合架構分析](phase-08-special-features/02-computer-use.md) | 代號 Chicago（tengu_malort_pedway）的 macOS 電腦控制功能，src/utils/computerUse/（15 個檔案）完整架構 |
| 03 | [UltraPlan 遠端規劃機制分析](phase-08-special-features/03-ultraplan.md) | 輸入 ultraplan 關鍵字觸發的遠端 CCR 容器規劃模式，含 ultrareview 同類機制解析 |
| 04 | [語音系統分析](phase-08-special-features/04-voice-system.md) | src/voice/ 的語音模式架構，讓使用者能以語音與 Claude Code 互動的完整實作 |
| 05 | [AutoDream 夢境整合機制分析](phase-08-special-features/05-auto-dream.md) | 代號 tengu_onyx_plover 的後台記憶整合系統，累積 session 後自動審查並更新記憶 |
| 06 | [Plugin 系統架構分析](phase-08-special-features/06-plugins-system.md) | src/plugins/ 的 Built-in 與 Marketplace 兩類插件系統架構完整解析 |
| 07 | [隱藏/特殊 Commands 分析](phase-08-special-features/07-hidden-commands.md) | src/commands/ 中的非標準命令，包含彩蛋、實驗性功能和平台整合命令 |
| 08 | [Feature Flags 完整清單](phase-08-special-features/08-feature-flags.md) | 編譯期（bun:bundle feature()）與運行期（GrowthBook/Statsig）兩層 feature flag 系統 |
| 09 | [Moreright、Teleport、DeepLink 功能分析](phase-08-special-features/09-moreright-teleport-deeplink.md) | useMoreRight、Teleport、DeepLink 三個特殊 UI/導航功能的實作分析 |
| 10 | [未公開/實驗性功能總整理](phase-08-special-features/10-unreleased-features-summary.md) | 發現的 82 個編譯期 feature flags 完整清單，揭示尚未公開的產品路線圖 |

---

## 十大發現

> 從 75 份報告、~884KB 分析內容中提煉的最重要洞察

### 1. Agent Loop 是一個精密的有狀態機
Claude Code 的核心不是簡單的「問答循環」，而是帶有完整狀態管理、工具執行緩衝、feedback 注入機制的有狀態執行機。`query.js` 管理的 stop reason 判斷、tool result 回注、interrupt 處理形成了生產級 LLM harness 的完整範本。

### 2. Context Engineering 比 Prompt Engineering 更重要
系統投入了大量工程資源在 context 管理：prompt cache 對齊、messages 正規化、compaction 策略。每次 API 呼叫前的 context 構造是一個多步驟管道，這說明「讓模型看到什麼」遠比「如何說話給模型聽」更決定性能。

### 3. 安全架構採用七層縱深防禦
從 bash 解析器層（tree-sitter）到 UI 確認層，Claude Code 實作了完整的防禦縱深。特別是 `bashSecurity.ts` 的 AST 解析路徑遠比字串匹配複雜，說明 prompt injection 和命令注入是被當作嚴肅的系統威脅處理。

### 4. 記憶系統有五個獨立子系統並存
Auto Memory（持久）、Session Memory（當次）、MagicDocs（文件）、Team Memory（共享）、AutoDream（整合）構成了複雜的記憶生態。每個子系統有獨立的觸發條件、存儲格式和生命週期，但共享同一套 forked agent 基礎設施。

### 5. 82 個未公開 Feature Flags 揭示產品路線圖
`bun:bundle` 的 `feature()` 系統中包含大量尚未對用戶開放的功能：Computer Use、UltraPlan、語音模式、Buddy 寵物等。這些功能完整實作但以 flag 隱藏，說明產品具備遠超當前版本的技術儲備。

### 6. Coordinator/Swarm 是真正的多 Agent 系統
Claude Code 不只是單一 agent 加工具，而是具備完整 multi-agent 基礎設施：Coordinator Mode 的任務分解調度、Swarm 系統的 Team Lead/Teammate 協作、跨 worktree 的隔離執行。這是目前最完整的生產級 LLM multi-agent 實作之一。

### 7. 成本追蹤達到毫秒級精度
cost-tracker.ts 實現了跨 session 的精確成本追蹤、prompt cache 命中偵測、rate limit header 解析。系統能追蹤 cache break 的具體原因，說明成本最佳化是一等公民工程需求。

### 8. Skills 系統實現了「可程式化的 prompt 擴充」
Skills 不是簡單的文本模板，而是完整的「mini agent」框架：獨立的工具授權、可選的子 agent 隔離、防衛性的 getPromptForCommand 模式。16 個 bundled skills 本身就是一個設計模式的參考實作庫。

### 9. Prompt 設計有系統化的工程模式
從 prompt 原始碼提煉出「三明治強化」、「工具偏好金字塔」、「角色綁定」等 8+ 設計模式。這說明 Anthropic 的 prompt engineering 已從藝術演化為工程學科，有可複製的方法論。

### 10. 系統為企業/團隊場景做了深度設計
Policy Limits 的組織管控、Team Memory 的共享記憶、Team Config 工具集、多 provider 支援（AWS Bedrock/GCP Vertex）等功能說明 Claude Code 的目標市場明確包含企業客戶，且企業功能在架構層面與個人功能深度整合。
