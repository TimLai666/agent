# 08 — Feature Flags 完整清單

## 概覽

Claude Code 使用兩個層次的 Feature Flag 系統：
1. **編譯期 flags**（`bun:bundle` 的 `feature()`）：決定功能是否進入 bundle
2. **運行期 flags**（GrowthBook / Statsig）：決定功能是否對特定用戶啟用

---

## 編譯期 Flags（`feature()` 來自 `bun:bundle`）

來源：`src/constants/betas.ts` 及 grep 全庫

| Flag 名稱 | 使用位置 | 說明 |
|----------|---------|------|
| `BUDDY` | buddy/ 全目錄 | Buddy AI 寵物系統 |
| `VOICE_MODE` | voice/voiceModeEnabled.ts | 語音模式 |
| `CONNECTOR_TEXT` | betas.ts | 影響 `summarize-connector-text-2026-03-13` beta header |
| `TRANSCRIPT_CLASSIFIER` | betas.ts | 影響 `afk-mode-2026-01-31` beta header |

---

## API Beta Headers（`src/constants/betas.ts`）

| 常數名稱 | Header 值 | 說明 |
|---------|---------|------|
| `CLAUDE_CODE_20250219_BETA_HEADER` | `claude-code-20250219` | Claude Code 基礎 beta |
| `INTERLEAVED_THINKING_BETA_HEADER` | `interleaved-thinking-2025-05-14` | 交錯式思考 |
| `CONTEXT_1M_BETA_HEADER` | `context-1m-2025-08-07` | 1M context window |
| `CONTEXT_MANAGEMENT_BETA_HEADER` | `context-management-2025-06-27` | Context 管理 |
| `STRUCTURED_OUTPUTS_BETA_HEADER` | `structured-outputs-2025-12-15` | 結構化輸出 |
| `WEB_SEARCH_BETA_HEADER` | `web-search-2025-03-05` | Web 搜尋 |
| `TOOL_SEARCH_BETA_HEADER_1P` | `advanced-tool-use-2025-11-20` | 工具搜尋（Claude API / Foundry） |
| `TOOL_SEARCH_BETA_HEADER_3P` | `tool-search-tool-2025-10-19` | 工具搜尋（Vertex / Bedrock） |
| `EFFORT_BETA_HEADER` | `effort-2025-11-24` | Effort 控制 |
| `TASK_BUDGETS_BETA_HEADER` | `task-budgets-2026-03-13` | Task 預算控制 |
| `PROMPT_CACHING_SCOPE_BETA_HEADER` | `prompt-caching-scope-2026-01-05` | Prompt 快取範圍 |
| `FAST_MODE_BETA_HEADER` | `fast-mode-2026-02-01` | 快速模式 |
| `REDACT_THINKING_BETA_HEADER` | `redact-thinking-2026-02-12` | 思考過程隱藏 |
| `TOKEN_EFFICIENT_TOOLS_BETA_HEADER` | `token-efficient-tools-2026-03-28` | Token 效率工具 |
| `SUMMARIZE_CONNECTOR_TEXT_BETA_HEADER` | `summarize-connector-text-2026-03-13`（`feature('CONNECTOR_TEXT')` 條件） | Connector 文字摘要 |
| `AFK_MODE_BETA_HEADER` | `afk-mode-2026-01-31`（`feature('TRANSCRIPT_CLASSIFIER')` 條件） | AFK 模式 |
| `CLI_INTERNAL_BETA_HEADER` | `cli-internal-2026-02-09`（`USER_TYPE === 'ant'` 條件） | 內部 CLI 功能 |
| `ADVISOR_BETA_HEADER` | `advisor-tool-2026-03-01` | 顧問工具 |
| `CCR_BYOC_BETA` | `ccr-byoc-2025-07-29` | CCR Bring Your Own Credentials |

### 特殊平台限制

**Bedrock 額外參數**（不透過 header，改用 extraBodyParams）：
- `interleaved-thinking-2025-05-14`
- `context-1m-2025-08-07`
- `tool-search-tool-2025-10-19`

**Vertex countTokens 允許清單**：
- `claude-code-20250219`
- `interleaved-thinking-2025-05-14`
- `context-management-2025-06-27`

---

## 運行期 GrowthBook Feature Flags（`tengu_*`）

### 核心功能 Flags

| Flag 名稱 | 說明 | 預設值 |
|----------|------|--------|
| `tengu_amber_quartz_disabled` | 語音模式 kill-switch（true = 停用語音） | false |
| `tengu_onyx_plover` | AutoDream 整合（含 enabled/minHours/minSessions） | disabled |
| `tengu_malort_pedway` | Computer Use（Chicago）功能 | disabled |
| `tengu_thinkback` | 年度回顧功能 | — |
| `tengu_ccr_bridge` | CCR Bridge 功能 | false |
| `tengu_cobalt_harbor` | 強制所有 session 連接 CCR | false |
| `tengu_harbor_permissions` | Harbor 權限系統 | — |

### Bridge 相關 Flags

| Flag 名稱 | 說明 |
|----------|------|
| `tengu_bridge_repl_v2` | Bridge REPL v2 |
| `tengu_bridge_repl_v2_cse_shim_enabled` | CSE ID 相容 shim（`cse_*` → `session_*` 前綴轉換） |
| `tengu_bridge_min_version` | 最低版本要求（`{ minVersion: '0.0.0' }`） |
| `tengu_ccr_bridge_multi_session` | 多 session 支援 |
| `tengu_ccr_bridge_multi_session`（sibling）| 多環境支援 |
| `tengu_ccr_mirror` | CCR 鏡像功能 |
| `tengu_ccr_bundle_seed_enabled` | Bundle seed 功能 |
| `tengu_bridge_initial_history_cap` | 初始歷史記錄上限 |

### 模型與 API Flags

| Flag 名稱 | 說明 |
|----------|------|
| `tengu_amber_flint` | — |
| `tengu_amber_json_tools` | JSON 工具格式 |
| `tengu_amber_prism` | — |
| `tengu_amber_stoat` | — |
| `tengu_amber_wren` | — |
| `tengu_ant_model_override` | Ant 人員模型覆蓋 |
| `tengu_immediate_model_command` | 立即模型命令 |
| `tengu_attribution_header` | API attribution header |

### 工具與能力 Flags

| Flag 名稱 | 說明 |
|----------|------|
| `tengu_tool_pear` | 特定工具能力 |
| `tengu_agent_list_attach` | Agent 列表附加 |
| `tengu_slim_subagent_claudemd` | 精簡 subagent CLAUDE.md |
| `tengu_advisor_tool_call` | 顧問工具調用（事件） |
| `tengu_harbor` | Harbor 功能 |
| `tengu_anti_distill_fake_tool_injection` | 反蒸餾假工具注入 |

### Slate 系列 Flags（UI/輸出相關）

| Flag 名稱 | 說明 |
|----------|------|
| `tengu_slate_prism` | Slate prism（UI 功能）預設 true |
| `tengu_slate_thimble` | 非互動式記憶萃取端到端控制 |

### 其他特殊 Flags

| Flag 名稱 | 說明 |
|----------|------|
| `tengu_chrome_auto_enable` | Chrome 整合自動啟用 |
| `tengu_session_memory` | Session 記憶 |
| `tengu_basalt_3kr` | — |
| `tengu_birch_trellis` | — |
| `tengu_bramble_lintel` | — |
| `tengu_chair_sermon` | — |
| `tengu_chomp_inflection` | — |
| `tengu_collage_kaleidoscope` | — |
| `tengu_copper_bridge` | — |
| `tengu_copper_panda` | — |
| `tengu_coral_fern` | — |
| `tengu_fgts` | — |
| `tengu_glacier_2xr` | — |
| `tengu_herring_clock` | — |
| `tengu_hive_evidence` | — |
| `tengu_lapis_finch` | — |
| `tengu_lodestone_enabled` | — |
| `tengu_marble_fox` | — |
| `tengu_marble_sandcastle` | — |
| `tengu_moth_copse` | — |
| `tengu_otk_slot_v1` | — |
| `tengu_passport_quail` | — |
| `tengu_pebble_leaf_prune` | — |
| `tengu_quartz_lantern` | — |
| `tengu_scratch` | — |
| `tengu_surreal_dali` | — |
| `tengu_trace_lantern` | — |
| `tengu_turtle_carbon` | — |
| `tengu_cobalt_lantern` | — |
| `tengu_cobalt_raccoon` | — |
| `tengu_strap_foyer` | — |

> 注意：許多 `tengu_` flags 採用「顏色 + 動物/物品」的命名模式（如 `amber_quartz`、`cobalt_harbor`），這是 Anthropic 內部代號命名規則，具體功能難以從名稱推斷。

---

## Statsig Feature Gates

| Gate 名稱 | 說明 |
|----------|------|
| `tengu_thinkback` | 年度回顧功能（Statsig gate） |
| `tengu_ccr_bridge_multi_session` | CCR 多 session（Statsig gate） |
| `tengu_ccr_bridge` | CCR Bridge（Statsig gate） |
| `tengu_sessions_elevated_auth_enforcement` | Session 認證強制（文件引用） |

---

## 環境變數 Flags

| 變數 | 說明 |
|------|------|
| `USER_TYPE === 'ant'` | Anthropic 員工標識，繞過多項限制 |
| `ALLOW_ANT_COMPUTER_USE_MCP=1` | Ant 員工強制啟用 Computer Use |
| `MONOREPO_ROOT_DIR` | 有此變數的 Ant 員工停用 Computer Use |

---

## Feature Flag 總量

- 編譯期 `feature()` flags：4 個
- API Beta headers：18 個常數
- GrowthBook `tengu_*` feature values（作為配置使用）：~52 個
- 全庫 `tengu_*` 事件/flag 名稱：~656 個唯一值（含 analytics 事件）
