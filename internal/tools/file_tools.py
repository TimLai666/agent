import base64
import io
import mimetypes
import os
import re
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent

from internal.cli import confirm
from internal.logger import logger

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


def add_file_tools(agent: Agent) -> None:
    """Add file-related tools to the agent."""

    file_tools_manager: FileTools = FileTools()

    @agent.tool_plain
    def find_files_with_fragment(fragment_regx: str, files: list[str]) -> list[str]:
        """Find files containing a specific fragment in their names.

        Parameters:
            fragment_regx (str): The fragment to search for (in regular expression).
            files (list[str]): The list of files to search within.

        Returns:
            list[str]: A list of matching file names.
        """
        return file_tools_manager.find_files_with_fragment(fragment_regx, files)

    @agent.tool_plain
    def find_all_lines_in_file_with_fragment(
        fragment_regx: str, file_path: str
    ) -> list[str]:
        """Find all lines in a file that contain a specific fragment.

        Parameters:
            fragment_regx (str): The fragment to search for (in regular expression).
            file_path (str): The path to the file to search within.

        Returns:
            list[str]: A list of matching lines.
        """
        return file_tools_manager.find_all_lines_in_file_with_fragment(
            fragment_regx, file_path
        )

    @agent.tool_plain
    def read_file(file_path: str) -> str:
        """Read the contents of a file."""
        return file_tools_manager.read_file(file_path)

    @agent.tool_plain
    def read_file_with_line_numbers(
        file_path: str,
        start_line: int = 1,
        end_line: int = 200,
    ) -> str:
        """Read a file with 1-based line numbers for easier code editing."""
        return file_tools_manager.read_file_with_line_numbers(
            file_path,
            start_line,
            end_line,
        )

    @agent.tool_plain
    def read_binary_file(file_path: str, max_bytes: int = 10 * 1024 * 1024) -> list[Any] | str:
        """Read a binary file and return base64 with metadata."""
        return file_tools_manager.read_binary_file(file_path, max_bytes)

    @agent.tool_plain
    def read_image_resized(
        image_path: str,
        max_dim: int = 1024,
        max_bytes: int = 2 * 1024 * 1024,
        output_format: str = "jpeg",
        jpeg_quality: int = 85,
    ) -> list[Any] | str:
        """Read an image, resize it, and return image content for the agent."""
        return file_tools_manager.read_image_resized(
            image_path,
            max_dim,
            max_bytes,
            output_format,
            jpeg_quality,
        )

    @agent.tool_plain
    def modify_existing_file(file_path: str, content: str) -> str:
        """Modify an existing file with new content."""
        return file_tools_manager.modify_existing_file(file_path, content)

    @agent.tool_plain
    def replace_lines_in_file(
        file_path: str,
        start_line: int,
        end_line: int,
        new_content: str,
    ) -> str:
        """Replace a line range in a text file using 1-based line numbers."""
        return file_tools_manager.replace_lines_in_file(
            file_path,
            start_line,
            end_line,
            new_content,
        )

    @agent.tool_plain
    def replace_line_in_file(
        file_path: str,
        line_number: int,
        new_content: str,
    ) -> str:
        """Replace exactly one line in a text file using 1-based line number."""
        return file_tools_manager.replace_line_in_file(
            file_path,
            line_number,
            new_content,
        )

    @agent.tool_plain
    def insert_line_in_file(
        file_path: str,
        line_number: int,
        content: str,
    ) -> str:
        """Insert content before the given 1-based line number in a text file."""
        return file_tools_manager.insert_line_in_file(
            file_path,
            line_number,
            content,
        )

    @agent.tool_plain
    def delete_lines_in_file(
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """Delete a line range from a text file using 1-based line numbers."""
        return file_tools_manager.delete_lines_in_file(
            file_path,
            start_line,
            end_line,
        )

    @agent.tool_plain
    def create_new_file(file_path: str, content: str) -> str:
        """Create a new file with the content."""
        return file_tools_manager.create_new_file(file_path, content)


class FileTools:
    """A class to encapsulate file-related tools."""

    def __init__(self) -> None:
        self.base_path: str = os.getcwd()

    def find_files_with_fragment(
        self, fragment_regx: str, files: list[str]
    ) -> list[str]:
        logger.info(f"Finding matches in {files} with fragment: {fragment_regx}")
        try:
            matching_files: list[str] = []
            for file in files:
                with open(file, "r", encoding="utf-8") as f:
                    file_content = f.read()
                if re.search(fragment_regx, file_content):
                    matching_files.append(file)
            if not matching_files:
                return [f"No files found matching regex '{fragment_regx}'."]
            return matching_files
        except Exception as e:
            logger.error(f"Error finding files with fragment {fragment_regx}: {str(e)}")
            return [str(e)]

    def find_all_lines_in_file_with_fragment(
        self, fragment_regx: str, file_path: str
    ) -> list[str]:
        logger.info(f"Finding all lines in file with fragment: {fragment_regx}")
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
            if not content:
                return [f"File '{file_path}' is empty or not found."]
            matches = [
                line for line in content.splitlines() if re.search(fragment_regx, line)
            ]
            if not matches:
                return [
                    f"No matches found in file '{file_path}' for fragment: {fragment_regx}"
                ]
            return matches
        except Exception as e:
            logger.error(f"Error finding fragment in file {file_path}: {str(e)}")
            return [str(e)]

    def read_file(self, file_path: str) -> str:
        logger.info(f"Reading file: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return file.read()
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {str(e)}")
            return str(e)

    def read_file_with_line_numbers(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        logger.info(
            f"Reading file with line numbers: {file_path} ({start_line}-{end_line})"
        )
        try:
            if start_line < 1:
                return "Error: start_line must be >= 1."
            if end_line < start_line:
                return "Error: end_line must be >= start_line."

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            if not lines:
                return f"File '{file_path}' is empty."

            total_lines = len(lines)
            if start_line > total_lines:
                return (
                    f"Error: start_line {start_line} exceeds total lines {total_lines}."
                )

            actual_end_line = min(end_line, total_lines)
            width = len(str(total_lines))
            numbered_lines = []
            for index in range(start_line - 1, actual_end_line):
                line_no = str(index + 1).rjust(width, "0")
                numbered_lines.append(f"{line_no}: {lines[index].rstrip('\\r\\n')}\n")

            return (
                f"file: {file_path}\n"
                f"total_lines: {total_lines}\n"
                f"showing: {start_line}-{actual_end_line}\n"
                + "".join(numbered_lines)
            )
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(
                f"Error reading file with line numbers {file_path}: {str(e)}"
            )
            return str(e)

    def read_binary_file(self, file_path: str, max_bytes: int) -> list[Any] | str:
        logger.info(f"Reading binary file: {file_path}")
        try:
            if max_bytes <= 0:
                raise ValueError("max_bytes must be positive.")
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"File '{file_path}' not found.")
            size = os.path.getsize(file_path)
            if size > max_bytes:
                raise ValueError(
                    f"File size {size} exceeds max_bytes {max_bytes}."
                )
            with open(file_path, "rb") as file:
                raw = file.read()
            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            media_ok = (
                mime.startswith("image/")
                or mime.startswith("audio/")
                or mime.startswith("video/")
                or mime in {
                    "application/pdf",
                    "text/plain",
                    "text/csv",
                    "text/markdown",
                    "text/html",
                    "application/msword",
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }
            )
            if media_ok:
                return [
                    f"Binary file {len(raw)} bytes ({mime}).",
                    BinaryContent(data=raw, media_type=mime),
                ]
            b64 = base64.b64encode(raw).decode("ascii")
            return (
                f"mime_type: {mime}\n"
                f"size_bytes: {len(raw)}\n"
                f"base64:\n{b64}"
            )
        except Exception as e:
            logger.error(f"Error reading binary file {file_path}: {str(e)}")
            return str(e)

    def read_image_resized(
        self,
        image_path: str,
        max_dim: int,
        max_bytes: int,
        output_format: str,
        jpeg_quality: int,
    ) -> list[Any] | str:
        logger.info(f"Reading image with resize: {image_path}")
        if Image is None:
            return "Error: Pillow is required for image resizing."
        if max_dim <= 0:
            return "Error: max_dim must be positive."
        if max_bytes <= 0:
            return "Error: max_bytes must be positive."

        path = os.path.expanduser(image_path)
        if not os.path.isfile(path):
            return f"Error: file not found: {path}"

        fmt = (output_format or "jpeg").lower()
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt not in {"jpeg", "png", "webp"}:
            return "Error: output_format must be jpeg, png, or webp."

        try:
            with Image.open(path) as im:
                if fmt in {"jpeg", "webp"}:
                    im = im.convert("RGB")
                else:
                    im = im.convert("RGBA")

                w, h = im.size
                scale = min(max_dim / max(w, h), 1.0)
                if scale < 1.0:
                    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                    im = im.resize(new_size, Image.Resampling.LANCZOS)

                def encode_image(image: Any, quality_value: int) -> bytes:
                    buffer = io.BytesIO()
                    save_kwargs: dict[str, Any] = {}
                    if fmt == "jpeg":
                        save_kwargs.update(quality=quality_value, optimize=True)
                    elif fmt == "webp":
                        save_kwargs.update(quality=quality_value)
                    elif fmt == "png":
                        save_kwargs.update(optimize=True)
                    image.save(buffer, format=fmt.upper(), **save_kwargs)
                    return buffer.getvalue()

                quality = max(1, min(jpeg_quality, 95))
                data = encode_image(im, quality)

                if fmt in {"jpeg", "webp"}:
                    while len(data) > max_bytes and quality > 20:
                        quality -= 5
                        data = encode_image(im, quality)

                while len(data) > max_bytes:
                    new_w = int(im.width * 0.85)
                    new_h = int(im.height * 0.85)
                    if new_w < 64 or new_h < 64:
                        break
                    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    data = encode_image(im, quality)

                if len(data) > max_bytes:
                    return f"Error: resized image exceeds max_bytes ({len(data)} > {max_bytes})."

                mime_map = {
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "webp": "image/webp",
                }
                mime = mime_map[fmt]
                return [
                    f"Resized image {im.width}x{im.height} ({len(data)} bytes).",
                    BinaryContent(data=data, media_type=mime),
                ]
        except Exception as e:
            logger.error(f"Error resizing image {path}: {str(e)}")
            return f"Error: image resize failed: {e}"

    def modify_existing_file(self, file_path: str, content: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to modify file '{file_path}', allow?",
                default_choice="Y",
            ):
                logger.info(f"User denied file modification: {file_path}")
                raise PermissionError("❌ User denied permission to modify this file. The operation was cancelled.")
            logger.info(f"Modifying file: {file_path}")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
            return f"File '{file_path}' modified successfully."
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(f"Error modifying file {file_path}: {str(e)}")
            return str(e)

    def replace_lines_in_file(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        new_content: str,
    ) -> str:
        try:
            if start_line < 1:
                return "Error: start_line must be >= 1."
            if end_line < start_line:
                return "Error: end_line must be >= start_line."

            if not confirm(
                message=(
                    "Agent wants to replace lines "
                    f"{start_line}-{end_line} in '{file_path}', allow?"
                ),
                default_choice="Y",
            ):
                logger.info(
                    f"User denied line replacement: {file_path} ({start_line}-{end_line})"
                )
                raise PermissionError(
                    "❌ User denied permission to modify this file. The operation was cancelled."
                )

            logger.info(
                f"Replacing lines in file: {file_path} ({start_line}-{end_line})"
            )
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            total_lines = len(lines)
            if total_lines == 0:
                return f"Error: File '{file_path}' is empty."
            if end_line > total_lines:
                return f"Error: end_line {end_line} exceeds total lines {total_lines}."

            newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"

            replacement_lines = new_content.splitlines(keepends=True)
            if (
                replacement_lines
                and not replacement_lines[-1].endswith(("\n", "\r"))
                and end_line < total_lines
            ):
                replacement_lines[-1] = replacement_lines[-1] + newline

            updated_lines = (
                lines[: start_line - 1] + replacement_lines + lines[end_line:]
            )

            with open(file_path, "w", encoding="utf-8") as file:
                file.writelines(updated_lines)

            return (
                f"Replaced lines {start_line}-{end_line} in '{file_path}' successfully. "
                f"Total lines: {total_lines} -> {len(updated_lines)}."
            )
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(
                f"Error replacing lines in file {file_path}: {str(e)}"
            )
            return str(e)

    def replace_line_in_file(
        self,
        file_path: str,
        line_number: int,
        new_content: str,
    ) -> str:
        return self.replace_lines_in_file(
            file_path=file_path,
            start_line=line_number,
            end_line=line_number,
            new_content=new_content,
        )

    def insert_line_in_file(
        self,
        file_path: str,
        line_number: int,
        content: str,
    ) -> str:
        try:
            if line_number < 1:
                return "Error: line_number must be >= 1."

            if not confirm(
                message=(
                    "Agent wants to insert content before line "
                    f"{line_number} in '{file_path}', allow?"
                ),
                default_choice="Y",
            ):
                logger.info(
                    f"User denied line insertion: {file_path} (before line {line_number})"
                )
                raise PermissionError(
                    "❌ User denied permission to modify this file. The operation was cancelled."
                )

            logger.info(
                f"Inserting content into file: {file_path} (before line {line_number})"
            )
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            total_lines = len(lines)
            if line_number > total_lines + 1:
                return (
                    f"Error: line_number {line_number} exceeds allowed max {total_lines + 1}."
                )

            newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
            insert_lines = content.splitlines(keepends=True)
            if insert_lines and not insert_lines[-1].endswith(("\n", "\r")):
                insert_lines[-1] = insert_lines[-1] + newline

            updated_lines = (
                lines[: line_number - 1] + insert_lines + lines[line_number - 1 :]
            )

            with open(file_path, "w", encoding="utf-8") as file:
                file.writelines(updated_lines)

            return (
                f"Inserted content before line {line_number} in '{file_path}' successfully. "
                f"Total lines: {total_lines} -> {len(updated_lines)}."
            )
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(
                f"Error inserting content into file {file_path}: {str(e)}"
            )
            return str(e)

    def delete_lines_in_file(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        try:
            if start_line < 1:
                return "Error: start_line must be >= 1."
            if end_line < start_line:
                return "Error: end_line must be >= start_line."

            if not confirm(
                message=(
                    "Agent wants to delete lines "
                    f"{start_line}-{end_line} in '{file_path}', allow?"
                ),
                default_choice="Y",
            ):
                logger.info(
                    f"User denied line deletion: {file_path} ({start_line}-{end_line})"
                )
                raise PermissionError(
                    "❌ User denied permission to modify this file. The operation was cancelled."
                )

            logger.info(
                f"Deleting lines in file: {file_path} ({start_line}-{end_line})"
            )
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            total_lines = len(lines)
            if total_lines == 0:
                return f"Error: File '{file_path}' is empty."
            if end_line > total_lines:
                return f"Error: end_line {end_line} exceeds total lines {total_lines}."
            if start_line == 1 and end_line == total_lines:
                return "Error: refusing to delete all lines. Use modify_existing_file for full replacement."

            updated_lines = lines[: start_line - 1] + lines[end_line:]

            with open(file_path, "w", encoding="utf-8") as file:
                file.writelines(updated_lines)

            return (
                f"Deleted lines {start_line}-{end_line} in '{file_path}' successfully. "
                f"Total lines: {total_lines} -> {len(updated_lines)}."
            )
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(
                f"Error deleting lines in file {file_path}: {str(e)}"
            )
            return str(e)

    def delete_lines_in_file(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        try:
            if start_line < 1:
                return "Error: start_line must be >= 1."
            if end_line < start_line:
                return "Error: end_line must be >= start_line."

            if not confirm(
                message=(
                    "Agent wants to delete lines "
                    f"{start_line}-{end_line} in '{file_path}', allow?"
                ),
                default_choice="Y",
            ):
                logger.info(
                    f"User denied line deletion: {file_path} ({start_line}-{end_line})"
                )
                raise PermissionError(
                    "❌ User denied permission to modify this file. The operation was cancelled."
                )

            logger.info(
                f"Deleting lines in file: {file_path} ({start_line}-{end_line})"
            )
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            total_lines = len(lines)
            if total_lines == 0:
                return f"Error: File '{file_path}' is empty."
            if end_line > total_lines:
                return f"Error: end_line {end_line} exceeds total lines {total_lines}."

            updated_lines = lines[: start_line - 1] + lines[end_line:]

            with open(file_path, "w", encoding="utf-8") as file:
                file.writelines(updated_lines)

            return (
                f"Deleted lines {start_line}-{end_line} in '{file_path}' successfully. "
                f"Total lines: {total_lines} -> {len(updated_lines)}."
            )
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(
                f"Error deleting lines in file {file_path}: {str(e)}"
            )
            return str(e)

    def create_new_file(self, file_path: str, content: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to create a new file at '{file_path}', allow?",
                default_choice="Y",
            ):
                logger.info(f"User denied file creation: {file_path}")
                raise PermissionError("❌ User denied permission to create this file. The operation was cancelled.")
            logger.info(f"Creating new file: {file_path}")
            if os.path.exists(file_path):
                raise FileExistsError(f"File '{file_path}' already exists.")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
            return f"File '{file_path}' created successfully."
        except Exception as e:
            logger.error(f"Error creating file {file_path}: {str(e)}")
            return str(e)
