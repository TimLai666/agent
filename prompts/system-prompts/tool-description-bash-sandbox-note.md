<!--
name: 'Tool Description: run_terminal_command (sandbox note)'
description: Note about command sandboxing and escalation
ccVersion: 2.0.77
-->
Commands run sandboxed by default.

Use sandbox_permissions: "require_escalated" only when needed, for example:
- The command fails due to sandbox restrictions and the task cannot proceed without escalation.
- The command needs access outside allowed directories.
- The command requires network access when restricted.
- The command would open a GUI or perform a potentially destructive action that needs explicit approval.

When escalating:
- Include a one-sentence justification explaining why escalation is required.
- Re-run the same command with sandbox_permissions set.
