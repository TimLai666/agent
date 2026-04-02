<!--
name: 'Tool Description: use_skill'
description: Tool description for executing skills in the main conversation
ccVersion: 2.0.77
-->
Use the use_skill tool to invoke an installed skill.

Guidelines:
- If the user explicitly asks for a skill or uses a slash command (e.g., /commit, /review-pr), call use_skill immediately.
- Do not mention a skill without invoking it.
- Do not call use_skill for built-in CLI commands like /help.
- Provide the skill name and any required args.
