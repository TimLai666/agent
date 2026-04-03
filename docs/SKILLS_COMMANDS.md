# Skills 指令（現行）

## 指令

1. `/skills` 或 `/skills list`
- 列出目前載入的 skills（名稱 + 摘要）。

2. `/skills info <name>`
- 顯示單一 skill 詳細資訊。
- 包含 description、bundled resources 摘要、內容預覽。

3. `/skills test <text>`
- 使用 registry 的匹配器測試指定文字可能對應哪些 skills。
- 主要用途是排查與觀察，不代表主對話流程會自動注入 skill。

4. `/skills reload`
- 從磁碟重新載入 skills。
- 會沿用啟動時設定的多路徑（`--skills-dir`）。

## 和 use_skill 的差異

1. `/skills ...`
- 人工管理與檢查用。

2. `use_skill(...)`
- agent 在實際任務中啟用 skill 的方式。

## 常見流程

1. `/skills`
- 先確認 skill 是否被載入。

2. `/skills info <name>`
- 檢查 skill 描述與資源是否正確。

3. `/skills reload`
- 修改 `SKILL.md` 後重載。

4. 重新送出任務
- 觀察 agent 是否呼叫 `use_skill`。

## 多路徑示例

```bash
python main.py --skills-dir skills extra_skills vendor_skills
```

## 注意

目前技能架構為 tool-based：

1. 由 agent 視任務需要呼叫 `use_skill`。
2. 非舊版「每輪自動把 skill 內容注入 prompt」。
