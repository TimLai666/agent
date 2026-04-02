<!--
name: 'Tool Description: read_file'
description: Tool description for reading files
ccVersion: 2.0.77
-->
Read text files from the local filesystem.

Usage:
- Use read_file for text-based files (code, configs, markdown).
- Use read_image_resized for images (jpg/png/etc.). It resizes and compresses before sending to the model.
- Use read_binary_file for non-image binary data (zip, pdf, etc.).
- Provide an absolute file path.
- If a file does not exist or is empty, the tool will return an error message or empty content.

Notes:
- Do not use the terminal to read files when read_file works.
- You can read multiple files in parallel when they are independent.
