# Skills 系統（現行架構）

## 概覽

本專案目前採用「工具啟用型（tool-based）」skills：

1. 啟動時載入所有 skills metadata。
2. 在 `MainAgent` 註冊 `use_skill` 工具。
3. Agent 判斷需要時主動呼叫 `use_skill(skill_name)`。
4. `use_skill` 回傳該 skill 內容與可用資源（scripts/references/assets）。

重要：目前不是「自動把 skill 內容注入每次對話 prompt」的模式。

## 核心元件

1. `SkillSpec`

- 位置：`internal/skills_loader.py`
- 內容：`name`、`description`、`path`、`resources`。
- `content` 會延遲讀取 `SKILL.md`（lazy loading）。

1. `SkillRegistry`

- 位置：`internal/skills_loader.py`
- 負責管理已載入 skills、名稱查找、匹配函式與 metadata 彙整。

1. `use_skill` 工具

- 位置：`internal/tools/skill_tools.py`
- 啟用後回傳：skill 內容 + Bundled Resources（若存在）。

## 掃描與載入規則

1. 以 `SKILL.md` 為 skill 定位檔。
2. 使用遞迴掃描（`rglob("SKILL.md")`），支援多層資料夾。
3. 支援單一路徑與多路徑載入：
   - `root_dir`：單一路徑（舊參數）
   - `root_dirs`：多路徑（新參數，優先）

## 入口設定（多技能路徑）

可在程式入口使用：

```bash
python main.py --skills-dir skills extra_skills vendor_skills
```

行為：

1. CLI 與 GUI 都會吃到同一組 `skill_root_dirs`。
2. `/skills reload` 會沿用同一組路徑重新載入。

若未指定 `--skills-dir`，預設載入順序為：

1. `~/.agents/skills`
2. `~/.claude/skills`
3. 專案內建 `skills/`

## Bundled Resources

每個 skill 可包含以下子資料夾：

1. `scripts/`
2. `references/`
3. `assets/`

系統在載入 skill 時會建立資源清單；呼叫 `use_skill` 時會把資源檔名與路徑回傳給 agent。

## 目前關於匹配的定位

`SkillRegistry.find_relevant_skills()` 仍存在，可用於測試或額外流程，但它不是主對話流程中的自動注入機制。

## 參考檔案

1. `internal/skills_loader.py`
2. `internal/tools/skill_tools.py`
3. `internal/agents/main_agent.py`
4. `internal/command_handler.py`
5. `main.py`
