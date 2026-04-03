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

## Regex Command Usage (All Terminal Types)

- Use regex-capable terminal commands for precise matching and replacement.
- Always choose commands that match the active shell and toolchain.
- Preferred regex tools by environment:
  - PowerShell: `Select-String`, `-match`, `-replace`, `[regex]::Matches(...)`
  - bash/zsh: `grep -E`, `rg`, `sed -E`, `perl -pe` / `perl -0777 -pe`
  - cmd.exe: `findstr /R` for simple regex search; use `powershell` or `perl` for advanced replacement
  - Cross-platform fast search: `rg` (ripgrep) first when available

- Regex execution workflow:
  1. Run a read-only regex search and confirm match count.
  2. Narrow scope to the intended file/line window.
  3. Apply replacement only when the match is unique or explicitly approved.
  4. Re-run search to verify result after replacement.

- Command patterns (reference):
  - PowerShell search: `Select-String -Path <file> -Pattern '<regex>'`
  - PowerShell replace preview: `(Get-Content <file> -Raw) -replace '<regex>','<replacement>'`
  - bash/zsh search: `rg -n '<regex>' <path>` or `grep -R -nE '<regex>' <path>`
  - bash/zsh replace (file): `sed -E 's/<regex>/<replacement>/g' <file>`
  - perl multiline replace: `perl -0777 -pe 's/<regex>/<replacement>/g' <file>`
  - cmd simple search: `findstr /S /N /R "<regex>" *.*`

- Replacement safety rules:
  - Do NOT run broad regex replacement across many files without pre-check.
  - If match count > 1 and user did not ask for bulk edits, stop and refine pattern.
  - Preserve encoding explicitly during write-back (`UTF8` on PowerShell).
  - Re-read changed lines to prevent accidental over-replacement.
  - For `sed -i` or in-place edits, create backup or validate against preview output first.
  - For cmd.exe workflows, avoid complex in-place regex edits directly in cmd.

- Platform note:
  - Regex flavor differs by tool (PowerShell .NET regex vs grep/sed/perl variants).
  - `findstr` regex support is limited compared with .NET/perl/PCRE engines.
  - If portability is uncertain, run read-only search first in active shell, then choose the safest replace tool.

## Safety and Reliability

- Keep to non-destructive commands unless user explicitly requests destructive operations.
- Validate command results before continuing to the next step.
- When command output is ambiguous, run a focused follow-up command to verify.
