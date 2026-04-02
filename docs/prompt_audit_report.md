# Prompt Audit Report

## Summary
- Total files: 51
- Contains Claude: 0
- Contains Anthropic: 0
- Has template variables: 18

## Per-file Results
| File | Lines | Claude | Anthropic | Template Vars |
|---|---:|:---:|:---:|---|
| prompts/MAIN_AGENT_PROMPT.md | 242 | N | N | ${SYSTEM_NAME} |
| prompts/SKILLS_PRIORITY.md | 25 | N | N | - |
| prompts/system-prompts/agent-prompt-agent-creation-architect.md | 75 | N | N | - |
| prompts/system-prompts/agent-prompt-agent-hook.md | 18 | N | N | ${STRUCTURED_OUTPUT_TOOL_NAME}, ${SYSTEM_NAME}, ${TRANSCRIPT_PATH} |
| prompts/system-prompts/agent-prompt-bash-command-description-writer.md | 16 | N | N | - |
| prompts/system-prompts/agent-prompt-bash-command-file-path-extraction.md | 26 | N | N | - |
| prompts/system-prompts/agent-prompt-bash-command-prefix-detection.md | 73 | N | N | ${COMMAND_STRING}, ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-claude-guide-agent.md | 23 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-claudemd-creation.md | 27 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-command-execution-specialist.md | 18 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-conversation-summarization.md | 100 | N | N | - |
| prompts/system-prompts/agent-prompt-explore.md | 26 | N | N | - |
| prompts/system-prompts/agent-prompt-pr-comments-slash-command.md | 42 | N | N | ${ADDITIONAL_USER_INPUT?"Additional user input: "+ADDITIONAL_USER_INPUT:""}, ${BASH_TOOL_NAME} |
| prompts/system-prompts/agent-prompt-prompt-hook-execution.md | 15 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-prompt-suggestion-generator-v2.md | 36 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-remember-skill.md | 118 | N | N | - |
| prompts/system-prompts/agent-prompt-review-pr-slash-command.md | 32 | N | N | ${BASH_TOOL_NAME}, ${PR_NUMBER_ARG} |
| prompts/system-prompts/agent-prompt-security-review-slash.md | 196 | N | N | - |
| prompts/system-prompts/agent-prompt-session-notes-template.md | 35 | N | N | - |
| prompts/system-prompts/agent-prompt-session-notes-update-instructions.md | 44 | N | N | ${MAX_SECTION_TOKENS} |
| prompts/system-prompts/agent-prompt-session-search-assistant.md | 39 | N | N | - |
| prompts/system-prompts/agent-prompt-session-title-and-branch-generation.md | 30 | N | N | - |
| prompts/system-prompts/agent-prompt-status-line-setup.md | 106 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/agent-prompt-update-magic-docs.md | 55 | N | N | - |
| prompts/system-prompts/agent-prompt-user-sentiment-analysis.md | 18 | N | N | ${CONVERSATION_HISTORY} |
| prompts/system-prompts/data-github-actions-workflow-for-claude-mentions.md | 54 | N | N | ${SYSTEM_NAME}, ${{ secrets.AI_PROVIDER_API_KEY } |
| prompts/system-prompts/data-github-app-installation-pr-description.md | 47 | N | N | ${SYSTEM_NAME} |
| prompts/system-prompts/greeting-time-check.md | 154 | N | N | - |
| prompts/system-prompts/system-prompt-autonomous-agent-standalone.md | 20 | N | N | - |
| prompts/system-prompts/system-prompt-censoring-assistance-with-malicious-activities.md | 6 | N | N | - |
| prompts/system-prompts/system-prompt-chrome-browser-mcp-tools.md | 16 | N | N | - |
| prompts/system-prompts/system-prompt-claude-in-chrome-browser-automation.md | 52 | N | N | - |
| prompts/system-prompts/system-prompt-git-status.md | 20 | N | N | ${CURRENT_BRANCH}, ${GIT_STATUS||"(clean)"}, ${MAIN_BRANCH}, ${RECENT_COMMITS} |
| prompts/system-prompts/system-prompt-learning-mode-insights.md | 14 | N | N | - |
| prompts/system-prompts/system-prompt-learning-mode.md | 28 | N | N | - |
| prompts/system-prompts/system-prompt-main-system-prompt.md | 36 | N | N | ${SECURITY_POLICY} |
| prompts/system-prompts/system-prompt-scratchpad-directory.md | 23 | N | N | ${SCRATCHPAD_DIR_FN()} |
| prompts/system-prompts/tool-description-bash-git-commit-and-pr-creation-instructions.md | 56 | N | N | - |
| prompts/system-prompts/tool-description-bash-sandbox-note.md | 16 | N | N | - |
| prompts/system-prompts/tool-description-bash.md | 31 | N | N | - |
| prompts/system-prompts/tool-description-computer.md | 9 | N | N | - |
| prompts/system-prompts/tool-description-edit.md | 12 | N | N | - |
| prompts/system-prompts/tool-description-glob.md | 11 | N | N | - |
| prompts/system-prompts/tool-description-grep.md | 12 | N | N | - |
| prompts/system-prompts/tool-description-playwright.md | 118 | N | N | - |
| prompts/system-prompts/tool-description-readfile.md | 17 | N | N | - |
| prompts/system-prompts/tool-description-skill.md | 12 | N | N | - |
| prompts/system-prompts/tool-description-websearch.md | 22 | N | N | - |
| prompts/system-prompts/tool-description-write.md | 12 | N | N | - |
| prompts/system-prompts/tool-parameter-computer-action-for-computer-tool.md | 19 | N | N | - |
| prompts/SYSTEM_PROMPT.md | 72 | N | N | - |