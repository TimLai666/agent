# Skills 日誌（現行）

## 主要日誌來源

1. `internal.skills_loader`
- 掃描了多少 `SKILL.md`
- 載入了多少 skills
- 使用哪些 roots

2. `internal.tools.skill_tools`
- `use_skill` 啟用了哪個 skill

3. Lazy loading
- 第一次讀取 skill 內容
- 第一次讀取某個 resource

## 常見訊息

```text
INFO  - Found N skill files
INFO  - Loaded N skills from <roots>
INFO  - SkillRegistry initialized with N skills (LLM scorer: disabled|enabled)
INFO  - [Tool] Activated skill: <skill-name>
INFO  - Loaded content for skill '<skill-name>' (~XXXX chars)
INFO  - Loaded resource scripts:foo.py for skill '<skill-name>'
```

## 開啟詳細日誌

```python
import logging

logging.getLogger("internal.skills_loader").setLevel(logging.DEBUG)
logging.getLogger("internal.tools.skill_tools").setLevel(logging.DEBUG)
```

## 快速排查

1. 沒有載入 skill
- 檢查 `Loaded N skills from ...` 是否指向正確路徑。

2. 看不到 `use_skill`
- 先用 `/skills`、`/skills info` 確認技能存在。

3. 沒看到資源路徑
- 確認 skill 目錄中有 `scripts/`、`references/` 或 `assets/`。
