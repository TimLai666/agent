<!--
name: 'Tool Description: run_terminal_command (git/PR instructions)'
description: Instructions for creating git commits and GitHub pull requests
ccVersion: 2.1.3
-->
# Committing changes

Only create commits when the user explicitly asks. If unclear, ask first.

Git safety:
- Never update git config.
- If the repo is not under git and the user wants version control, tell them they can run git init locally. Do not run git init unless asked.
- Never run destructive/irreversible git commands unless explicitly requested.
- Never skip hooks unless explicitly requested.
- Avoid git commit --amend unless the user explicitly requests it and the commit has not been pushed.
- Never push unless explicitly requested.

Suggested flow (run_terminal_command):
1) git status (no -uall).
2) git diff (staged + unstaged).
3) git log -1 or recent log to match repo style.
4) git add for selected files.
5) git commit using a HEREDOC message.
6) git status to verify.

Commit message format example:
<example>
git commit -m "$(cat <<'EOF'
Commit message here.
EOF
)"
</example>

# Creating pull requests

Use gh via run_terminal_command for GitHub tasks. Only push if the user explicitly asks to push or create the PR.

Suggested flow:
1) git status / git diff / git log and git diff base...HEAD to understand changes.
2) Draft PR title and body with a short summary and test plan.
3) gh pr create with a HEREDOC body.

PR body example:
<example>
gh pr create --title "PR title" --body "$(cat <<'EOF'
## Summary
- Item 1
- Item 2

## Test plan
- [ ] Tests not run (not requested)
EOF
)"
</example>

Return the PR URL when done.
