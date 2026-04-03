# COMMAND USAGE PRACTICE

## Primary Execution Rule

- Default to terminal commands for task execution whenever feasible.
- Prefer one clear command at a time; chain only when dependencies are explicit.
- If a command can complete the task reliably, do NOT switch to non-terminal tools.

## Task Decomposition Into Terminal Commands

- Before running commands, decompose the user request into atomic command tasks.
- Use this sequence for every non-trivial request:
  1. Clarify target and scope (what path, what files, what output).
  2. Inspect current state (directory, file existence, environment, versions).
  3. Execute minimal safe commands for each subtask.
  4. Verify outputs after each subtask before moving on.
  5. Summarize completion and unresolved items.

- Command planning rules:
  - Prefer multiple short deterministic commands over one long complex command.
  - Avoid hidden side effects; separate read/verify/write stages.
  - Keep commands idempotent when possible.
  - Use absolute paths for file operations when ambiguity exists.

- For write operations, enforce a 3-step pattern:
  1. Read current content with explicit encoding.
  2. Apply update with explicit encoding.
  3. Re-read or diff to confirm expected result.

- For search/refactor operations, enforce a 3-step pattern:
  1. Discover candidate files.
  2. Search exact patterns.
  3. Validate all matches before any write command.

## File Read/Write via Commands

- Always treat text encoding explicitly when reading or writing files.
- On Windows PowerShell:
  - Prefer `Get-Content -Encoding UTF8` for reads.
  - Prefer `Set-Content -Encoding UTF8` / `Out-File -Encoding utf8` for writes.
- On POSIX shells:
  - Assume UTF-8 but verify if output looks garbled.
  - Use tools that preserve exact bytes/newlines when required.

- Always include encoding in command design when reading/writing text files.
- Never assume terminal default encoding is correct for multilingual content.

## Long Output and Truncation Control

- Assume terminal output may be truncated.
- For large files or outputs:
  - Read in chunks/pages (for example by line ranges).
  - Use filtering and narrowing before printing full output.
  - Prefer targeted extraction over dumping entire content.
- If truncation risk exists, explicitly split the task into multiple bounded command reads.

- When reading large files, use bounded line windows and iterate:
  - Read first window.
  - Decide next window from context.
  - Continue until enough evidence is collected.

## Safety and Reliability

- Keep to non-destructive commands unless user explicitly requests destructive operations.
- Validate command results before continuing to the next step.
- When command output is ambiguous, run a focused follow-up command to verify.
