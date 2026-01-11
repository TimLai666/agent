# Skills 快速參考

## 🚀 指令速查

```bash
/skills                    # 列出所有 skills
/skills info <name>        # 查看 skill 詳情
/skills test <prompt>      # 測試 skill 匹配
/skills reload             # 重新載入 skills
```

## 📁 目錄結構

```
skills/
├── README.md                      # Skills 說明文檔
├── QUICKSTART.md                  # 快速入門
├── code-review/
│   └── SKILL.md                   # 代碼審查 skill
├── debugging-assistant/
│   └── SKILL.md                   # 除錯助手 skill
├── python-tutorial/
│   ├── SKILL.md                   # Python 教學 skill
│   ├── scripts/
│   │   └── hello_world.py
│   ├── references/
│   │   └── cheatsheet.md
│   └── assets/
│       └── template.py
└── tool-usage-guide/
    └── SKILL.md                   # Tools 使用指南
```

## 🎯 核心概念

**Skills = 知識模組**
- 提供方法論、最佳實踐、指導
- 自動激活（基於提示匹配）
- 注入到 agent 的 context

**vs Tools = 執行工具**
- 執行實際操作（讀文件、調 API）
- 需要明確調用
- 返回數據

**vs SubAgents = 專門 agent**
- 有自己的系統提示和行為
- 處理特定類型任務
- 可以使用 skills

## 📝 創建 Skill

### 1. 基本結構

```markdown
---
name: my-skill
description: 清楚描述這個 skill 做什麼以及何時使用
---

# My Skill

[你的指導內容...]

## When to Use
- 使用場景 1
- 使用場景 2

## Guidelines
1. 指導方針 1
2. 指導方針 2
```

### 2. 創建步驟

```bash
# 1. 創建目錄
mkdir skills/my-skill

# 2. 創建 SKILL.md
cat > skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: 你的描述
---

# 你的內容
EOF

# 3. 重新載入
# 在 agent 中執行：
> /skills reload

# 4. 驗證
> /skills info my-skill
```

### 3. Bundled Resources（可選）

```bash
# 添加腳本
mkdir skills/my-skill/scripts
echo "#!/usr/bin/env python3" > skills/my-skill/scripts/example.py

# 添加參考文檔
mkdir skills/my-skill/references
echo "# Reference" > skills/my-skill/references/guide.md

# 添加資源
mkdir skills/my-skill/assets
echo "template" > skills/my-skill/assets/template.txt
```

## 🔍 使用 Skills

### 自動激活

```
用戶：Can you review this code?
系統：自動匹配到 code-review skill
系統：注入 code-review 內容到 context
Agent：根據 code-review 指導進行審查
```

### 查看激活的 Skills

日誌中會顯示：
```
INFO - [MainAgent] Activated 2 skill(s): code-review, debugging-assistant
```

### 測試匹配

```
> /skills test Can you review my code?

Testing prompt: 'Can you review my code?'
Matched 1 skill(s):

1. code-review
   Provides systematic code review guidance.
```

## 🎓 示例 Skills

### 1. Code Review
- **激活條件**: "review code", "check quality", "find bugs"
- **提供**: 系統化代碼審查方法論
- **包含**: 安全、性能、可讀性檢查清單

### 2. Debugging Assistant
- **激活條件**: "bug", "error", "debug", "not working"
- **提供**: 結構化除錯流程
- **包含**: 問題定位、假設測試、常見 bug 模式

### 3. Python Tutorial
- **激活條件**: "python", "learn python", "python syntax"
- **提供**: Python 編程指導
- **包含**: Scripts, references, assets

### 4. Tool Usage Guide
- **激活條件**: "tools", "how to use tool"
- **提供**: Tools 使用最佳實踐
- **包含**: 安全、性能、錯誤處理指導

## 📊 日誌

### INFO 級別
```
INFO - Loaded 5 skills from /path/to/skills
INFO - [MainAgent] Activated 2 skill(s): code-review, debugging-assistant
```

### DEBUG 級別
```
DEBUG - Searching for relevant skills (mode: keyword, max: 3, min_score: 0.10)
DEBUG -   - 'code-review': score=0.567 (matched: code, review, bugs)
DEBUG - Selected top 2 skill(s)
```

## 🎯 配對機制

### LLM 語義匹配（預設啟用）⭐

**現已使用 LLM 進行語義理解匹配！**

```
1. LLM 評估每個 skill 與 prompt 的語義相關性
2. 返回 0.0-1.0 的相關性分數
3. 篩選 >= 0.3 的 skills
4. 按分數排序，取前 3 個
```

**特點：**

- ✓ **完美支援中文**（"教我寫python" ✓）
- ✓ 語義理解而非關鍵詞匹配
- ✓ 95%+ 準確性
- ⚠️ 稍慢（~300ms）但值得

### 實際範例

```
Prompt: "教我寫python"  （純中文）

LLM 匹配結果：
- python-tutorial: 0.95 ✅
- code-review: 0.10 ❌
- debugging: 0.05 ❌

激活：python-tutorial
```

```
Prompt: "代碼品質不好，怎麼改進"  （語義理解）

LLM 匹配結果：
- code-review: 0.85 ✅
- debugging-assistant: 0.60 ✅
- python-tutorial: 0.15 ❌

激活：code-review, debugging-assistant
```

### 測試配對

```bash
/skills test <你的 prompt>  # 查看會匹配哪些 skills
/skills test 教我寫python   # 中文也完美支援！
```

## ⚡ 優先級系統

### 決策層級

```
Skills（專家指導）> Tools（執行操作）> 直接回答
```

### 實際效果

當 skill 被激活時，會在 context 中加入：

```markdown
# Active Skills (PRIORITY: Use these BEFORE tools)

**IMPORTANT**: 優先使用以下 skills 的知識和方法論...

## code-review
[內容...]

---
**Remember**: 遵循 skills 指導再使用 tools
```

## 🔧 配置

### 匹配參數

```python
# 在 MainAgent._apply_skills() 中
relevant_skills = self.skills.find_relevant_skills(
    prompt,
    max_skills=3,      # 最多激活 3 個
    min_score=0.1,     # 最低相關性 0.1
    use_llm=False      # 使用關鍵詞匹配（快）
)
```

### LLM 評分模式

```python
# 啟用 LLM 評分（更準確但較慢）
registry = load_skill_registry(
    enable_llm_scoring=True,
    agent=your_agent
)
```

## 🐛 故障排查

| 問題 | 檢查 | 解決 |
|------|------|------|
| Skills 未載入 | `/skills` | 檢查 skills/ 目錄和 SKILL.md |
| Skill 未激活 | `/skills test <prompt>` | 改進 description 關鍵詞 |
| 找不到 skill | `/skills info <name>` | 確認名稱拼寫正確 |
| 修改未生效 | `/skills reload` | 重新載入 skills |

## 📚 完整文檔

- **系統架構**: [docs/SKILLS_SYSTEM.md](docs/SKILLS_SYSTEM.md)
- **完整實現**: [docs/SKILLS_FULL_IMPLEMENTATION.md](docs/SKILLS_FULL_IMPLEMENTATION.md)
- **使用指南**: [docs/SKILLS_USAGE_IN_AGENTS.md](docs/SKILLS_USAGE_IN_AGENTS.md)
- **配對與優先級**: [docs/SKILLS_MATCHING_AND_PRIORITY.md](docs/SKILLS_MATCHING_AND_PRIORITY.md) ⭐ NEW
- **日誌系統**: [docs/SKILLS_LOGGING.md](docs/SKILLS_LOGGING.md)
- **指令文檔**: [docs/SKILLS_COMMANDS.md](docs/SKILLS_COMMANDS.md)
- **vs Tools**: [docs/SKILLS_VS_TOOLS.md](docs/SKILLS_VS_TOOLS.md)
- **Skills 目錄**: [skills/README.md](skills/README.md)
- **快速入門**: [skills/QUICKSTART.md](skills/QUICKSTART.md)

## 💡 最佳實踐

### Description 撰寫
```yaml
# ✅ 好的 description
description: Provides systematic code review guidance. Use when the user asks to review code, check code quality, find bugs, or improve code structure.

# ❌ 差的 description
description: A helpful skill for coding.
```

### 內容組織
- 主要內容在 SKILL.md（< 500 行）
- 詳細文檔放 references/
- 示例腳本放 scripts/
- 模板資源放 assets/

### 關鍵詞選擇
- 包含所有相關的觸發詞
- 使用用戶會說的詞（不是技術術語）
- 測試匹配：`/skills test <各種說法>`

## 🎯 總結

**Skills 系統提供：**
- ✅ 知識注入（vs Tools 的執行）
- ✅ 自動激活（vs 手動調用）
- ✅ Progressive disclosure（按需載入）
- ✅ 完整的指令支援（查看、測試、重載）
- ✅ 詳細的日誌記錄
- ✅ Bundled resources 支援

**立即開始：**
```bash
> /skills                    # 查看現有 skills
> /skills test <your text>   # 測試匹配
> mkdir skills/my-skill      # 創建新 skill
> /skills reload             # 載入新 skill
```
