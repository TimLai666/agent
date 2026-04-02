<!--
name: 'Tool Description: Content Search'
description: Content search guidance using file tools
ccVersion: 2.0.77
-->
Search file contents using file tools.

Usage:
- Use find_all_lines_in_file_with_fragment to search within a specific file (regex supported).
- For searching across a known list of files, use find_files_with_fragment with that list.
- If you need fast recursive search across the repo, use run_terminal_command with rg.
- Prefer file tools over shell grep/rg when the scope is small.
