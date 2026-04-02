<!--
name: 'Tool Description: run_terminal_command'
description: Description for running terminal commands
ccVersion: 2.1.5
-->
Run a terminal command with run_terminal_command.

Use cases:
- git, build, test, package managers, or other true shell operations.
- Do not use the shell for file reads/writes/searches when file tools can do the job.

Git policy:
- If a repo is not initialized, tell the user they can run git init themselves. Do not run git init unless the user asks.
- Never push to a remote unless the user explicitly asks.

Command hygiene:
- Quote paths with spaces.
- If a command will create files/directories, check the parent directory first (list_files_in_directory or ls).
- Prefer absolute paths; avoid changing directories unless the user requests it.

Parallel vs sequential:
- If commands are independent, run multiple tool calls in a single response.
- If commands depend on each other, chain with && in one command.

Prefer file tools for:
- list_files_in_directory
- find_files_with_fragment
- find_all_lines_in_file_with_fragment
- read_file
- modify_existing_file
- create_new_file
