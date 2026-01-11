# Skills Tool Description 修復

## 🐛 問題

Agent 無法看到 skills 列表，因為 `use_skill` tool 的 description 是空的。

## 🔍 根本原因

在 `internal/tools/skill_tools.py` 中，使用了 **f-string 作為 docstring**：

```python
@agent.tool_plain
def use_skill(skill_name: str) -> str:
    f"""ACTIVATE A SKILL for expert guidance...

    AVAILABLE SKILLS:
    {skills_desc}
    ...
    """
    # function body
```

**問題：Python 不會將 f-string 識別為函數的 docstring！**

- Docstring 必須是字面字符串（string literal）
- f-string 是表達式，會被忽略
- 結果：`use_skill.__doc__` = `None`
- Agent 看不到任何 skills 列表

## ✅ 解決方案

### 1. 先構建 description 字符串

```python
# Build the tool description (must be done before function definition)
tool_description = f"""ACTIVATE A SKILL for expert guidance on specialized tasks.

*** CRITICAL: You MUST use this tool when the user's request matches ANY skill below. ***

AVAILABLE SKILLS:
{skills_desc}

WHEN TO USE:
1. Read the skill descriptions above carefully
2. If the user's request matches a skill's domain, call this tool FIRST
3. Get the skill's guidance BEFORE formulating your response
4. Follow the skill's methodology exactly

EXAMPLES:
- User asks about Python -> use_skill("python-tutorial")
- User asks to review code -> use_skill("code-review")
...
"""
```

### 2. 通過 decorator 參數傳遞 description

```python
@agent.tool_plain(description=tool_description)
def use_skill(skill_name: str) -> str:
    # function body
```

### 3. 為 SubAgent 也註冊 skill tool

在 `internal/sub_agents/registry.py` 的 `load_sub_agent_registry()` 函數中添加：

```python
if philosopher:
    _register_philosopher_tools(agent, philosopher)
# Register skill tool if skills available
if skills:
    from internal.tools.skill_tools import register_skill_tool
    register_skill_tool(agent, skills)
```

## 📊 驗證結果

測試腳本確認：

```bash
✅ Tool registered: use_skill
✅ Description length: 6916 chars
✅ Contains: CRITICAL, AVAILABLE SKILLS, WHEN TO USE, EXAMPLES
✅ Lists 20 skills:
   - python-tutorial
   - code-review
   - debugging-assistant
   - tool-usage-guide
   - docx, pdf, pptx, xlsx
   - (... 其他 13 個 skills)
```

## 🎯 修復的檔案

1. **`internal/tools/skill_tools.py`**
   - 將 f-string docstring 改為預先構建的 `tool_description`
   - 使用 `@agent.tool_plain(description=tool_description)` 傳遞 description

2. **`internal/sub_agents/registry.py`**
   - 為每個 SubAgent 註冊 `use_skill` tool
   - 確保 SubAgent 也能看到和使用 skills

## 📝 技術細節

### 為什麼 f-string 不能作為 docstring？

```python
# ❌ 錯誤 - f-string 不會被識別為 docstring
def func():
    f"""This is {variable}"""
    pass

print(func.__doc__)  # None

# ✅ 正確 - 字面字符串會被識別
def func():
    """This is a docstring"""
    pass

print(func.__doc__)  # "This is a docstring"
```

### pydantic_ai 的 tool_plain 支持 description 參數

```python
@agent.tool_plain(
    description="Tool description here",
    name="tool_name",
    # ... other options
)
def my_tool(param: str) -> str:
    return result
```

這個 description 會被：
1. 發送給 LLM 作為 tool 的說明
2. 用於 tool calling 時的參考
3. 讓 agent 理解何時使用這個 tool

## 🚀 效果

現在 agent 可以：

1. ✅ 看到完整的 skills 列表（20 個 skills）
2. ✅ 閱讀每個 skill 的描述
3. ✅ 理解何時應該使用哪個 skill
4. ✅ 根據用戶請求主動調用 `use_skill` tool
5. ✅ MainAgent 和 SubAgent 都支持 skills

## 📚 相關文檔

- [Skills Tool-Based Migration](SKILLS_TOOL_BASED_MIGRATION.md)
- [Skills Claude Code Implementation](SKILLS_CLAUDE_CODE_IMPLEMENTATION.md)
- [pydantic_ai Tool Documentation](https://ai.pydantic.dev/tools/)
