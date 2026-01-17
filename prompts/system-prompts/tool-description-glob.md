<!--
name: 'Tool Description: File Listing'
description: File listing and light discovery using file tools
ccVersion: 2.0.77
-->
Use file tools to discover files without the shell.

Usage:
- Use list_files_in_directory to list entries in a directory (non-recursive).
- If you already have a list of file paths, use find_files_with_fragment to filter those files by a regex match in file contents.
- If you need recursive discovery across the entire repo, use run_terminal_command with rg --files or rg when file tools are insufficient.
