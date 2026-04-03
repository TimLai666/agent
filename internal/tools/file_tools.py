import base64
import io
import mimetypes
import os
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent

from internal.logger import logger

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


def add_file_tools(agent: Agent) -> None:
    """Add file-related tools to the agent."""

    file_tools_manager: FileTools = FileTools()

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


class FileTools:
    """A class to encapsulate binary and image file tools."""

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
