# Claude Code Skills 實現方式

## 🎯 官方實現原理

### 來源

根據 [Claude Agent Skills Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/) 的詳細分析：

### 核心機制

1. **Skills 是 Prompt Templates**
   - 不是可執行代碼
   - 是專門的提示詞模板，注入領域特定指令到對話 context

2. **通過 Tool 實現**
   - 系統註冊一個 `use_skill` tool
   - Tool 的 description 包含所有可用 skills 的 name 和 description
   - 格式化成列表讓 Claude 閱讀

3. **Claude 自主決定**
   - **沒有算法路由或意圖分類**（原文："no algorithmic skill selection"）
   - 完全依賴 Claude 的語言理解能力
   - Claude 讀取 tool description 中的 skills 列表，用自己的推理能力匹配用戶意圖

4. **Tool Calling 激活**
   - 當 Claude 認為某個 skill 相關時，主動調用 `use_skill` tool
   - 參數包含要使用的 skill name
   - 系統注入對應 skill 的完整內容到 context

### 關鍵引用

> "There is no algorithmic skill selection or AI-powered intent detection at the code level. Instead, the system formats all available skills' names and descriptions into the Skill tool's description, letting Claude match user intent through language understanding."

> "Skills operate through prompt expansion and context modification to modify how Claude processes subsequent requests without writing executable code."

## 📊 對比分析

### 我們目前的實現（錯誤）

```python
async def _apply_skills(self, prompt: str) -> str:
    # ❌ 額外的 LLM API 調用來評分
    relevant_skills = await self.skills.find_relevant_skills(
        prompt,
        use_llm=True  # ❌ 調用 LLM 去評估相關性
    )

    # ❌ 自動注入到每個 prompt
    if relevant_skills:
        skills_context = self.skills.build_skills_context(relevant_skills)
        prompt = f"{skills_context}\n\n---\n\n{prompt}"

    return prompt
```

**問題：**
- 每次請求都額外調用 LLM API（慢且昂貴）
- Claude 沒有決定權
- 自動注入可能不需要的 skills

### Claude Code 的實現（正確）

```python
# 1. 註冊 tool
@agent.tool_plain
def use_skill(skill_name: str) -> str:
    """
    Activate a skill to guide your response.

    Available skills:
    - python-tutorial: Python programming tutorial and best practices. Use when...
    - code-review: Provides systematic code review guidance. Use when...
    - debugging-assistant: Systematic debugging guidance. Use when...
    - tool-usage-guide: Guidance on when and how to use tools. Use when...

    Call this tool to activate a skill before processing the user's request.
    """
    skill = registry.get_skill(skill_name)
    if not skill:
        return f"Skill '{skill_name}' not found."

    # 注入 skill 內容到 context
    return skill.content

# 2. Claude 自己決定何時調用
# 用戶：教我 python
# Claude：我應該使用 python-tutorial skill
#        → 調用 use_skill("python-tutorial")
#        → 獲得 skill 內容
#        → 根據 skill 指導回答
```

**優點：**
- 零額外 API 調用
- Claude 完全控制
- 只在需要時載入 skills
- 符合 Progressive Disclosure 原則

## 🔧 正確實現步驟

### 1. 移除自動注入機制

```python
# 刪除 MainAgent._apply_skills()
# 刪除 SubAgent._apply_skills()
# 刪除所有自動 skill 匹配邏輯
```

### 2. 註冊 use_skill tool

```python
def register_skill_tool(agent: Agent, skills: SkillRegistry):
    """Register the use_skill tool with dynamic description."""

    # 構建 tool description（包含所有 skills）
    skills_list = []
    for skill_name in skills.list_names():
        skill = skills.get_skill(skill_name)
        skills_list.append(f"  - {skill.name}: {skill.description}")

    skills_desc = "\n".join(skills_list)

    @agent.tool_plain
    def use_skill(skill_name: str) -> str:
        f"""
        Activate a skill to guide your response with specialized knowledge and methodology.

        Available skills:
        {skills_desc}

        Call this tool BEFORE processing requests that match a skill's domain.
        The skill will provide expert guidance, best practices, and systematic approaches.

        Args:
            skill_name: Name of the skill to activate

        Returns:
            The skill's guidance content
        """
        skill = skills.get_skill(skill_name)
        if not skill:
            available = ", ".join(skills.list_names())
            return f"Skill '{skill_name}' not found. Available: {available}"

        logger.info(f"[Tool] Activated skill: {skill.name}")
        return skill.content
```

### 3. 在 MainAgent 中整合

```python
class MainAgent:
    @classmethod
    def create(cls, ...):
        # ... 創建 agent ...

        # Load skills
        skills = load_skill_registry()

        # Register skill tool
        register_skill_tool(agent, skills)

        # ... 其餘設置 ...
```

## 📈 效果對比

### 之前（錯誤實現）

```
用戶：教我 python

系統：
1. 調用 LLM API 評估 skills 相關性 (~300ms, 成本)
2. 自動注入 python-tutorial skill
3. 處理請求

總時間：~500ms
API 調用：2 次（評估 + 主請求）
成本：高
```

### 之後（正確實現）

```
用戶：教我 python

Claude 思考：
- 看到 use_skill tool description
- 發現 python-tutorial skill 相關
- 決定調用 use_skill("python-tutorial")

系統：
1. Tool 調用返回 skill 內容
2. Claude 根據 skill 指導回答

總時間：~200ms
API 調用：1 次（主請求，包含 tool call）
成本：低
```

## 🎯 關鍵優勢

1. **零額外 API 成本** - 不需要預先評分
2. **更快** - 沒有額外的 LLM 調用
3. **Claude 主導** - 符合 agent 設計哲學
4. **Progressive Disclosure** - 只載入需要的 skills
5. **完全符合 Claude Code** - 官方認可的實現方式

## 📚 參考資源

- [Claude Agent Skills Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [How to Make Claude Code Skills Activate Reliably](https://scottspence.com/posts/how-to-make-claude-code-skills-activate-reliably)
- [Agent Skills - Claude Code Docs](https://code.claude.com/docs/en/skills)
- [GitHub - anthropics/skills](https://github.com/anthropics/skills)

## 🚀 下一步

實現正確的 tool-based skills 系統：

1. 移除 `_apply_skills()` 方法
2. 移除 LLM scoring 機制
3. 實現 `use_skill` tool
4. 更新文檔
5. 測試效果
