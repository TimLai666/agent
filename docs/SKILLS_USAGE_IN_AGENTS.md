# Skills 在 MainAgent 和 SubAgent 中的使用

## ✅ 現在的狀況

**MainAgent 和所有 SubAgent 都會自動使用 Skills！**

## 🔄 工作流程

### 1. Skills 載入順序

```python
# 在 MainAgent.create() 中：

# Step 1: 載入 skills（優先）
skills = load_skill_registry()

# Step 2: 載入 sub-agents（傳入 skills）
sub_agents = load_sub_agent_registry(
    base_config, env, http_client,
    philosopher=philosopher,
    skills=skills  # ← 傳入 skills！
)

# Step 3: 創建 MainAgent
main_agent = MainAgent(agent, philosopher, sub_agents, ..., skills)
```

### 2. Skills 應用流程

#### MainAgent 執行

```
用戶輸入 → MainAgent.run()
         ↓
         _apply_skills(prompt)  # ← 激活相關 skills
         ↓
         執行 agent.run(enhanced_prompt)
```

#### SubAgent 執行

```
MainAgent 調用 → SubAgent.run(prompt)
              ↓
              _apply_skills(prompt)  # ← SubAgent 也有！
              ↓
              執行 agent.run(enhanced_prompt)
```

## 📊 架構圖

```
┌─────────────────────────────────────────┐
│          SkillRegistry                  │
│  (共享給 MainAgent 和所有 SubAgents)     │
└─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐      ┌────────────────┐
│  MainAgent    │      │  SubAgent 1    │
│               │      │                │
│ - _skills ────┼──────┤ - _skills      │
│ - _apply_skills() │  │ - _apply_skills() │
└───────────────┘      └────────────────┘
                              │
                              ▼
                       ┌────────────────┐
                       │  SubAgent 2    │
                       │                │
                       │ - _skills      │
                       │ - _apply_skills() │
                       └────────────────┘
```

## 🎯 實際執行示例

### 場景 1：MainAgent 直接處理

```python
# 用戶輸入
"Can you review this code?"

# MainAgent 流程
1. MainAgent._apply_skills()
   → 匹配到 "code-review" skill
   → 注入 skill 內容到 prompt

2. MainAgent.agent.run(enhanced_prompt)
   → Agent 使用 code-review 指導
```

### 場景 2：調用 SubAgent

```python
# 用戶輸入（帶 @sub-agent）
"@researcher find information about Python typing"

# 執行流程
1. MainAgent 識別 @researcher

2. 調用 SubAgent.run("find information about Python typing")

3. SubAgent._apply_skills()
   → 匹配到 "python-tutorial" skill
   → 注入 skill 內容

4. SubAgent.agent.run(enhanced_prompt)
   → SubAgent 使用 python-tutorial 指導
```

### 場景 3：智能選擇不同 Skills

```python
# MainAgent 處理代碼審查
MainAgent.run("Review my code")
→ 激活：code-review skill

# SubAgent 處理 Python 問題
SubAgent.run("Explain Python decorators")
→ 激活：python-tutorial skill

# SubAgent 處理除錯
SubAgent.run("Help me fix this bug")
→ 激活：debugging-assistant skill
```

## 🔍 代碼實現細節

### SubAgent.base.py

```python
class SubAgent:
    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: PhilosopherCoAgent | None = None,
        skills: Optional[SkillRegistry] = None,  # ← 新增
    ):
        self.agent = agent
        self._philosopher = philosopher
        self._skills = skills  # ← 存儲 skills

    def _apply_skills(self, prompt: str) -> str:
        """Apply relevant skills (與 MainAgent 相同邏輯)."""
        if not self._skills or self._skills.is_empty():
            return prompt

        # 找相關 skills
        relevant_skills = self._skills.find_relevant_skills(prompt)

        if not relevant_skills:
            return prompt

        # 建構 skills context
        skills_context = self._skills.build_skills_context(relevant_skills)

        if skills_context:
            logger.info(
                "[SubAgent] Activated skills: %s",
                ", ".join([s.name for s in relevant_skills])
            )
            prompt = f"{skills_context}\n\n---\n\n{prompt}"

        return prompt

    async def run(self, prompt: str) -> str:
        # 應用 skills
        if self._skills:
            prompt = self._apply_skills(prompt)  # ← 關鍵！

        result = await self.agent.run(prompt)
        return result.output
```

### SubAgent.registry.py

```python
def load_sub_agent_registry(
    base_config: AgentConfig,
    env: dict[str, str],
    http_client: AsyncClient,
    root_dir: Path | None = None,
    philosopher: PhilosopherCoAgent | None = None,
    skills: Optional[Any] = None,  # ← 新增參數
) -> SubAgentRegistry:
    # ...

    for spec in specs:
        # 創建 Agent
        agent = Agent(...)

        # 創建 SubAgent（傳入 skills）
        agents[key] = SubAgent(
            agent,
            philosopher=philosopher,
            skills=skills  # ← 傳入！
        )
```

## 📝 日誌輸出

當 skills 被激活時，你會看到：

```
# MainAgent 激活 skill
INFO - Activated skills: code-review

# SubAgent 激活 skill
INFO - [SubAgent] Activated skills: python-tutorial
```

## ⚙️ 配置選項

### 禁用 Skills（如果需要）

```python
# MainAgent 不使用 skills
main_agent = MainAgent.create(
    ...,
    skills=SkillRegistry({}, None)  # 空 registry
)

# SubAgent 不使用 skills
sub_agents = load_sub_agent_registry(
    ...,
    skills=None  # 不傳入 skills
)
```

### 只給 MainAgent 使用 Skills

```python
# MainAgent 使用 skills
skills = load_skill_registry()

# SubAgent 不使用 skills
sub_agents = load_sub_agent_registry(
    ...,
    skills=None  # ← 傳 None
)

main_agent = MainAgent.create(
    ...,
    sub_agents=sub_agents,
    skills=skills  # ← MainAgent 有 skills
)
```

### 共享 Skills（預設，推薦）

```python
# 載入一次 skills
skills = load_skill_registry()

# 傳給 sub-agents
sub_agents = load_sub_agent_registry(..., skills=skills)

# 傳給 main agent
main_agent = MainAgent.create(..., sub_agents=sub_agents, skills=skills)
```

## 🎯 優勢

### 1. 一致性

MainAgent 和 SubAgent 都使用相同的 skills 系統，行為一致。

### 2. 記憶體效率

所有 agents 共享同一個 SkillRegistry，不會重複載入。

### 3. 智能激活

每個 agent 根據自己的任務獨立選擇相關 skills：
- MainAgent 處理代碼審查 → 激活 code-review
- SubAgent 處理 Python 問題 → 激活 python-tutorial

### 4. 靈活配置

可以選擇：
- 所有 agents 都用 skills（預設）
- 只有 MainAgent 用 skills
- 都不用 skills

## 📊 性能影響

### 記憶體

```
Skills 載入一次：~400 tokens metadata
共享給所有 agents：無額外開銷
```

### 速度

```
每個 agent 執行時：
- 關鍵詞匹配：~1-2ms
- LLM 評分：~100-500ms（如果啟用）
```

## ✅ 總結

**問題：MainAgent 跟所有 SubAgent 都會自己使用嗎？**

**答案：✅ 是的！**

- ✅ MainAgent 會使用 skills
- ✅ 所有 SubAgent 也會使用 skills
- ✅ 共享同一個 SkillRegistry（記憶體效率）
- ✅ 各自獨立激活相關 skills（智能選擇）
- ✅ 使用相同的 `_apply_skills()` 邏輯（一致性）

每個 agent 都會根據收到的 prompt 自動找出並應用最相關的 skills！
