<!--
name: 'Tool Description: modify_existing_file'
description: Tool description for editing existing files
ccVersion: 2.0.77
-->
Modify an existing file by providing the full new content.

Usage:
- Always read the file first with read_file.
- Provide the complete updated content to modify_existing_file.
- Preserve unchanged content and formatting unless the user asked otherwise.
- Avoid creating new files; use create_new_file only when needed.
