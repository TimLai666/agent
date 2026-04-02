<!--
name: 'Tool Description: Subagents'
description: Tools for delegating to subagents (list_sub_agents, ask_sub_agent)
ccVersion: 2.1.4
-->
Use subagent tools to delegate specialized or parallel work.

Tools:
- list_sub_agents: list available subagents and their short descriptions.
- ask_sub_agent: call a specific subagent by name with a prompt.

Guidelines:
- Use list_sub_agents when you are unsure which subagent fits.
- Use ask_sub_agent for complex, multi-step tasks or domain-specific help.
- Provide a clear, scoped prompt and specify the output you want.
- Summarize the subagent result back to the user.
- You can call multiple subagents in parallel when the tasks are independent.
