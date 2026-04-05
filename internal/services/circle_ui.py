import random
import math
import re
import string
import sys
import io
import os
import html
import weakref
import urllib.request
import concurrent.futures
import base64
from io import BytesIO
try:
    from PIL import Image
except Exception:
    Image = None

# Thread pool for downloading/processing images (limit concurrency to avoid resource spikes)
_image_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
# Cache for downloaded images: (url, max_width) -> data_uri or ""
_image_data_cache: dict[tuple[str, int], str] = {}
_image_inflight: set[tuple[str, int]] = set()
_image_failures: dict[tuple[str, int], int] = {}
# Max bytes to read for an image (e.g., 8MB)
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Max dimension (width or height) for images; images larger will be downscaled to this
_MAX_IMAGE_DIM = 1600


def _download_and_encode_image(url: str, max_width: int = 800) -> str:
    """下載圖片並轉為 base64 data URI

    Args:
        url: 圖片 URL
        max_width: 最大寬度

    Returns:
        data URI 字符串，失敗時返回原 URL
    """
    try:
        # 處理本地文件
        if url.startswith('file://'):
            local_path = url[7:]
            if local_path.startswith('/') and len(local_path) > 3 and local_path[2] == ':':
                local_path = local_path[1:]
            with open(local_path, 'rb') as f:
                raw = f.read(_MAX_IMAGE_BYTES + 1)
        elif not url.startswith(('http://', 'https://')):
            # 本地路徑
            import os
            if os.path.exists(url):
                with open(url, 'rb') as f:
                    raw = f.read(_MAX_IMAGE_BYTES + 1)
            else:
                return url
        else:
            # 遠程 URL
            with urllib.request.urlopen(url, timeout=8) as resp:
                raw = resp.read(_MAX_IMAGE_BYTES + 1)

        if len(raw) > _MAX_IMAGE_BYTES:
            return url  # 圖片太大，不處理

        # 如果有 PIL，進行壓縮和轉換
        if Image is not None:
            try:
                im = Image.open(BytesIO(raw))
                im.load()

                # 轉換 RGBA 為 RGB（避免透明度問題）
                if im.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', im.size, (255, 255, 255))
                    if im.mode == 'P':
                        im = im.convert('RGBA')
                    background.paste(im, mask=im.split()[-1] if im.mode in ('RGBA', 'LA') else None)
                    im = background
                elif im.mode != 'RGB':
                    im = im.convert('RGB')

                # 縮小尺寸
                w, h = im.size
                if w > max_width:
                    h = int(h * max_width / w)
                    w = max_width
                    im = im.resize((w, h), Image.Resampling.LANCZOS)

                # 轉為 JPEG（更小）
                output = BytesIO()
                im.save(output, format='JPEG', quality=85, optimize=True)
                data = output.getvalue()
            except Exception:
                # PIL 處理失敗，使用原始數據
                data = raw
        else:
            data = raw

        # 編碼為 base64
        b64 = base64.b64encode(data).decode('ascii')
        return f'data:image/jpeg;base64,{b64}'

    except Exception as e:
        logger.debug(f"Failed to download/encode image {url}: {e}")
        return url  # 返回原 URL


def _render_image_block(data_uri: str, alt: str, source_url: str | None = None) -> str:
    safe_alt = html.escape(alt) if alt else ""
    action_links = (
        f'<a href="{data_uri}" '
        f'style="display: inline-block; padding: 2px 6px; '
        f'background: rgba(0, 0, 0, 0.55); color: #CFE9FF; text-decoration: none; '
        f'border-radius: 6px; font-size: 10px;">Save</a>'
    )
    if source_url:
        safe_src = html.escape(source_url, quote=True)
        action_links += (
            f' <a href="{safe_src}" '
            f'style="display: inline-block; padding: 2px 6px; '
            f'background: rgba(0, 0, 0, 0.35); color: #CFE9FF; text-decoration: none; '
            f'border-radius: 6px; font-size: 10px;">Open</a>'
        )
    return (
        f'<div style="margin: 6px 0 10px 0;">'
        f'<img src="{data_uri}" alt="{safe_alt}" '
        f'style="max-width: 100%; height: auto; display: block; margin: 0 0 4px 0;" />'
        f'{action_links}'
        f'</div>'
    )


def _render_image_placeholder(alt: str) -> str:
    label = alt if alt else "Loading image..."
    return (
        f'<div style="margin: 6px 0; color: rgba(255, 255, 255, 0.7); '
        f'font-size: 11px;">{label}</div>'
    )


def _render_image_link(url: str, alt: str) -> str:
    label = alt if alt else "image"
    return f"[{label}]({url})"


def _process_markdown_images_async(text: str) -> tuple[str, list[tuple[str, int]]]:
    """Replace markdown images with cached data URIs; return pending downloads."""
    if not text:
        return text, []

    md_img = re.compile(r'!\[([^\]]*)\]\((<[^>]+>|[^)]+)\)')
    md_link = re.compile(r'(?<!\!)\[([^\]]*)\]\((<[^>]+>|[^)]+)\)')
    pending: list[tuple[str, int]] = []

    def is_image_url(url: str) -> bool:
        return bool(re.search(r'\.(png|jpe?g|gif|webp|bmp|svg)(?:\?|#|$)', url, re.IGNORECASE))

    def promote_image_links(raw_text: str) -> str:
        def replace_link(match):
            label = match.group(1)
            url = match.group(2).strip()
            if url.startswith('<') and url.endswith('>'):
                url = url[1:-1].strip()
            if not url or not is_image_url(url):
                return match.group(0)
            return f"![{label}]({url})"

        return md_link.sub(replace_link, raw_text)

    def replace_image(match):
        alt = match.group(1)
        url = match.group(2).strip()
        if url.startswith('<') and url.endswith('>'):
            url = url[1:-1].strip()

        width_match = re.search(r'=\s*(\d+)', url)
        if width_match:
            width = int(width_match.group(1))
            url = re.sub(r'\s*=\s*\d+', '', url).strip()
        else:
            width = 800

        if url.startswith('data:image/'):
            return _render_image_block(url, alt)

        key = (url, width)
        cached = _image_data_cache.get(key)
        if cached:
            return _render_image_block(cached, alt, url)
        if cached == "" or _image_failures.get(key, 0) >= 2:
            return _render_image_link(url, alt) if url else ""

        pending.append(key)
        return _render_image_placeholder(alt)

    return md_img.sub(replace_image, promote_image_links(text)), pending

def _autolink_markdown(text: str) -> str:
    if not text:
        return text

    # Replace http(s)://... occurrences with [url](url) except when already inside brackets/parentheses/angle brackets
    def repl(m):
        url = m.group(0)
        start = m.start()
        # If immediately preceded by characters that indicate it's already part of a link or HTML, skip
        if start > 0:
            prev = text[start - 1]
            if prev in "([<\"'=":
                return url
        return f'[{url}]({url})'

    return re.sub(r'https?://[^\s<)]+', repl, text)


def _prepare_markdown(text: str) -> str:
    """Normalize markdown: autolink only."""
    if not text:
        return text
    return _autolink_markdown(text)

from PySide6.QtCore import (
    QMetaObject,
    Property,
    QRect,
    QSize,
    Signal,
    QTimer,
    Qt,
    QUrl,
    QEasingCurve,
    QPropertyAnimation,
    QVariantAnimation,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QCursor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)


def _make_stop_icon(size: int = 28) -> QIcon:
    """Draw a white rounded-square stop icon perfectly centred on a transparent pixmap."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sq = int(size * 0.38)
    x = (size - sq) // 2
    p.setBrush(QColor(255, 255, 255, 240))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(x, x, sq, sq, 2, 2)
    p.end()
    return QIcon(px)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except Exception:
    QWebEngineView = None
    HAS_WEBENGINE = False

from internal.logger import logger


def _compute_todo_window_position(
    frame: QRect,
    button_rect: QRect,
    panel_size: QSize,
    screen_rect: QRect,
) -> tuple[int, int]:
    x = frame.right() + 12
    min_x = screen_rect.left() + 8
    max_x = screen_rect.right() - panel_size.width() - 8
    if max_x < min_x:
        max_x = min_x
    x = max(min_x, min(x, max_x))

    if button_rect.width() <= 0 or button_rect.height() <= 0:
        anchor_y = frame.top() + 20
    else:
        anchor_y = frame.top() + button_rect.center().y() - (panel_size.height() // 2)

    min_y = screen_rect.top() + 8
    max_y = screen_rect.bottom() - panel_size.height() - 8
    if max_y < min_y:
        max_y = min_y
    y = max(min_y, min(anchor_y, max_y))
    return x, y


class AutoWrapTextBrowser(QTextBrowser):
    """QTextBrowser that keeps document width aligned to viewport width."""

    @staticmethod
    def _sanitize_font(font: QFont) -> QFont:
        safe_font = QFont(font)
        # Qt rich text may internally call setPointSize(font.pointSize()).
        # If pointSize is -1 (even when pixelSize is set), warnings will spam logs.
        if safe_font.pointSize() <= 0 and safe_font.pointSizeF() <= 0:
            safe_font.setPointSize(11)
        return safe_font

    def _ensure_valid_font(self) -> None:
        safe_font = self._sanitize_font(self.font())
        self.setFont(safe_font)
        try:
            self.document().setDefaultFont(safe_font)
        except Exception:
            pass

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ensure_valid_font()
        self._raw_markdown = None
        self._last_rendered_markdown = None
        self._markdown_refresh_pending = False
        self._image_max_width = None
        self._constrain_images_active = False
        self._image_buttons = []
        self._refresh_image_buttons_pending = False
        try:
            self.document().contentsChanged.connect(self._on_contents_changed)
            self.document().resourceLoaded.connect(self._on_resource_loaded)
        except Exception:
            pass
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        try:
            self.anchorClicked.connect(self._handle_anchor_clicked)
        except Exception:
            pass

    def setMarkdown(self, text: str) -> None:
        self._ensure_valid_font()
        self._raw_markdown = text or ""
        self._last_rendered_markdown = None
        self._apply_markdown_with_images()

    def _apply_markdown_with_images(self) -> None:
        raw = self._raw_markdown
        if raw is None:
            QTextBrowser.setMarkdown(self, raw)
            return
        processed, pending = _process_markdown_images_async(raw)
        if processed != self._last_rendered_markdown:
            self._last_rendered_markdown = processed
            QTextBrowser.setMarkdown(self, processed)
        if pending:
            self._queue_image_downloads(pending)

    @Slot()
    def _schedule_markdown_refresh(self) -> None:
        if self._markdown_refresh_pending:
            return
        self._markdown_refresh_pending = True
        QTimer.singleShot(0, self._refresh_markdown)

    def _refresh_markdown(self) -> None:
        self._markdown_refresh_pending = False
        if self._raw_markdown is None:
            return
        self._apply_markdown_with_images()

    def _queue_image_downloads(self, pending: list[tuple[str, int]]) -> None:
        if not pending:
            return
        self_ref = weakref.ref(self)

        def done_callback(future, key):
            try:
                data_uri = future.result()
            except Exception:
                data_uri = ""
            if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
                data_uri = ""
            if data_uri:
                _image_data_cache[key] = data_uri
                _image_failures.pop(key, None)
            else:
                _image_failures[key] = _image_failures.get(key, 0) + 1
            _image_inflight.discard(key)
            widget = self_ref()
            if widget is None:
                return
            try:
                QMetaObject.invokeMethod(
                    widget,
                    "_schedule_markdown_refresh",
                    Qt.QueuedConnection,
                )
            except Exception:
                try:
                    QTimer.singleShot(0, widget._schedule_markdown_refresh)
                except Exception:
                    pass

        for key in dict.fromkeys(pending):
            if key in _image_inflight:
                continue
            _image_inflight.add(key)
            url, width = key
            future = _image_executor.submit(_download_and_encode_image, url, width)
            future.add_done_callback(lambda fut, k=key: done_callback(fut, k))

    def _on_contents_changed(self):
        self.update_wrap_width()
        self._schedule_refresh_image_buttons()

    def _on_resource_loaded(self, *_args):
        self.update_wrap_width()
        self._schedule_refresh_image_buttons()
        try:
            self.textChanged.emit()
        except Exception:
            pass

    def setOpenExternalLinks(self, _open_external: bool) -> None:
        super().setOpenExternalLinks(False)

    def _handle_anchor_clicked(self, url: QUrl) -> None:
        try:
            url_str = url.toString()
            if url.scheme() == "data" and url_str.startswith("data:image/"):
                self._save_data_uri(url_str)
                return
        except Exception:
            pass
        QDesktopServices.openUrl(url)

    def _save_data_uri(self, data_uri: str) -> None:
        try:
            if not data_uri.startswith("data:image/"):
                return
            header, b64data = data_uri.split(",", 1)
            mime_part = header.split(";", 1)[0]
            ext = "png"
            if "/" in mime_part:
                ext = mime_part.split("/", 1)[1] or "png"
            raw = base64.b64decode(b64data)
            image = QImage.fromData(raw)
            if image.isNull():
                return
            default_dir = os.path.expanduser("~")
            default_path = os.path.join(default_dir, f"image.{ext}")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Image",
                default_path,
                "Images (*.png *.jpg *.jpeg *.bmp)",
            )
            if not path:
                return
            image.save(path)
        except Exception:
            pass

    def _schedule_refresh_image_buttons(self):
        if self._refresh_image_buttons_pending:
            return
        self._refresh_image_buttons_pending = True
        QTimer.singleShot(0, self._refresh_image_buttons)
        QTimer.singleShot(60, self._refresh_image_buttons)

    def _clear_image_buttons(self):
        for btn in self._image_buttons:
            try:
                btn.deleteLater()
            except Exception:
                pass
        self._image_buttons = []

    def _resolve_image_resource(self, name: str):
        try:
            resource = self.document().resource(QTextDocument.ImageResource, QUrl(name))
            if isinstance(resource, (QPixmap, QImage)):
                return resource
        except Exception:
            resource = None

        if name.startswith("data:image/"):
            try:
                header, b64data = name.split(",", 1)
                raw = base64.b64decode(b64data)
                image = QImage.fromData(raw)
                if not image.isNull():
                    return image
            except Exception:
                return None

        try:
            if name.startswith("file://"):
                local_path = name[7:]
                if local_path.startswith("/") and len(local_path) > 3 and local_path[2] == ":":
                    local_path = local_path[1:]
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        raw = f.read(_MAX_IMAGE_BYTES + 1)
                    image = QImage.fromData(raw)
                    if not image.isNull():
                        return image
            elif name.startswith(("http://", "https://")):
                with urllib.request.urlopen(name, timeout=8) as resp:
                    raw = resp.read(_MAX_IMAGE_BYTES + 1)
                image = QImage.fromData(raw)
                if not image.isNull():
                    return image
        except Exception:
            return None
        return None

    def _save_image(self, name: str) -> None:
        resource = self._resolve_image_resource(name)
        if resource is None:
            return
        if isinstance(resource, QPixmap):
            image = resource.toImage()
        else:
            image = resource
        if image.isNull():
            return

        default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, "image.png")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image",
            default_path,
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            return
        image.save(path)

    def _create_image_button(self, image_name: str):
        btn = QToolButton(self.viewport())
        btn.setText("Save")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setStyleSheet(
            "QToolButton { "
            "background-color: rgba(0, 0, 0, 140); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 80); "
            "border-radius: 6px; "
            "padding: 2px 6px; "
            "font-size: 10px; "
            "}"
            "QToolButton:hover { background-color: rgba(0, 0, 0, 180); }"
        )
        btn.clicked.connect(lambda _=False, name=image_name: self._save_image(name))
        btn.adjustSize()
        return btn

    def _refresh_image_buttons(self):
        self._refresh_image_buttons_pending = False
        self._clear_image_buttons()

        try:
            doc = self.document()
            layout = doc.documentLayout()
            offset = self.contentOffset()
            viewport_h = self.viewport().height()

            block = doc.begin()
            while block.isValid():
                block_layout = block.layout()
                block_rect = layout.blockBoundingRect(block)
                it = block.begin()
                while not it.atEnd():
                    fragment = it.fragment()
                    if fragment.isValid():
                        fmt = fragment.charFormat()
                        if fmt.isImageFormat():
                            img_fmt = QTextImageFormat(fmt)
                            pos_in_block = fragment.position() - block.position()
                            line_y = 0.0
                            line_doc_x = block_rect.left()
                            if block_layout is not None:
                                line = block_layout.lineForTextPosition(pos_in_block)
                                if line.isValid():
                                    line_doc_x = (
                                        block_rect.left()
                                        + line.x()
                                        + line.cursorToX(pos_in_block)
                                    )
                                    line_y = line.y()
                            x = line_doc_x
                            y = block_rect.top() + line_y
                            img_w = img_fmt.width() or 0
                            img_h = img_fmt.height() or 0
                            if img_w <= 0 or img_h <= 0:
                                res = self._resolve_image_resource(img_fmt.name())
                                if isinstance(res, QPixmap):
                                    img_w = res.width()
                                    img_h = res.height()
                                elif isinstance(res, QImage):
                                    img_w = res.width()
                                    img_h = res.height()
                            if img_w <= 0 or img_h <= 0:
                                img_h = 1

                            view_x = int(x - offset.x())
                            view_y = int(y - offset.y())
                            if view_y + img_h < 0 or view_y > viewport_h:
                                it += 1
                                continue

                            btn = self._create_image_button(img_fmt.name())
                            btn.move(max(0, view_x + 6), max(0, view_y + 6))
                            btn.show()
                            btn.raise_()
                            self._image_buttons.append(btn)
                    it += 1
                block = block.next()
        except Exception:
            pass

    def _constrain_images(self, max_width: int) -> None:
        if self._constrain_images_active:
            return
        if not max_width or max_width <= 0:
            return
        self._constrain_images_active = True
        try:
            doc = self.document()
            cursor = QTextCursor(doc)
            block = doc.begin()
            while block.isValid():
                it = block.begin()
                while not it.atEnd():
                    fragment = it.fragment()
                    if fragment.isValid():
                        fmt = fragment.charFormat()
                        if fmt.isImageFormat():
                            img_fmt = QTextImageFormat(fmt)
                            current_w = img_fmt.width()
                            if current_w and current_w <= max_width:
                                it += 1
                                continue
                            resource = doc.resource(
                                QTextDocument.ImageResource, QUrl(img_fmt.name())
                            )
                            if isinstance(resource, QPixmap):
                                iw = resource.width()
                                ih = resource.height()
                            elif isinstance(resource, QImage):
                                iw = resource.width()
                                ih = resource.height()
                            else:
                                iw = img_fmt.width()
                                ih = img_fmt.height()
                            if iw and iw > max_width:
                                scale = max_width / iw
                                img_fmt.setWidth(max_width)
                                if ih:
                                    img_fmt.setHeight(int(ih * scale))
                                cursor.setPosition(fragment.position())
                                cursor.setPosition(
                                    fragment.position() + fragment.length(),
                                    QTextCursor.KeepAnchor,
                                )
                                cursor.setCharFormat(img_fmt)
                    it += 1
                block = block.next()
        except Exception:
            pass
        finally:
            self._constrain_images_active = False

    def update_wrap_width(self, width: float | None = None) -> None:
        try:
            w = width if width is not None else self.viewport().width()
            if not w:
                return
            w = max(1, int(w))
            self._image_max_width = w
            doc = self.document()
            doc.setUseDesignMetrics(False)
            doc.setTextWidth(w)
            if self.lineWrapMode() != QTextEdit.NoWrap:
                if self.lineWrapMode() != QTextEdit.FixedPixelWidth:
                    self.setLineWrapMode(QTextEdit.FixedPixelWidth)
                self.setLineWrapColumnOrWidth(w)
            self._constrain_images(w)
            self._schedule_refresh_image_buttons()
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_wrap_width()
        self._schedule_refresh_image_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_refresh_image_buttons()


class CodeBlockWidget(QWidget):
    """Custom widget for displaying code blocks with copy button."""
    
    def __init__(self, code: str, language: str = "", parent=None):
        super().__init__(parent)
        self.code = code
        self.language = language
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with language and copy button
        header = QWidget()
        header.setStyleSheet(
            "background-color: rgba(45, 45, 45, 220); "
            "border-top-left-radius: 8px; "
            "border-top-right-radius: 8px; "
            "padding: 4px 8px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(8)
        
        lang_label = QLabel(language if language else "code")
        lang_label.setStyleSheet("color: rgba(255, 255, 255, 160); font-size: 11px; background: transparent;")
        
        copy_btn = QPushButton("📋 Copy")
        copy_btn.setFixedHeight(20)
        copy_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: rgba(0, 122, 255, 140); "
            "  color: white; "
            "  border: none; "
            "  border-radius: 4px; "
            "  padding: 2px 8px; "
            "  font-size: 11px; "
            "} "
            "QPushButton:hover { background-color: rgba(0, 122, 255, 200); } "
            "QPushButton:pressed { background-color: rgba(0, 100, 200, 220); }"
        )
        copy_btn.clicked.connect(self._copy_code)
        
        header_layout.addWidget(lang_label)
        header_layout.addStretch()
        header_layout.addWidget(copy_btn)
        
        # Code content
        code_browser = AutoWrapTextBrowser()
        code_browser.setPlainText(code)
        code_browser.setStyleSheet(
            "QTextBrowser { "
            "  background-color: rgba(30, 30, 30, 240); "
            "  color: #D4D4D4; "
            "  font-family: 'Consolas', 'Courier New', monospace; "
            "  font-size: 13px; "
            "  border: none; "
            "  border-bottom-left-radius: 8px; "
            "  border-bottom-right-radius: 8px; "
            "  padding: 8px; "
            "  line-height: 1.4; "
            "}"
        )
        code_browser.setFrameShape(QFrame.NoFrame)
        code_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        code_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        code_browser.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        code_browser.setViewportMargins(0, 0, 0, 0)
        code_browser.setContentsMargins(0, 0, 0, 0)
        code_browser.document().setDocumentMargin(0)
        code_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        code_browser.update_wrap_width()
        
        def adjust_height():
            try:
                code_browser.document().adjustSize()
                h = code_browser.document().size().height()
                code_browser.setFixedHeight(max(int(h) + 16, 40))
            except RuntimeError:
                pass
        
        try:
            code_browser.document().contentsChanged.connect(adjust_height)
        except Exception:
            pass
        QTimer.singleShot(0, adjust_height)
        
        layout.addWidget(header)
        layout.addWidget(code_browser)
        
        self.setStyleSheet("background: transparent;")
    
    def _copy_code(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.code)
        # Brief visual feedback
        sender = self.sender()
        if sender:
            original_text = sender.text()
            sender.setText("✓ Copied")
            QTimer.singleShot(1000, lambda: sender.setText(original_text) if sender else None)


class CommandLineEdit(QLineEdit):
    """支援指令補全和歷史記錄的輸入框"""
    
    # 所有可用的指令
    COMMANDS = [
        "/help",
        "/exit",
        "/quit",
        "/clear",
        "/config",
        "/config-web",
        "/history",
        "/history 5",
        "/history 10",
        "/last",
        "/retry",
        "/compact",
        "/tools",
        "/skills",
        "/skills list",
        "/skills info ",
        "/skills test ",
        "/skills reload",
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []  # 指令歷史
        self.history_index = -1  # 當前歷史索引
        
        # 設置自動補全
        self.completer = QCompleter(self.COMMANDS, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(8)
        
        # 自定義補全器樣式
        popup = self.completer.popup()
        popup.setStyleSheet(
            "QListView {"
            "  background-color: rgba(40, 40, 40, 240);"
            "  color: white;"
            "  border: 1px solid rgba(255, 255, 255, 60);"
            "  border-radius: 8px;"
            "  padding: 4px;"
            "  selection-background-color: rgba(0, 122, 255, 180);"
            "}"
            "QListView::item {"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "}"
            "QListView::item:hover {"
            "  background-color: rgba(255, 255, 255, 30);"
            "}"
        )
        
        self.setCompleter(self.completer)
    
    def keyPressEvent(self, event: QKeyEvent):
        """處理特殊按鍵"""
        # 上箭頭：顯示上一條歷史記錄
        if event.key() == Qt.Key_Up:
            if self.history and self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.setText(self.history[-(self.history_index + 1)])
            event.accept()
            return
        
        # 下箭頭：顯示下一條歷史記錄
        elif event.key() == Qt.Key_Down:
            if self.history_index > 0:
                self.history_index -= 1
                self.setText(self.history[-(self.history_index + 1)])
            elif self.history_index == 0:
                self.history_index = -1
                self.clear()
            event.accept()
            return
        
        # Tab 鍵：觸發補全（如果補全器有建議）
        elif event.key() == Qt.Key_Tab:
            if self.completer.completionCount() > 0:
                # 如果有補全建議，選擇第一個
                self.completer.setCurrentRow(0)
                self.setText(self.completer.currentCompletion())
                # 如果是需要參數的指令，將游標移到末尾
                if self.text().endswith(" "):
                    self.setCursorPosition(len(self.text()))
            event.accept()
            return
        
        # Ctrl+V with image in clipboard → attach to parent MainWindow
        if (event.key() == Qt.Key_V and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime and mime.hasImage():
                img = clipboard.image()
                if not img.isNull():
                    try:
                        buf = io.BytesIO()
                        from PIL import Image as _PIL
                        pil_img = _PIL.fromqimage(img) if hasattr(_PIL, "fromqimage") else None
                        if pil_img is None:
                            # Fallback: save QImage to bytes via PNG
                            import tempfile, os
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                tmp_path = tmp.name
                            img.save(tmp_path)
                            with open(tmp_path, "rb") as f:
                                img_bytes = f.read()
                            os.unlink(tmp_path)
                        else:
                            pil_img.save(buf, format="PNG")
                            img_bytes = buf.getvalue()
                        # Walk up to find MainWindow and append image
                        iw = img.width()
                        ih = img.height()
                        parent = self.parent()
                        while parent is not None:
                            if hasattr(parent, "_attached_images"):
                                parent._attached_images.append(img_bytes)
                                if hasattr(parent, "_show_attach_chip"):
                                    parent._show_attach_chip(f"📷 image.png  {iw}×{ih}")
                                break
                            parent = parent.parent() if hasattr(parent, "parent") else None
                    except Exception as e:
                        logger.debug(f"Clipboard image paste failed: {e}")
                    event.accept()
                    return

        # 其他按鍵：重置歷史索引
        if event.key() not in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab):
            self.history_index = -1

        # 調用父類處理
        super().keyPressEvent(event)
    
    def add_to_history(self, text: str):
        """添加到歷史記錄"""
        if text and text.strip():
            # 避免重複
            if not self.history or self.history[-1] != text:
                self.history.append(text)
                # 限制歷史記錄數量
                if len(self.history) > 100:
                    self.history = self.history[-100:]
            self.history_index = -1


class Arc:
    colors = list(string.ascii_lowercase[0:6] + string.digits)

    shades_of_green = [
        "#32CD32",
        "#CAE00D",
        "#9EFD38",
        "#568203",
        "#93C572",
        "#8DB600",
        "#708238",
        "#556B2F",
        "#014421",
        "#98FB98",
        "#7CFC00",
        "#4F7942",
        "#009E60",
        "#00FF7F",
        "#00FA9A",
        "#177245",
        "#2E8B57",
        "#3CB371",
        "#A7F432",
        "#123524",
        "#5E8C31",
        "#90EE90",
        "#03C03C",
        "#66FF00",
        "#006600",
        "#D9E650",
    ]

    def __init__(self):
        self.diameter = random.randint(40, 110)
        color_hex = random.choice(Arc.shades_of_green)
        self.color = QColor(color_hex)
        self.color.setAlpha(150)
        self.span = random.randint(60, 180)
        self.direction = 1 if random.randint(10, 15) % 2 == 0 else -1
        self.startAngle = random.randint(0, 360)
        self.step = random.randint(100, 300)


class Circle:
    def __init__(self):
        self.diameter = 100
        self.color_index = 0

    def get_color(self, animation_progress):
        # 根據動畫進度選擇顏色
        progress = (animation_progress / 360) * len(Arc.shades_of_green)
        current_index = int(progress) % len(Arc.shades_of_green)
        next_index = (current_index + 1) % len(Arc.shades_of_green)

        # 計算兩個顏色之間的插值比例
        t = progress - int(progress)  # 0.0 到 1.0 之間的小數部分

        # 取得當前和下一個顏色
        current_color = QColor(Arc.shades_of_green[current_index])
        next_color = QColor(Arc.shades_of_green[next_index])

        # 在兩個顏色之間插值
        r = int(current_color.red() + (next_color.red() - current_color.red()) * t)
        g = int(
            current_color.green() + (next_color.green() - current_color.green()) * t
        )
        b = int(current_color.blue() + (next_color.blue() - current_color.blue()) * t)

        return QColor(r, g, b).name()


class SpinnerLabel(QLabel):
    """Lightweight text-spinner label that cycles frames with a QTimer."""

    def __init__(self, parent=None, base_text: str = ""):
        super().__init__(parent)
        self.base_text = base_text
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._idx = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setText(base_text)
        self.setVisible(False)
        self.setStyleSheet("color: #A0A0A0; border: none; background: transparent;")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

    def _tick(self):
        try:
            self.setText(
                f"{self.frames[self._idx % len(self.frames)]} {self.base_text}"
            )
            self._idx += 1
        except RuntimeError:
            # C++ object gone; ignore
            pass

    def set_base_text(self, text: str):
        self.base_text = text
        if not self._timer.isActive():
            self.setText(text)

    def start(self):
        if not self._timer.isActive():
            self._idx = 0
            self.setVisible(True)
            self._timer.start(100)

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self.setVisible(False)
        self.setText(self.base_text)


class WaveformWidget(QWidget):
    """Animated audio waveform bars — self-animating, no external mic access needed."""

    BAR_COUNT = 7
    BAR_W = 4
    BAR_GAP = 4
    MIN_H = 3
    MAX_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        total_w = self.BAR_COUNT * (self.BAR_W + self.BAR_GAP) - self.BAR_GAP
        self.setFixedWidth(total_w + 16)
        self.setMinimumHeight(self.MAX_H + 8)
        self._heights = [float(self.MIN_H)] * self.BAR_COUNT
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._animate)
        self._tick = 0

    def start(self):
        self._tick = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._heights = [float(self.MIN_H)] * self.BAR_COUNT
        self.update()

    def set_level(self, _level: float):
        pass  # level sampling removed to avoid mic conflict; animation is autonomous

    def _animate(self):
        import math, random
        self._tick += 1
        t = self._tick * 0.18
        for i in range(self.BAR_COUNT):
            # Sine wave across bars with per-bar phase offset + random noise
            phase = i * (math.pi / (self.BAR_COUNT - 1))
            wave = (math.sin(t + phase) + 1) / 2          # 0..1
            envelope = math.sin(i * math.pi / (self.BAR_COUNT - 1))  # bell shape
            base_h = self.MIN_H + (self.MAX_H - self.MIN_H) * wave * envelope
            noise = random.uniform(-1.5, 1.5)
            target = max(self.MIN_H, min(self.MAX_H, base_h + noise))
            self._heights[i] += (target - self._heights[i]) * 0.35
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        cx = w // 2
        total_w = self.BAR_COUNT * (self.BAR_W + self.BAR_GAP) - self.BAR_GAP
        x0 = cx - total_w // 2
        for i, bar_h in enumerate(self._heights):
            x = x0 + i * (self.BAR_W + self.BAR_GAP)
            bar_h = max(self.MIN_H, bar_h)
            y = (h - bar_h) // 2
            alpha = int(160 + 90 * (bar_h / self.MAX_H))
            color = QColor(100, 180, 255, alpha)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(int(x), int(y), self.BAR_W, int(bar_h), 2, 2)
        p.end()


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: str, parent=None, is_active=False, on_toggle_callback=None):
        super().__init__(parent)
        self.base_title = title
        self.is_active = is_active
        self._content_height = 0
        self._animation = None
        self.on_toggle_callback = on_toggle_callback  # Callback to notify parent of height changes

        # Title button + spinner on the left
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(6)

        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(is_active)  # Auto-expand if active
        self.button.setArrowType(Qt.DownArrow if is_active else Qt.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setStyleSheet(
            "QToolButton { color: #007AFF; font-weight: bold; border: none; background: transparent; padding: 2px; }"
            "QToolButton:hover { color: #329DFF; }"
        )
        self.button.clicked.connect(self.toggle)

        self.spinner = SpinnerLabel(self, base_text=title)
        if is_active:
            self.spinner.start()

        head_layout.addWidget(self.button)
        head_layout.addWidget(self.spinner)
        head_layout.addStretch(1)

        # Content area
        self.content = AutoWrapTextBrowser()
        # If the section is active but empty, provide a small placeholder so the section is visible
        if is_active and not content.strip():
            self.content.setHtml("<i>Waiting for output...</i>")
        else:
            self.content.setMarkdown(_prepare_markdown(content))
        self.content.setOpenExternalLinks(True)
        self.content.update_wrap_width()
        self.content.setStyleSheet(
    "background: transparent; color: #F0F0F0; font-size: 13px; border-radius: 10px; border: none; margin: 0; padding: 0;"
)
        self.content.setLineWrapMode(QTextEdit.WidgetWidth)
        # 設定圖片樣式以防止橫向捲動
        self.content.document().setDefaultStyleSheet("img { max-width: 251px; width: 100%; height: auto; display: block; }")
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Ensure content doesn't scroll internally and compute size changes
        self.content.setViewportMargins(0, 0, 0, 0)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.document().setDocumentMargin(0)

        def adjust():
            try:
                if self.content is None:
                    return
                self.content.update_wrap_width()
                doc = self.content.document()
                doc_size = doc.documentLayout().documentSize()
                h = doc_size.height()
                # Ensure a sensible minimum height so active blocks are visible
                min_h = 28 if self.is_active else 10
                new_height = max(int(h) + 16, min_h)
                self._content_height = new_height
                self.content.setFixedHeight(new_height)
                if self.layout():
                    self.layout().activate()
            except RuntimeError:
                pass

        # Listen to both text and document changes
        try:
            self.content.textChanged.connect(adjust)
        except Exception:
            pass
        try:
            self.content.document().contentsChanged.connect(adjust)
        except Exception:
            pass
        QTimer.singleShot(0, adjust)
        # Allow clicking links as well as text selection
        self.content.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.content.setVisible(is_active)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(head)
        layout.addWidget(self.content)

    def get_content_height(self):
        """獲取內容區域的高度（用於動畫）"""
        return self._content_height

    def set_content_height(self, height):
        """設置內容區域的高度（用於動畫）"""
        self._content_height = height
        self.content.setFixedHeight(int(height))

    contentHeight = Property(int, get_content_height, set_content_height)

    def update_content(self, new_content: str):
        """更新區塊內容並重新計算高度"""
        if not new_content.strip() and self.is_active:
            self.content.setHtml("<i>Waiting for output...</i>")
        else:
            self.content.setMarkdown(_prepare_markdown(new_content))
        self.content.update_wrap_width()
        
        # 強制重新計算高度
        QTimer.singleShot(0, self._recalculate_height)
        QTimer.singleShot(50, self._recalculate_height)  # 再次確認
    
    def _recalculate_height(self):
        """重新計算內容高度"""
        try:
            if self.content is None:
                return
            self.content.update_wrap_width()
            doc = self.content.document()
            doc_size = doc.documentLayout().documentSize()
            h = doc_size.height()
            min_h = 28 if self.is_active else 10
            new_height = max(int(h) + 16, min_h)
            self._content_height = new_height
            self.content.setFixedHeight(new_height)
            if self.layout():
                self.layout().activate()
            # 通知父容器更新
            if self.parent():
                self.parent().updateGeometry()
        except RuntimeError:
            pass

    def set_active(self, active: bool, animate: bool = True):
        """設置區塊的活動狀態，可選擇是否使用動畫"""
        if self.is_active == active:
            return
        
        self.is_active = active
        
        if active:
            self.spinner.start()
            self.button.setChecked(True)
            self.button.setArrowType(Qt.DownArrow)
            if not self.content.toPlainText().strip():
                self.content.setHtml("<i>Waiting for output...</i>")
            
            self.content.update_wrap_width()
            doc_size = self.content.document().documentLayout().documentSize()
            target_height = max(int(doc_size.height()) + 16, 28)
            
            if animate and self._content_height == 0:
                self.content.setVisible(True)
                self._animate_height(0, target_height)
            else:
                self._content_height = target_height
                self.content.setFixedHeight(target_height)
                self.content.setVisible(True)
        else:
            # 當標籤關閉時，停止spinner並自動收合區塊
            self.spinner.stop()
            content_text = self.content.toPlainText().strip()
            has_real_content = content_text and "Waiting for" not in content_text
            
            # 無論是否有內容，都自動收合區塊
            if has_real_content:
                # 有內容時，使用動畫收合
                current_height = self._content_height if self._content_height > 0 else self.content.height()
                if animate and current_height > 0:
                    self._animate_height(current_height, 0, on_finish=lambda: self._finish_collapse())
                else:
                    self._finish_collapse()
            else:
                # 沒有實際內容時，也要收合
                if animate and self._content_height > 0:
                    self._animate_height(self._content_height, 0, on_finish=lambda: self._finish_collapse())
                else:
                    self._finish_collapse()

    def toggle(self):
        """切換區塊展開/收起狀態（用戶手動點擊）"""
        expanded = self.button.isChecked()
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        
        if expanded:
            # 展開
            self.content.update_wrap_width()
            doc_size = self.content.document().documentLayout().documentSize()
            target_height = max(int(doc_size.height()) + 16, 28)
            
            def on_expand_finish():
                self.content.setVisible(True)
                # Notify parent to recalculate bubble height
                if self.on_toggle_callback:
                    QTimer.singleShot(50, self.on_toggle_callback)
            
            self._animate_height(0, target_height, on_finish=on_expand_finish)
        else:
            # 收起
            current_height = self._content_height if self._content_height > 0 else self.content.height()
            
            def on_collapse_finish():
                self.content.setVisible(False)
                # Notify parent to recalculate bubble height
                if self.on_toggle_callback:
                    QTimer.singleShot(50, self.on_toggle_callback)
            
            self._animate_height(current_height, 0, on_finish=on_collapse_finish)

    def _animate_height(self, start_height: int, end_height: int, on_finish=None):
        """創建高度變化的動畫"""
        if self._animation and self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()
        
        self._animation = QPropertyAnimation(self, b"contentHeight")
        self._animation.setDuration(250)
        self._animation.setStartValue(start_height)
        self._animation.setEndValue(end_height)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        
        if on_finish:
            self._animation.finished.connect(on_finish)
        
        self._animation.start()

    def _finish_collapse(self):
        """完成收起動作"""
        self.button.setChecked(False)
        self.button.setArrowType(Qt.RightArrow)
        self.content.setVisible(False)
        self._content_height = 0


class OutputBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "OutputBubble { "
            "background-color: rgba(30, 30, 30, 210); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 50); "
            "border-radius: 20px;"
            "}"
        )

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollBar:vertical { border: none; background: transparent; width: 4px; margin: 4px 0 4px 0; } "
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); min-height: 20px; border-radius: 2px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.scroll.setWidget(self.container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    def content_height(self) -> int:
        return int(self.container.sizeHint().height())

    def _available_width(self) -> int:
        """Compute available inner width (accounting for margins)"""
        try:
            margins = self.layout.contentsMargins()
            return max(0, self.width() - (margins.left() + margins.right() + 8))
        except Exception:
            return max(0, self.width() - 20)

    def resizeEvent(self, event):
        """On resize, rescale children (images and text) to avoid horizontal overflow."""
        super().resizeEvent(event)
        avail_w = self._available_width()
        # Ensure container itself doesn't exceed available width
        try:
            self.container.setMaximumWidth(avail_w)
            self.container.setMinimumWidth(0)
        except Exception:
            pass
        # Update text browsers and images throughout the container (recursive)
        try:
            for tb in self.container.findChildren(QTextBrowser):
                try:
                    tb.setMaximumWidth(avail_w)
                    tb.setMinimumWidth(0)
                    tb.update_wrap_width(avail_w)
                    doc = tb.document()
                    doc_size = doc.documentLayout().documentSize()
                    h = max(int(doc_size.height()) + 16, 32)
                    tb.setMinimumHeight(h)
                    tb.setMaximumHeight(h)
                except Exception:
                    pass
            for lbl in self.container.findChildren(QLabel):
                try:
                    # Static pixmap
                    if hasattr(lbl, '_orig_pixmap') and lbl._orig_pixmap is not None:
                        new_pix = lbl._orig_pixmap.scaledToWidth(avail_w, Qt.SmoothTransformation)
                        lbl.setPixmap(new_pix)
                        lbl.setMaximumWidth(avail_w)
                        lbl.setMinimumWidth(0)
                    # Animated GIF
                    if getattr(lbl, '_is_gif', False) and hasattr(lbl, '_gif_movie'):
                        movie = lbl._gif_movie
                        rect = movie.frameRect()
                        h = rect.height() or int(avail_w * 0.75)
                        movie.setScaledSize(QSize(avail_w, h))
                        lbl.setMaximumWidth(avail_w)
                        lbl.setMinimumWidth(0)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Error resizing children recursively: {e}", exc_info=True)

    def set_content(self, text: str):
        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        segments = self._parse_segments(text or "")
        for kind, content, is_active in segments:
            if not content.strip():
                continue
            if kind == "normal":
                # 使用 _prepare_markdown 處理內容（包括將圖片轉為 data URI）
                browser = AutoWrapTextBrowser()
                browser.setMarkdown(_prepare_markdown(content))
                browser.setOpenExternalLinks(True)
                browser.setStyleSheet(
                    "background: transparent; color: white; font-size: 14px;"
                )
                # 設定圖片樣式以防止橫向捲動
                browser.document().setDefaultStyleSheet("img { max-width: 251px; width: 100%; height: auto; display: block; }")
                browser.setFrameShape(QFrame.NoFrame)
                browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                # Allow clicking links as well as text selection
                browser.setTextInteractionFlags(Qt.TextBrowserInteraction)
                # Ensure content wraps and doesn't create horizontal scrolling
                browser.setLineWrapMode(QTextEdit.WidgetWidth)
                # Force the browser to fill horizontal space but not exceed bubble width
                # Compute available width taking layout margins into account
                avail_w = self._available_width()
                browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                browser.setMinimumWidth(0)
                browser.setMaximumWidth(avail_w)
                browser.setViewportMargins(0, 0, 0, 0)
                browser.setContentsMargins(0, 0, 0, 0)
                browser.document().setDocumentMargin(0)

                def update_browser_height(b=browser):
                    try:
                        b.update_wrap_width(avail_w)
                        doc_size = b.document().documentLayout().documentSize()
                        h = max(int(doc_size.height()) + 16, 32)
                        b.setMinimumHeight(h)
                        b.setMaximumHeight(h)
                    except RuntimeError:
                        pass

                try:
                    browser.textChanged.connect(update_browser_height)
                    browser.document().contentsChanged.connect(update_browser_height)
                except Exception:
                    pass
                QTimer.singleShot(0, update_browser_height)
                self.layout.addWidget(browser)
            else:
                title = "Tool execution" if kind == "tool" else "選項結果"
                section = CollapsibleSection(title, content)
                self.layout.addWidget(section)

        self.layout.addStretch(1)

    def _parse_segments(self, text: str):
        tags = {
            "<tool-execution>": "tool",
            "</tool-execution>": "tool",
            "<discussion>": "discussion",
            "</discussion>": "discussion",
        }
        open_tags = {"<tool-execution>", "<discussion>"}
        close_tags = {"</tool-execution>", "</discussion>"}
        segments = []
        stack = ["normal"]
        pos = 0

        def add_segment(kind, chunk, active=False):
            # If there's no content and it's not explicitly marked active, skip.
            if not chunk and not active:
                return
            if segments and segments[-1][0] == kind:
                # Preserve existing active state if previously set.
                existing_active = segments[-1][2] if len(segments[-1]) > 2 else False
                segments[-1] = (
                    kind,
                    segments[-1][1] + chunk,
                    existing_active or active,
                )
            else:
                segments.append((kind, chunk, active))

        while pos < len(text):
            next_pos = -1
            next_tag = ""
            for tag in tags:
                idx = text.find(tag, pos)
                if idx == -1:
                    continue
                if next_pos == -1 or idx < next_pos:
                    next_pos = idx
                    next_tag = tag
            if next_pos == -1:
                add_segment(stack[-1], text[pos:])
                break
            if next_pos > pos:
                add_segment(stack[-1], text[pos:next_pos])
            if next_tag in open_tags:
                stack.append(tags[next_tag])
            elif next_tag in close_tags and len(stack) > 1:
                stack.pop()
            pos = next_pos + len(next_tag)

        return segments




class SiriResponseBubble(QWidget):
    SPINNER_PATTERN = re.compile(
        r"^\s*(?:[-*>]\s*)?(?:still\s+|currently\s+)?(?P<status>thinking|listening|分析需求中|規劃回覆中|執行步驟中|生成回覆中|執行工具中|載入技能中|委派子代理中|整理結果中)(?:\s*(?:\.{3,}|\?\?)?\s*)$",
        re.IGNORECASE,
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Animation state for the active border
        self._is_running = False
        self._animation_angle = 0
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation)

        self.setStyleSheet(
            "SiriResponseBubble { "
            "background-color: rgba(20, 20, 20, 205); "
            "border: 1px solid rgba(255, 255, 255, 35); "
            "border-radius: 30px;"
            "} "
            "QTextBrowser { background: transparent; border: none; } "
            "QTextBrowser::viewport { padding: 0px; margin: 0px; border: none; }"
        )

        self.container = QWidget()
        self.container.setObjectName("container")
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.container.setStyleSheet("background: transparent; border: none;")

        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(8)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollBar:vertical { border: none; background: transparent; width: 4px; margin: 6px 0 6px 0; } "
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); min-height: 20px; border-radius: 2px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        self.scroll.setWidget(self.container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)


    def _available_width(self) -> int:
        try:
            margins = self.layout.contentsMargins()
            container_w = self.container.width() or self.width()
            if hasattr(self, "scroll"):
                container_w = self.scroll.viewport().width() or container_w
            return max(0, container_w - (margins.left() + margins.right()))
        except Exception:
            return max(0, self.width() - 20)

    def _refresh_layout_metrics(self, process_events: bool = True) -> None:
        try:
            self.layout.activate()
            self.container.adjustSize()
            if process_events:
                QApplication.processEvents()
        except Exception:
            pass

    def _delayed_layout_refresh(self) -> None:
        try:
            self._refresh_layout_metrics(process_events=False)
            QTimer.singleShot(50, lambda: QApplication.processEvents())
        except Exception as e:
            logger.debug(f"Delayed layout refresh error: {e}")

    def _request_parent_update(self):
        # Request parent (MainWindow) to update speech bubble size after section toggle.
        try:
            self._refresh_layout_metrics()
            QTimer.singleShot(0, lambda: self._refresh_layout_metrics(process_events=True))

            parent_widget = self.parent()
            while parent_widget:
                if hasattr(parent_widget, 'speech_bubble') and parent_widget.speech_bubble == self:
                    QTimer.singleShot(50, lambda p=parent_widget: self._trigger_bubble_resize(p))
                    break
                parent_widget = parent_widget.parent()
        except Exception as e:
            logger.debug(f"Failed to request parent update: {e}")

    def _trigger_bubble_resize(self, main_window):
        # Helper to trigger bubble resize in MainWindow.
        try:
            bubble = main_window.speech_bubble
            bubble.layout.activate()
            bubble.container.adjustSize()
            QApplication.processEvents()

            padding = 30
            bubble_width = main_window.FIXED_WIDTH - 20
            main_window._current_bubble_width = bubble_width
            needed_height = bubble.content_height() + padding
            max_bubble_height = main_window.FIXED_HEIGHT - 200
            bubble_height = min(max(needed_height, 80), max_bubble_height)

            bubble.setFixedSize(bubble_width, bubble_height)

            window_center_x = main_window.FIXED_WIDTH // 2
            ball_center_y = main_window.FIXED_HEIGHT - main_window.BALL_CENTER_FROM_BOTTOM
            bubble_x = window_center_x - bubble_width // 2
            bubble_y = ball_center_y - bubble_height
            bubble_x = max(10, min(bubble_x, main_window.FIXED_WIDTH - bubble_width - 10))
            bubble_y = max(20, min(bubble_y, main_window.FIXED_HEIGHT - bubble_height - 80))

            bubble.move(bubble_x, bubble_y)
            QTimer.singleShot(0, main_window._update_window_mask)
        except Exception as e:
            logger.debug(f"Failed to trigger bubble resize: {e}")

    def _recalculate_child_heights(self) -> None:
        try:
            avail_w = self._available_width()
            container_w = self.width()
            if hasattr(self, "scroll"):
                container_w = self.scroll.viewport().width() or container_w
            self.container.setMinimumWidth(container_w)
            self.container.setMaximumWidth(container_w)
            for tb in self.container.findChildren(QTextBrowser):
                try:
                    if avail_w > 0:
                        tb.setMinimumWidth(avail_w)
                        tb.setMaximumWidth(avail_w)
                    else:
                        tb.setMinimumWidth(0)
                        tb.setMaximumWidth(0)
                    tb.setViewportMargins(0, 0, 0, 0)
                    tb.setContentsMargins(0, 0, 0, 0)
                    try:
                        tb.viewport().setContentsMargins(0, 0, 0, 0)
                    except Exception:
                        pass
                    tb.setStyleSheet(tb.styleSheet() + " padding: 0; margin: 0; ")
                    tb.document().setDocumentMargin(0)
                    tb.setLineWrapMode(QTextEdit.WidgetWidth)
                    tb.update_wrap_width(avail_w)
                    doc = tb.document()
                    doc_size = doc.documentLayout().documentSize()
                    h = max(int(doc_size.height()) + 16, 32)
                    tb.setMinimumHeight(h)
                    tb.setMaximumHeight(h)
                except Exception:
                    pass
            for section in self.container.findChildren(CollapsibleSection):
                try:
                    section._recalculate_height()
                except Exception:
                    pass
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalculate_child_heights()
        QTimer.singleShot(0, self._delayed_layout_refresh)
        QTimer.singleShot(50, self._recalculate_child_heights)

    def _split_normal_segments(self, content: str):
        segments = []
        buffer = []
        lines = content.splitlines(keepends=True)
        for idx, line in enumerate(lines):
            stripped = line.strip()
            match = self.SPINNER_PATTERN.match(stripped)
            if match:
                remaining = "".join(lines[idx + 1 :]).strip()
                if remaining:
                    buffer.append(line)
                    continue
                chunk = "".join(buffer)
                if chunk.strip():
                    segments.append(("text", chunk.rstrip("\n")))
                buffer = []
                status = match.group("status")
                fallback_text = stripped
                if not fallback_text:
                    fallback_text = (
                        f"{status.capitalize()}..." if status else "Thinking..."
                    )
                segments.append(("spinner", fallback_text))
            else:
                buffer.append(line)
        if buffer:
            chunk = "".join(buffer)
            if chunk.strip():
                segments.append(("text", chunk))
        if not segments and content.strip():
            segments.append(("text", content))
        return segments

    def _normalize_soft_wrap(self, text: str) -> str:
        """Merge likely soft-wrapped lines into a single paragraph."""
        if not text:
            return text
        lines = text.splitlines()
        if len(lines) < 2:
            return text
        for line in lines:
            stripped = line.lstrip()
            if not stripped:
                return text
            if stripped.startswith(("- ", "* ", "+ ", "> ", "#", "```", "| ")):
                return text
            if line.startswith(("    ", "\t")):
                return text
        avg_len = sum(len(line) for line in lines) / max(len(lines), 1)
        if avg_len < 40:
            return text
        return " ".join(line.strip() for line in lines)

    def content_height(self) -> int:
        self._refresh_layout_metrics()
        container_hint = self.container.sizeHint().height()
        layout_hint = self.layout.sizeHint().height()
        return int(max(container_hint, layout_hint))

    def _extract_code_blocks(self, text: str) -> list[tuple[str, str, str]]:
        # Extract code blocks from markdown text.
        segments = []
        pos = 0

        pattern = re.compile(r'^```(\w*)\n(.*?)^```', re.MULTILINE | re.DOTALL)

        for match in pattern.finditer(text):
            if match.start() > pos:
                text_before = text[pos:match.start()]
                if text_before.strip():
                    segments.append(('text', text_before, ''))

            language = match.group(1) or ''
            code = match.group(2).rstrip('\n')
            segments.append(('code', code, language))
            pos = match.end()

        if pos < len(text):
            text_after = text[pos:]
            if text_after.strip():
                segments.append(('text', text_after, ''))

        if not segments and text.strip():
            segments.append(('text', text, ''))

        return segments

    def set_content(self, text: str):
        existing_sections = {}
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, CollapsibleSection):
                title = widget.base_title
                existing_sections[title] = widget

        segments = self._parse_segments(text or "")
        seen_sections = set()

        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget is not None and not isinstance(widget, CollapsibleSection):
                widget.setParent(None)
                widget.deleteLater()

        for kind, content, is_active in segments:
            if kind == "normal":
                sub_segments = self._split_normal_segments(content)
                if not sub_segments:
                    continue
                for sub_kind, sub_content in sub_segments:
                    if sub_kind == "spinner":
                        sub_content = _prepare_markdown(sub_content)
                        container = QWidget()
                        h = QHBoxLayout(container)
                        h.setContentsMargins(0, 0, 0, 0)
                        h.setSpacing(8)
                        spinner = SpinnerLabel(container, base_text="")
                        spinner.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                        spinner.start()
                        label = AutoWrapTextBrowser(container)
                        label.setLineWrapMode(QTextEdit.WidgetWidth)
                        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                        label.setMarkdown(sub_content)
                        label.setOpenExternalLinks(True)
                        label.setStyleSheet(
                            "background: transparent; border: none; color: #FFFFFF; "
                            "font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; "
                            "font-size: 14px; line-height: 1.5;"
                        )
                        label.document().setDefaultStyleSheet(
                            "img { max-width: 100%; height: auto; display: block; }"
                        )
                        label.setFrameShape(QFrame.NoFrame)
                        label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        label.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
                        label.setViewportMargins(0, 0, 0, 0)
                        label.setContentsMargins(0, 0, 0, 0)
                        label.document().setDocumentMargin(0)

                        def update_spinner_label_height(b=label):
                            try:
                                b.update_wrap_width(self._available_width())
                                doc_size = b.document().documentLayout().documentSize()
                                height = doc_size.height()
                                min_height = max(int(height) + 16, 32)
                                b.setMinimumHeight(min_height)
                                b.setMaximumHeight(min_height)
                            except RuntimeError:
                                pass

                        try:
                            label.textChanged.connect(update_spinner_label_height)
                            label.document().contentsChanged.connect(update_spinner_label_height)
                        except Exception:
                            pass
                        QTimer.singleShot(0, update_spinner_label_height)
                        h.addWidget(spinner)
                        h.setAlignment(spinner, Qt.AlignTop)
                        h.addWidget(label, 1)
                        h.addStretch(1)
                        self.layout.addWidget(container)
                    else:
                        if not sub_content.strip():
                            continue
                        code_segments = self._extract_code_blocks(sub_content)
                        for seg_type, seg_content, seg_lang in code_segments:
                            if seg_type == 'code':
                                code_widget = CodeBlockWidget(seg_content, seg_lang)
                                self.layout.addWidget(code_widget)
                            else:
                                seg_content = self._normalize_soft_wrap(seg_content)
                                browser = AutoWrapTextBrowser()
                                browser.setMarkdown(_prepare_markdown(seg_content))
                                browser.setOpenExternalLinks(True)
                                browser.setLineWrapMode(QTextEdit.WidgetWidth)
                                browser.setStyleSheet(
                                    "QTextBrowser { color: #FFFFFF; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; "
                                    "font-size: 14px; line-height: 1.5; }"
                                )
                                browser.document().setDefaultStyleSheet(
                                    "img { max-width: 100%; height: auto; display: block; }"
                                )
                                browser.setFrameShape(QFrame.NoFrame)
                                browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                                browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                                browser.setTextInteractionFlags(Qt.TextBrowserInteraction)
                                browser.setViewportMargins(0, 0, 0, 0)
                                browser.setContentsMargins(0, 0, 0, 0)
                                browser.document().setDocumentMargin(0)
                                browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

                                def update_browser_height(b=browser):
                                    try:
                                        avail_w = self._available_width()
                                        if avail_w > 0:
                                            b.setMinimumWidth(avail_w)
                                            b.setMaximumWidth(avail_w)
                                        b.setLineWrapMode(QTextEdit.WidgetWidth)
                                        b.update_wrap_width(avail_w)
                                        doc = b.document()
                                        doc_size = doc.documentLayout().documentSize()
                                        h2 = doc_size.height()
                                        min_height = max(int(h2) + 16, 32)
                                        b.setMinimumHeight(min_height)
                                        b.setMaximumHeight(min_height)
                                    except RuntimeError:
                                        pass

                                try:
                                    browser.textChanged.connect(update_browser_height)
                                    browser.document().contentsChanged.connect(update_browser_height)
                                except Exception:
                                    pass
                                QTimer.singleShot(0, update_browser_height)
                                self.layout.addWidget(browser)
            elif kind in ("tool", "discussion"):
                title = "Tool execution" if kind == "tool" else "選項結果"
                seen_sections.add(title)

                if title in existing_sections:
                    section = existing_sections[title]
                    content_for_section = content if content.strip() else "<i>Waiting for results...</i>"
                    section.update_content(content_for_section)
                    section.set_active(is_active)
                    self.layout.addWidget(section)
                else:
                    content_for_section = content
                    if is_active and not content.strip():
                        content_for_section = "<i>Waiting for results...</i>"
                    section = CollapsibleSection(
                        title, content_for_section, is_active=is_active,
                        on_toggle_callback=self._request_parent_update
                    )
                    self.layout.addWidget(section)
                    existing_sections[title] = section

        for title, section in list(existing_sections.items()):
            if title not in seen_sections:
                section.setParent(None)
                section.deleteLater()

        self.layout.addStretch(1)
        QTimer.singleShot(0, self._delayed_layout_refresh)
        QTimer.singleShot(50, self._recalculate_child_heights)

    def _parse_segments(self, text: str):
        tags = {
            "<tool-execution>": "tool",
            "</tool-execution>": "tool",
            "<discussion>": "discussion",
            "</discussion>": "discussion",
        }

        open_tags = {"<tool-execution>", "<discussion>"}
        close_tags = {"</tool-execution>", "</discussion>"}

        segments = []  # List of (kind, content, is_active)
        stack = ["normal"]
        pos = 0

        def add_segment(kind: str, chunk: str, active: bool = False) -> None:
            if not chunk and not active:
                return

            if segments and segments[-1][0] == kind:
                prev_kind, prev_chunk, prev_active = segments[-1]
                segments[-1] = (prev_kind, prev_chunk + chunk, prev_active or active)
            else:
                segments.append((kind, chunk, active))

        while pos < len(text):
            next_pos = None
            next_tag = None
            for tag in tags:
                idx = text.find(tag, pos)

                if idx == -1:
                    continue

                if next_pos is None or idx < next_pos:
                    next_pos = idx
                    next_tag = tag

            if next_pos is None:
                add_segment(stack[-1], text[pos:])
                break

            if next_pos > pos:
                add_segment(stack[-1], text[pos:next_pos])

            if next_tag in open_tags:
                new_kind = tags[next_tag]
                stack.append(new_kind)
                add_segment(new_kind, "", True)
            elif next_tag in close_tags and len(stack) > 1:
                closing_kind = stack.pop()
                for idx in range(len(segments) - 1, -1, -1):
                    seg_kind, seg_chunk, seg_active = segments[idx]
                    if seg_kind == closing_kind:
                        segments[idx] = (seg_kind, seg_chunk, False)
                        break
            pos = next_pos + len(next_tag)

        if len(stack) > 1:
            current_kind = stack[-1]
            if segments and segments[-1][0] == current_kind:
                seg_kind, seg_chunk, seg_active = segments[-1]
                segments[-1] = (seg_kind, seg_chunk, True)
            else:
                segments.append((current_kind, "", True))

        return segments

    def _update_animation(self):
        # Update animation angle and repaint.
        self._animation_angle = (self._animation_angle + 2) % 360
        self.update()

    def start_animation(self):
        # Start animated border to show agent is thinking.
        if not self._is_running:
            self._is_running = True
            self._animation_timer.start(16)

    def stop_animation(self):
        # Stop animated border to show agent is idle.
        if self._is_running:
            self._is_running = False
            self._animation_timer.stop()
            self.update()

    def paintEvent(self, event):
        # Custom paint to add animated outer ring.
        super().paintEvent(event)

        if not self._is_running:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        colors = [
            QColor("#6FD3C5"),
            QColor("#6B8FE5"),
            QColor("#9B8FEA"),
            QColor("#6ED0B2"),
        ]

        progress = self._animation_angle / 360.0
        color_index = int(progress * len(colors))
        next_color_index = (color_index + 1) % len(colors)
        t = (progress * len(colors)) - color_index

        current_color = colors[color_index]
        next_color = colors[next_color_index]

        r = int(current_color.red() + (next_color.red() - current_color.red()) * t)
        g = int(current_color.green() + (next_color.green() - current_color.green()) * t)
        b = int(current_color.blue() + (next_color.blue() - current_color.blue()) * t)

        border_color = QColor(r, g, b, 190)

        pen = QPen(border_color)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 30, 30)


class ArcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.arcs = [Arc() for i in range(20)]
        self.circle = Circle()  # 新增這行
        self.startAnime()

    def initUI(self):
        # self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 添加這行
        self.setStyleSheet("background-color:transparent;")  # 改為透明

    def startAnime(self):
        self.anim = QVariantAnimation(self, duration=10000)
        self.anim.setStartValue(0)
        self.anim.setEndValue(360)
        self.anim.valueChanged.connect(self.update)
        self.anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 取得圓圈顏色
        circle_color = self.circle.get_color(self.anim.currentValue())

        # 計算球球位置 - 固定在底部往上150px的位置
        ball_center_x = self.width() / 2
        # 從父視窗獲取固定位置參數，如果沒有則使用預設值
        parent = self.parent()
        if parent and hasattr(parent, 'BALL_CENTER_FROM_BOTTOM'):
            ball_center_y = self.height() - parent.BALL_CENTER_FROM_BOTTOM
        else:
            ball_center_y = self.height() - 150  # 預設值

        # 繪製多層底層發光圓 (Siri 般的層次感發光效果)
        # 第一層：核心高亮
        core_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter / 4
        )
        c_core = QColor(circle_color)
        c_core.setAlpha(180)
        core_grad.setColorAt(0, c_core)
        core_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(core_grad)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter / 2),
            int(ball_center_y - self.circle.diameter / 2),
            int(self.circle.diameter),
            int(self.circle.diameter),
        )

        # 第二層：中等擴散（縮小範圍，降低強度）
        mid_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter / 1.5
        )
        c_mid = QColor(circle_color)
        c_mid.setAlpha(80)
        mid_grad.setColorAt(0, c_mid)
        mid_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(mid_grad)
        # 縮小中層的繪製範圍以配合較小的漸層半徑
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter * (4.0 / 3.0) / 2),
            int(ball_center_y - self.circle.diameter * (4.0 / 3.0) / 2),
            int(self.circle.diameter * 4.0 / 3.0),
            int(self.circle.diameter * 4.0 / 3.0),
        )

        # 第三層：廣域外溢（大幅縮小外溢範圍，並降低透明度）
        outer_grad = QRadialGradient(
            ball_center_x, ball_center_y, self.circle.diameter * 1.0
        )
        c_outer = QColor(circle_color)
        c_outer.setAlpha(20)
        outer_grad.setColorAt(0, c_outer)
        outer_grad.setColorAt(1, Qt.transparent)

        painter.setBrush(outer_grad)
        # outer 使用 2x radius 的繪製範圍
        painter.drawEllipse(
            int(ball_center_x - self.circle.diameter),
            int(ball_center_y - self.circle.diameter),
            int(self.circle.diameter * 2),
            int(self.circle.diameter * 2),
        )

        # 繪製旋轉的圓弧
        for arc in self.arcs:
            pen = QPen(arc.color, 4, Qt.SolidLine)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(
                int(ball_center_x - arc.diameter / 2),
                int(ball_center_y - arc.diameter / 2),
                int(arc.diameter),
                int(arc.diameter),
                int(
                    self.anim.currentValue() * 16 * arc.direction + arc.startAngle * 100
                ),
                int(arc.span * 16),
            )

        if self.anim.currentValue() == 360:
            self.startAnime()


class EdgeHandle(QWidget):
    def __init__(self, on_activate=None):
        super().__init__(None)
        self._on_activate = on_activate
        self._collapsed_width = 16
        self._expanded_width = 24
        self._height = 140
        self._screen_geo = None
        self._side = "right"
        self._hovered = False
        self._active_glow = False
        self._glow_angle = 0
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(30)
        self._glow_timer.timeout.connect(self._tick_glow)
        self._dragging = False
        self._drag_start_global = None
        self._drag_offset = None
        self.setFixedSize(self._collapsed_width, self._height)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("")

    def _resolve_screen_geometry(self, reference=None):
        screen = None
        if reference is not None:
            try:
                screen = reference.screen()
            except Exception:
                screen = None
            if screen is None:
                try:
                    handle = reference.windowHandle()
                    if handle is not None:
                        screen = handle.screen()
                except Exception:
                    screen = None
        if screen is None:
            try:
                screen = QGuiApplication.screenAt(QCursor.pos())
            except Exception:
                screen = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _snap_to_edge(self, geo):
        width = self._expanded_width if self._hovered else self._collapsed_width
        self.setFixedSize(width, self._height)
        if self._side == "left":
            x = geo.left()
        else:
            x = geo.right() - width + 1
        y = self.y()
        y = max(geo.top(), min(y, geo.bottom() - self._height))
        self.setGeometry(x, y, width, self._height)

    def show_at_edge(self, reference=None):
        geo = self._resolve_screen_geometry(reference)
        if geo is None:
            return
        self._screen_geo = geo
        self._hovered = False

        # Auto-snap to the nearest horizontal edge based on the reference window position.
        if reference is not None:
            try:
                ref_center_x = reference.geometry().center().x()
                if abs(ref_center_x - geo.left()) <= abs(geo.right() - ref_center_x):
                    self._side = "left"
                else:
                    self._side = "right"
            except Exception:
                pass

        # Always derive vertical position from current window location;
        # do not persist collapsed handle height across cycles.
        if reference is not None:
            try:
                ref_geo = reference.frameGeometry()
                y = ref_geo.center().y() - (self._height // 2)
            except Exception:
                y = geo.bottom() - self._height
        else:
            y = geo.bottom() - self._height
        y = max(geo.top(), min(y, geo.bottom() - self._height))
        self.move(self.x(), y)
        self._snap_to_edge(geo)
        self.show()
        self.raise_()

    def set_active_glow(self, active: bool) -> None:
        if self._active_glow == active:
            return
        self._active_glow = active
        if active:
            if not self._glow_timer.isActive():
                self._glow_timer.start()
        else:
            if self._glow_timer.isActive():
                self._glow_timer.stop()
        self.update()

    def _tick_glow(self):
        self._glow_angle = (self._glow_angle + 6) % 360
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        geo = self._screen_geo or self._resolve_screen_geometry(None)
        if geo is None:
            return
        self._snap_to_edge(geo)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        geo = self._screen_geo or self._resolve_screen_geometry(None)
        if geo is None:
            return
        self._snap_to_edge(geo)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_global = event.globalPosition().toPoint()
            self._drag_offset = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        geo = self._resolve_screen_geometry(None)
        if geo is None:
            return
        self._screen_geo = geo
        new_x = event.globalPosition().toPoint().x() - self._drag_offset.x()
        new_y = event.globalPosition().toPoint().y() - self._drag_offset.y()
        new_y = max(geo.top(), min(new_y, geo.bottom() - self._height))
        self.move(new_x, new_y)

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            return
        self._dragging = False
        end_pos = event.globalPosition().toPoint()
        moved = (end_pos - self._drag_start_global).manhattanLength() if self._drag_start_global else 0
        geo = self._resolve_screen_geometry(None)
        if geo is not None:
            self._screen_geo = geo
            mid_x = self.geometry().center().x()
            if abs(mid_x - geo.left()) < abs(geo.right() - mid_x):
                self._side = "left"
            else:
                self._side = "right"
            self._hovered = False
            self._snap_to_edge(geo)
        if moved < 4 and self._on_activate:
            self._on_activate()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        base_color = QColor(32, 32, 32, 220)
        border_color = QColor(120, 255, 180, 200) if self._active_glow else QColor(255, 255, 255, 90)

        # Glow (animated when active)
        if self._active_glow:
            gradient = QConicalGradient(rect.center(), self._glow_angle)
            gradient.setColorAt(0.0, QColor(120, 255, 180, 0))
            gradient.setColorAt(0.05, QColor(120, 255, 180, 200))
            gradient.setColorAt(0.15, QColor(120, 255, 180, 0))
            gradient.setColorAt(1.0, QColor(120, 255, 180, 0))
            glow_pen = QPen(gradient, 6)
        else:
            glow_pen = QPen(QColor(160, 160, 160, 60), 4)
        glow_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 9, 9)

        # Body fill
        if self._hovered:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, QColor(18, 24, 34, 235))
            grad.setColorAt(0.35, QColor(22, 42, 60, 240))
            grad.setColorAt(0.6, QColor(30, 74, 92, 245))
            grad.setColorAt(0.82, QColor(44, 110, 120, 245))
            grad.setColorAt(1.0, QColor(64, 132, 140, 245))
        else:
            mid_dark = QColor(18, 18, 18, 230)
            edge_soft = QColor(38, 38, 38, 220)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if self._active_glow:
                wave = math.sin(math.radians(self._glow_angle))
                mid_pos = 0.45 + (wave * 0.06)
            else:
                mid_pos = 0.45
            grad.setColorAt(0.0, edge_soft)
            grad.setColorAt(max(0.2, min(0.8, mid_pos)), mid_dark)
            grad.setColorAt(1.0, edge_soft)

        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, 9, 9)


class TodoPanelWindow(QWidget):
    """Floating todo panel window shown separately from the main orb UI."""

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowTitle("Todo List")
        self.setMinimumSize(280, 360)
        self.resize(320, 460)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet(
            "QWidget { background-color: rgba(18, 22, 32, 238); color: #EAF3FF; }"
            "QLabel#todoPanelTitle { font-size: 13px; font-weight: bold; color: #F1F7FF; }"
            "QTextBrowser {"
            "background-color: rgba(11, 15, 22, 196);"
            "color: #EAF3FF;"
            "border: 1px solid rgba(120, 170, 230, 80);"
            "border-radius: 8px;"
            "padding: 6px;"
            "font-size: 12px;"
            "}"
        )

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 10)
        self.layout.setSpacing(6)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.title_label = QLabel("Todo List", header)
        self.title_label.setObjectName("todoPanelTitle")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.content = AutoWrapTextBrowser(self)
        self.content.setOpenExternalLinks(True)
        self.content.setMarkdown("_尚無 todo 資訊_")

        self.layout.addWidget(header)
        self.layout.addWidget(self.content, 1)

    def set_todo_text(self, text: str) -> None:
        data = (text or "").strip()
        if data:
            self.content.setMarkdown(f"```text\n{data}\n```")
        else:
            self.content.setMarkdown("_尚無 todo 資訊_")


class MainWindow(QMainWindow):
    # 信号：请求显示确认对话框
    confirm_requested = Signal(str, str, object)  # message, default_choice, result_container
    # 信号：请求显示问题选单对话框
    question_requested = Signal(str, list, bool, object)  # question, options, multi, result_container
    # 切換到聊天模式
    switch_to_chat = Signal()
    collapse_state_changed = Signal(bool)
    # 當使用者正在編輯輸入框（鍵入文字）時發出
    typing = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Assistant")
        # 固定視窗大小（調整為較窄寬度）
        self.FIXED_WIDTH = 300
        self.FIXED_HEIGHT = 800
        self.setGeometry(100, 100, self.FIXED_WIDTH, self.FIXED_HEIGHT)
        self.setFixedSize(self.FIXED_WIDTH, self.FIXED_HEIGHT)
        self.arcWidget = ArcWidget()
        # Essential for translucency and frameless, and always on top
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCentralWidget(self.arcWidget)

        self.old_pos = None  # 初始化拖拽位置
        self.input_callback = None  # 回調函數，用於處理用戶輸入
        self._stop_callback = None   # 停止 agent 的回調
        self._bypass_callback = None # bypass 模式切換回調
        
        # 固定球的位置參數（球心在底部往上130px，縮小與輸入框的距離）
        self.BALL_CENTER_FROM_BOTTOM = 130
        # 固定輸入框的位置（距離底部40px，使輸入框上移，與球更接近）
        self.INPUT_FROM_BOTTOM = 40
        self.INPUT_HEIGHT_BASE = 72    # input card (38) + separator (1) + toolbar (20) + margins
        self.INPUT_HEIGHT_CHIPS = 100  # + chip row (26) + spacing
        self.INPUT_HEIGHT = self.INPUT_HEIGHT_BASE

        # 移除右上角關閉按鈕以簡化 UI（由視窗系統或快捷鍵關閉）

        # 創建講話框 - 改用新設計的 SiriResponseBubble
        self.speech_bubble = SiriResponseBubble()
        self.speech_bubble.setParent(self)
        self.speech_bubble.setFixedSize(140, 160)
        self.speech_bubble.show()  # 初始顯示

        # Debounce speech bubble refresh to avoid flicker when streaming many chunks.
        self._pending_bubble_text = ""
        self._bubble_update_timer = QTimer(self)
        self._bubble_update_timer.setSingleShot(True)
        self._bubble_update_timer.timeout.connect(self._flush_bubble_update)
        self._mask_update_timer = QTimer(self)
        self._mask_update_timer.setSingleShot(True)
        self._mask_update_timer.timeout.connect(self._update_window_mask)

        # ── Input container (single card: [attach chips] / [input row] / [toolbar row]) ──
        self._attached_file_path: str = ""
        self._attached_images: list[bytes] = []   # multiple pasted images
        self._is_running = False
        self._bypass_mode = False  # auto-approve all permissions

        self.input_container = QWidget(self)
        self.input_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Outer vertical layout — no margins, contents sit inside the card
        outer_vbox = QVBoxLayout(self.input_container)
        outer_vbox.setContentsMargins(0, 0, 0, 0)
        outer_vbox.setSpacing(0)

        # ── Unified card widget (single rounded dark panel) ───────────────
        self._input_card = QWidget()
        self._input_card.setObjectName("InputCard")
        self._input_card.setStyleSheet(
            "#InputCard { "
            "background: rgba(28, 30, 38, 230); "
            "border: 1px solid rgba(255,255,255,35); "
            "border-radius: 18px; "
            "}"
        )
        card_vbox = QVBoxLayout(self._input_card)
        card_vbox.setContentsMargins(8, 6, 8, 6)
        card_vbox.setSpacing(4)

        # ── Attachment chip row (hidden until something is attached) ──────
        self._attach_row = QWidget()
        self._attach_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._attach_chips_layout = QHBoxLayout(self._attach_row)
        self._attach_chips_layout.setContentsMargins(2, 0, 2, 0)
        self._attach_chips_layout.setSpacing(5)
        self._attach_chips_layout.addStretch(1)
        self._attach_row.setFixedHeight(26)
        self._attach_row.hide()
        card_vbox.addWidget(self._attach_row)

        # ── Main input row ────────────────────────────────────────────────
        input_row_widget = QWidget()
        input_row_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        input_row = QHBoxLayout(input_row_widget)
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(4)

        self._voice_active = False
        self._voice_callback = None  # set by main.py: fn(text|None)

        self.voice_button = QPushButton("🎤")
        self.voice_button.setFixedSize(28, 28)
        self._voice_btn_idle_style = (
            "QPushButton { "
            "background: transparent; color: rgba(200,200,220,190); "
            "border: none; font-size: 14px; border-radius: 14px; "
            "}"
            "QPushButton:hover { background: rgba(255,255,255,12); }"
        )
        self._voice_btn_cancel_style = (
            "QPushButton { "
            "background: rgba(180,40,40,200); color: #fff; "
            "border: none; font-size: 13px; border-radius: 14px; "
            "}"
            "QPushButton:hover { background: rgba(210,55,55,230); }"
        )
        self.voice_button.setStyleSheet(self._voice_btn_idle_style)
        self.voice_button.clicked.connect(self.on_voice_requested)

        self.input_field = CommandLineEdit()
        self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
        self.input_field.setStyleSheet(
            "QLineEdit { "
            "background: transparent; "
            "color: #e8eaf0; "
            "border: none; "
            "padding: 2px 4px; "
            "font-size: 12px; "
            "}"
        )
        self.input_field.returnPressed.connect(self.on_input_submitted)
        try:
            self.input_field.textEdited.connect(self._handle_user_typing)
        except Exception:
            self.input_field.textChanged.connect(self._handle_user_typing)

        # Waveform widget — hidden until voice mode is active
        self._waveform = WaveformWidget()
        self._waveform.hide()

        self.send_button = QPushButton("發送")
        self.send_button.setFixedSize(52, 28)
        self._send_btn_send_style = (
            "QPushButton { "
            "background: #2FBF71; color: #fff; border: none; "
            "border-radius: 12px; font-weight: bold; font-size: 12px; "
            "}"
            "QPushButton:hover { background: #28A862; }"
        )
        self._send_btn_stop_style = (
            "QPushButton { "
            "background: rgba(210,55,55,220); color: #fff; border: none; "
            "border-radius: 12px; font-size: 11px; "
            "padding: 0 0 1px 0; "
            "}"
            "QPushButton:hover { background: rgba(230,70,70,240); }"
        )
        self.send_button.setStyleSheet(self._send_btn_send_style)
        self.send_button.clicked.connect(self.on_input_submitted)

        input_row.addWidget(self.voice_button)
        input_row.addWidget(self.input_field, 1)
        input_row.addWidget(self._waveform, 1)
        input_row.addWidget(self.send_button)
        card_vbox.addWidget(input_row_widget)

        # ── Separator line ────────────────────────────────────────────────
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("QWidget { background: rgba(255,255,255,18); border: none; }")
        card_vbox.addWidget(sep)

        # ── Toolbar row (inside card, has the card background) ────────────
        _tbtn = (
            "QPushButton { background: transparent; color: rgba(150,165,185,160); "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { color: rgba(210,225,255,220); background: rgba(255,255,255,8); }"
        )
        _tlbl = "QLabel { color: rgba(140,158,180,150); font-size: 10px; background: transparent; }"

        toolbar_row = QWidget()
        toolbar_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        toolbar_layout = QHBoxLayout(toolbar_row)
        toolbar_layout.setContentsMargins(2, 0, 2, 0)
        toolbar_layout.setSpacing(2)

        self._attach_btn = QPushButton("＋")
        self._attach_btn.setToolTip("附加檔案")
        self._attach_btn.setFixedSize(22, 20)
        self._attach_btn.setStyleSheet(_tbtn)
        self._attach_btn.clicked.connect(self._on_attach_file)
        toolbar_layout.addWidget(self._attach_btn)

        self._slash_btn = QPushButton("／")
        self._slash_btn.setToolTip("插入 /指令")
        self._slash_btn.setFixedSize(22, 20)
        self._slash_btn.setStyleSheet(_tbtn)
        self._slash_btn.clicked.connect(self._on_slash_shortcut)
        toolbar_layout.addWidget(self._slash_btn)

        self._total_tok_label = QLabel("Σ —")
        self._total_tok_label.setStyleSheet(_tlbl)
        self._total_tok_label.setToolTip("本次對話累計消耗 token 數（全部）")
        toolbar_layout.addWidget(self._total_tok_label)

        self._ctx_label = QLabel("ctx —")
        self._ctx_label.setStyleSheet(_tlbl)
        self._ctx_label.setToolTip("目前 context 窗口用量 / 最大值")
        toolbar_layout.addWidget(self._ctx_label)

        toolbar_layout.addStretch(1)

        # Bypass toggle button (right side of toolbar)
        self._bypass_btn = QPushButton("🔒")
        self._bypass_btn.setToolTip("全開模式：自動允許所有工具執行（再按恢復）")
        self._bypass_btn.setFixedSize(22, 20)
        self._bypass_btn.setCheckable(True)
        self._bypass_btn.setStyleSheet(_tbtn)
        self._bypass_btn.clicked.connect(self._on_bypass_toggled)
        toolbar_layout.addWidget(self._bypass_btn)

        # Chat mode switch button
        self._chat_switch_btn = QPushButton("💬")
        self._chat_switch_btn.setToolTip("切換到聊天介面")
        self._chat_switch_btn.setFixedSize(22, 20)
        self._chat_switch_btn.setStyleSheet(_tbtn)
        self._chat_switch_btn.clicked.connect(self.switch_to_chat.emit)
        toolbar_layout.addWidget(self._chat_switch_btn)

        card_vbox.addWidget(toolbar_row)
        outer_vbox.addWidget(self._input_card)

        # keep reference so existing code that calls toolbar_widget.show/hide still works
        self.toolbar_widget = toolbar_row

        # ── Compaction indicator (floating pill, hidden until compaction runs) ─
        self._compact_label = QLabel("✂ 壓縮記憶中…", self)
        self._compact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._compact_label.setFixedHeight(22)
        self._compact_label.setStyleSheet(
            "QLabel { background: rgba(90, 60, 160, 210); color: #ddc8ff; "
            "border: 1px solid rgba(180,140,255,120); border-radius: 11px; "
            "font-size: 10px; padding: 0 10px; }"
        )
        self._compact_label.hide()
        self._compact_pulse_timer = QTimer(self)
        self._compact_pulse_timer.setInterval(500)
        self._compact_pulse_timer.timeout.connect(self._pulse_compact_label)
        self._compact_pulse_phase = 0

        # ── Collapse / Todo buttons (floating on parent) ──────────────────
        self.collapse_button = QPushButton("收合", self)
        self.collapse_button.setFixedSize(60, 22)
        self.collapse_button.setStyleSheet(
            "QPushButton { "
            "background-color: rgba(45, 45, 45, 200); "
            "color: #FFFFFF; "
            "border: 1px solid rgba(255, 255, 255, 60); "
            "border-radius: 11px; "
            "font-size: 11px; "
            "}"
            "QPushButton:hover { background-color: rgba(70, 70, 70, 220); }"
        )
        self.collapse_button.clicked.connect(self.collapse_to_edge)
        self.collapse_button.hide()

        self.todo_toggle_button = QPushButton("Todo", self)
        self.todo_toggle_button.setFixedSize(54, 22)
        self.todo_toggle_button.setStyleSheet(
            "QPushButton { "
            "background-color: rgba(24, 52, 82, 210); "
            "color: #DCEFFF; "
            "border: 1px solid rgba(170, 210, 255, 120); "
            "border-radius: 11px; "
            "font-size: 11px; "
            "font-weight: bold; "
            "}"
            "QPushButton:hover { background-color: rgba(36, 72, 112, 230); }"
        )
        self.todo_toggle_button.clicked.connect(self.toggle_todo_drawer)
        self.todo_toggle_button.hide()
        self.todo_panel_window = TodoPanelWindow(self)
        self._todo_window_position_initialized = False
        self._todo_snapshot_text = ""

        self.input_container.hide()  # 初始隱藏

        self.edge_handle = EdgeHandle(on_activate=self.expand_from_edge)
        self._input_visible_before_collapse = False
        self._collapsed = False


        self.config_webview_window = None  # WebView 窗口引用

        self._pending_geometry_refresh = False

        # 连接确认信号到槽
        self.confirm_requested.connect(self._handle_confirm_request)
        self.question_requested.connect(self._handle_question_request)

        # 初始化窗口遮罩（點擊穿透）- 多次延遲更新確保完全渲染
        QTimer.singleShot(0, self._update_window_mask)
        QTimer.singleShot(100, self._update_window_mask)
        QTimer.singleShot(300, self._update_window_mask)

    def set_input_callback(self, callback):
        """設置輸入回調函數"""
        self.input_callback = callback

    def set_stop_callback(self, callback):
        """設置停止 agent 的回調函數"""
        self._stop_callback = callback
    
    def open_config_webview(self):
        """打開配置頁面 WebView"""
        try:
            if not HAS_WEBENGINE:
                error_msg = (
                    "無法打開內建 WebView：\n\n"
                    "PySide6-WebEngine 未安裝。\n\n"
                    "請在終端中執行：\n"
                    "pip install PySide6-WebEngine\n\n"
                    "或使用指令：/config （終端模式）"
                )
                self.update_speech_bubble(error_msg)
                logger.warning("WebEngine not available")
                return
            
            from internal.services import config_webui
            
            # 確保 Web UI 正在運行
            url = config_webui.ensure_webui_running()
            
            # 如果窗口已存在，顯示並激活
            if self.config_webview_window is not None:
                try:
                    self.config_webview_window.show()
                    self.config_webview_window.activateWindow()
                    self.config_webview_window.raise_()
                    logger.info("Config webview window reactivated")
                except RuntimeError:
                    # 窗口已被刪除，重新創建
                    self.config_webview_window = None
            
            if self.config_webview_window is None:
                # 創建新窗口
                self.config_webview_window = ConfigWebViewWindow(url, parent=self)
                self.config_webview_window.show()
                logger.info(f"Created new config webview: {url}")
            
        except ImportError as e:
            error_msg = f"無法打開配置頁面：\n{str(e)}\n\n請安裝 PySide6-WebEngine"
            self.update_speech_bubble(error_msg)
            logger.error(f"Failed to open config webview: {e}")
        except Exception as e:
            error_msg = f"無法打開配置頁面：{str(e)}"
            self.update_speech_bubble(error_msg)
            logger.error(f"Failed to open config webview: {e}", exc_info=True)

    @Slot(str, str, object)
    def _handle_confirm_request(self, message: str, default_choice: str, result_container: object):
        """槽函数：在主线程中处理确认请求"""
        try:
            logger.info(f"[主线程] Creating ConfirmDialog for: {message[:50]}...")
            dialog = ConfirmDialog(message, default_choice, parent=self)
            result_container.result = dialog.get_result()
            logger.info(f"[主线程] Dialog result: {result_container.result}")
        except Exception as e:
            logger.error(f"[主线程] Error in _handle_confirm_request: {e}", exc_info=True)
        finally:
            result_container.done.set()

    def show_confirm_dialog(self, message: str, default_choice: str = '') -> bool:
        """顯示確認對話框（線程安全）— 使用 threading.Event 等待，相容 asyncio 線程"""
        import threading
        logger.info(f"[工作线程] show_confirm_dialog called: {message[:50]}...")

        class ResultContainer:
            def __init__(self):
                self.result = False
                self.done = threading.Event()

        result_container = ResultContainer()
        self.confirm_requested.emit(message, default_choice, result_container)
        result_container.done.wait(timeout=300)  # 5-minute timeout
        logger.info(f"[工作线程] Dialog closed, returning: {result_container.result}")
        return result_container.result

    @Slot(str, list, bool, object)
    def _handle_question_request(self, question: str, options: list, multi: bool, result_container: object):
        """槽函數：在主線程中處理問題選單請求"""
        try:
            logger.info(f"[主线程] Creating ChoiceDialog for: {question[:50]}...")
            dialog = ChoiceDialog(question, options, multi=multi, parent=self)
            result_container.result = dialog.get_result()
            logger.info(f"[主线程] ChoiceDialog result: {result_container.result!r}")
        except Exception as e:
            logger.error(f"[主线程] Error in _handle_question_request: {e}", exc_info=True)
        finally:
            result_container.done.set()

    def show_question_dialog(self, question: str, options: list[str], multi: bool = False) -> str:
        """顯示問題選單對話框（線程安全）— 使用 threading.Event 等待，相容 asyncio 線程"""
        import threading
        logger.info(f"[工作线程] show_question_dialog called: {question[:50]}...")

        class ResultContainer:
            def __init__(self):
                self.result: str = ""
                self.done = threading.Event()

        result_container = ResultContainer()
        self.question_requested.emit(question, options, multi, result_container)
        result_container.done.wait(timeout=300)
        logger.info(f"[工作线程] ChoiceDialog closed, returning: {result_container.result!r}")
        return result_container.result

    def _position_input_container(self) -> None:
        bubble_width = getattr(self, "_current_bubble_width", None)
        if bubble_width:
            input_width = min(bubble_width, self.FIXED_WIDTH - 40)
        else:
            input_width = min(self.FIXED_WIDTH - 40, 500)
        x = (self.FIXED_WIDTH - input_width) // 2
        self.input_container.setGeometry(
            x,
            self.FIXED_HEIGHT - self.INPUT_HEIGHT - self.INPUT_FROM_BOTTOM,
            input_width,
            self.INPUT_HEIGHT,
        )
        self._position_collapse_button()
        self._position_todo_toggle_button()
        self._position_compact_label()

    def _position_compact_label(self) -> None:
        lbl_w = max(140, self._compact_label.sizeHint().width() + 20)
        lbl_h = 22
        input_rect = self.input_container.geometry()
        x = (self.FIXED_WIDTH - lbl_w) // 2
        y = input_rect.y() - lbl_h - 6
        self._compact_label.setGeometry(x, y, lbl_w, lbl_h)

    def _position_todo_toggle_button(self) -> None:
        btn_w = self.todo_toggle_button.width()
        btn_h = self.todo_toggle_button.height()
        input_rect = self.input_container.geometry()
        x = input_rect.center().x() - (btn_w // 2) - 66
        y = max(10, input_rect.y() - btn_h - 6)
        x = max(8, min(x, self.FIXED_WIDTH - btn_w - 8))
        self.todo_toggle_button.setGeometry(x, y, btn_w, btn_h)

    def _position_todo_window(self, *, force: bool = False) -> None:
        if self.todo_panel_window is None:
            return
        if self._todo_window_position_initialized and not force:
            return
        frame = self.frameGeometry()
        screen = self.screen() or QGuiApplication.screenAt(frame.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            screen_rect = screen.availableGeometry()
        else:
            screen_rect = QRect(frame.left(), frame.top(), frame.width(), frame.height())
        x, y = _compute_todo_window_position(
            frame,
            self.todo_toggle_button.geometry(),
            self.todo_panel_window.size(),
            screen_rect,
        )
        self.todo_panel_window.move(x, y)
        self._todo_window_position_initialized = True

    def toggle_todo_drawer(self) -> None:
        if self.todo_panel_window.isVisible():
            self.close_todo_drawer()
        else:
            self.open_todo_drawer()

    def open_todo_drawer(self) -> None:
        if self.todo_panel_window.isVisible():
            return
        self._position_todo_window()
        self.todo_panel_window.show()
        self.todo_panel_window.raise_()
        self.todo_panel_window.activateWindow()
        self._update_window_mask()

    def close_todo_drawer(self) -> None:
        if not self.todo_panel_window.isVisible():
            return
        self.todo_panel_window.hide()
        self._update_window_mask()

    def update_todo_drawer(self, text: str) -> None:
        self._todo_snapshot_text = (text or "").strip()
        self.todo_panel_window.set_todo_text(self._todo_snapshot_text)

    def _position_collapse_button(self) -> None:
        btn_w = self.collapse_button.width()
        btn_h = self.collapse_button.height()
        input_rect = self.input_container.geometry()
        x = input_rect.center().x() - (btn_w // 2)
        y = max(10, input_rect.y() - btn_h - 6)
        self.collapse_button.setGeometry(x, y, btn_w, btn_h)

    def show_input_container(self) -> None:
        self._position_input_container()
        self.input_container.show()
        self.collapse_button.show()
        self.todo_toggle_button.show()
        self._update_window_mask()

    # ── Toolbar actions ───────────────────────────────────────────────────

    def set_running(self, running: bool) -> None:
        """Toggle send/stop button between run mode and stop mode."""
        self._is_running = running
        if running:
            self.send_button.setText("")
            self.send_button.setIcon(_make_stop_icon(20))
            self.send_button.setIconSize(QSize(20, 20))
            self.send_button.setStyleSheet(self._send_btn_stop_style)
            self.send_button.clicked.disconnect()
            self.send_button.clicked.connect(self._on_stop_requested)
        else:
            self.send_button.setIcon(QIcon())  # clear icon
            self.send_button.setText("發送")
            self.send_button.setStyleSheet(self._send_btn_send_style)
            self.send_button.clicked.disconnect()
            self.send_button.clicked.connect(self.on_input_submitted)

    def _on_stop_requested(self) -> None:
        if self._stop_callback:
            self._stop_callback()

    def set_bypass_callback(self, callback) -> None:
        """Set callback invoked when bypass mode is toggled. callback(enabled: bool)"""
        self._bypass_callback = callback

    def _on_bypass_toggled(self, checked: bool) -> None:
        self._bypass_mode = checked
        _bypass_on = (
            "QPushButton { background: rgba(220,120,0,180); color: #ffe0a0; "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { background: rgba(240,140,0,210); }"
        )
        _bypass_off = (
            "QPushButton { background: transparent; color: rgba(150,165,185,160); "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { color: rgba(210,225,255,220); background: rgba(255,255,255,8); }"
        )
        if checked:
            self._bypass_btn.setText("🔓")
            self._bypass_btn.setToolTip("全開模式已開啟 — 自動允許所有工具（點擊關閉）")
            self._bypass_btn.setStyleSheet(_bypass_on)
        else:
            self._bypass_btn.setText("🔒")
            self._bypass_btn.setToolTip("全開模式：自動允許所有工具執行（再按恢復）")
            self._bypass_btn.setStyleSheet(
                "QPushButton { background: transparent; color: rgba(150,165,185,160); "
                "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
                "QPushButton:hover { color: rgba(210,225,255,220); background: rgba(255,255,255,8); }"
            )
        cb = getattr(self, "_bypass_callback", None)
        if cb:
            cb(checked)

    def is_bypass_mode(self) -> bool:
        return self._bypass_mode

    def update_context_meter(self, used_tokens: int, max_tokens: int, total_tokens: int = 0) -> None:
        """Update the token usage labels in the toolbar.

        Args:
            used_tokens:  tokens currently in the context window
            max_tokens:   maximum context window size
            total_tokens: cumulative tokens consumed across the whole session
        """
        def _fmt(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}k"
            return str(n)

        if max_tokens > 0:
            pct = min(100, round(used_tokens * 100 / max_tokens))
            ctx_color = "#f06b6b" if pct >= 80 else "#f0c060" if pct >= 50 else "rgba(160,180,200,160)"
            self._ctx_label.setText(f"ctx {_fmt(used_tokens)}/{_fmt(max_tokens)} ({pct}%)")
            self._ctx_label.setStyleSheet(f"QLabel {{ color: {ctx_color}; font-size: 10px; }}")

        if total_tokens > 0:
            self._total_tok_label.setText(f"Σ {_fmt(total_tokens)}")
        else:
            self._total_tok_label.setText("Σ —")

    # ── Chip style helpers ────────────────────────────────────────────────
    _CHIP_STYLE = (
        "QLabel { background: rgba(45,55,80,200); color: #a8d4ff; "
        "border: 1px solid rgba(90,140,220,100); border-radius: 8px; "
        "padding: 2px 8px; font-size: 11px; }"
    )
    _CHIP_CLOSE_STYLE = (
        "QPushButton { background: transparent; color: rgba(160,170,200,160); "
        "border: none; font-size: 9px; padding: 0; } "
        "QPushButton:hover { color: #ff6b6b; }"
    )

    def _add_chip(self, label: str, on_remove) -> None:
        """Insert a chip + ✕ button pair into the attach row (before the stretch)."""
        chip = QLabel(label)
        chip.setStyleSheet(self._CHIP_STYLE)
        chip.setMaximumWidth(200)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(14, 14)
        close_btn.setStyleSheet(self._CHIP_CLOSE_STYLE)

        # Store refs on buttons for cleanup
        chip._close_btn = close_btn

        def _remove():
            on_remove()
            # Remove chip + close_btn from layout
            for w in (chip, close_btn):
                self._attach_chips_layout.removeWidget(w)
                w.deleteLater()
            self._refresh_chip_row()

        close_btn.clicked.connect(_remove)

        # Insert before the trailing stretch (last item)
        insert_pos = max(0, self._attach_chips_layout.count() - 1)
        self._attach_chips_layout.insertWidget(insert_pos, chip)
        self._attach_chips_layout.insertWidget(insert_pos + 1, close_btn)
        self._refresh_chip_row()

    def _refresh_chip_row(self) -> None:
        """Show/hide the chip row and reposition the container accordingly."""
        has_chips = self._attach_chips_layout.count() > 1  # >1 means chips present (not just stretch)
        if has_chips:
            self._attach_row.show()
            self.INPUT_HEIGHT = self.INPUT_HEIGHT_CHIPS
        else:
            self._attach_row.hide()
            self.INPUT_HEIGHT = self.INPUT_HEIGHT_BASE
        if self.input_container.isVisible():
            self._position_input_container()

    def _show_attach_chip(self, label: str) -> None:
        """Add an image chip (called for clipboard paste)."""
        idx = len(self._attached_images) - 1  # index of the image just appended

        def on_remove():
            # Remove this specific image by index (find by closure)
            try:
                if 0 <= idx < len(self._attached_images):
                    self._attached_images.pop(idx)
            except Exception:
                pass

        self._add_chip(label, on_remove)

    def _clear_attachment(self) -> None:
        """Clear ALL attachments and remove all chips."""
        self._attached_file_path = ""
        self._attached_images = []
        # Remove all chip widgets (everything except the trailing stretch)
        while self._attach_chips_layout.count() > 1:
            item = self._attach_chips_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._refresh_chip_row()

    def _on_attach_file(self) -> None:
        """Open file dialog and attach a file to the next message."""
        path, _ = QFileDialog.getOpenFileName(
            self, "附加檔案", "", "All Files (*.*)"
        )
        if path:
            self._attached_file_path = path
            name = path.split("/")[-1].split("\\")[-1]
            short = name if len(name) <= 20 else name[:17] + "…"

            def on_remove():
                self._attached_file_path = ""

            self._add_chip(f"📎 {short}", on_remove)

    def _on_slash_shortcut(self) -> None:
        """Insert '/' into the input field to trigger command completion."""
        if not self.input_field.text():
            self.input_field.setText("/")
            self.input_field.setFocus()
            self.input_field.setCursorPosition(1)

    def get_attached_file_path(self) -> str:
        """Return path of attached file (cleared after retrieval)."""
        path = self._attached_file_path
        if path:
            self._attached_file_path = ""
            self._clear_attachment()
        return path

    def get_attached_image_data(self) -> bytes:
        """Return first pasted image bytes (legacy; use pop_attached_images_as_tempfiles for multi)."""
        if self._attached_images:
            return self._attached_images[0]
        return b""

    def pop_attached_images_as_tempfiles(self) -> list[str]:
        """Save all pasted images to temp PNG files and return their paths.
        Clears the image list. Caller is responsible for deleting the files."""
        if not self._attached_images:
            return []
        import tempfile, os
        paths = []
        for data in self._attached_images:
            fd, path = tempfile.mkstemp(suffix=".png", prefix="agent_clip_")
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            paths.append(path)
        self._attached_images = []
        self._clear_attachment()
        return paths

    def pop_attached_image_as_tempfile(self) -> str:
        """Legacy single-image version — returns first image path only."""
        paths = self.pop_attached_images_as_tempfiles()
        return paths[0] if paths else ""

    # ── Input callback ────────────────────────────────────────────────────

    def _handle_user_typing(self, *_args):
        """Slot: triggered when the user edits the input field.
        Emits the `typing` signal for external consumers to reset idle timers."""
        try:
            self.typing.emit()
        except Exception:
            pass

    def hide_input_container(self) -> None:
        self.input_container.hide()
        self.collapse_button.hide()
        self.todo_toggle_button.hide()
        self._update_window_mask()

    def toggle_input_container(self) -> None:
        if self.input_container.isVisible():
            self.hide_input_container()
        else:
            self.show_input_container()

    def collapse_to_edge(self) -> None:
        if self._collapsed:
            return
        self._input_visible_before_collapse = self.input_container.isVisible()
        self.close_todo_drawer()
        self.edge_handle.show_at_edge(self)
        self.edge_handle.raise_()
        self.hide()
        self._collapsed = True
        self.collapse_state_changed.emit(True)

    def expand_from_edge(self) -> None:
        if not self._collapsed:
            return
        self.edge_handle.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        if self._input_visible_before_collapse:
            self.show_input_container()
        self._update_window_mask()
        self._collapsed = False

    def on_input_submitted(self):
        """處理文字輸入提交"""
        text = self.input_field.text().strip()
        if text and self.input_callback:
            # 添加到歷史記錄
            if isinstance(self.input_field, CommandLineEdit):
                self.input_field.add_to_history(text)
            self.input_field.clear()
            self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
            self.input_callback(text)

    # ── Voice mode ────────────────────────────────────────────────────────

    def set_voice_callback(self, cb) -> None:
        """cb(text: str|None) called when voice recognition finishes or is cancelled."""
        self._voice_callback = cb

    def on_voice_requested(self):
        if self._voice_active:
            self._cancel_voice()
        else:
            self._enter_voice_mode()

    def _enter_voice_mode(self) -> None:
        self._voice_active = True
        # Swap text field → waveform
        self.input_field.hide()
        self._waveform.show()
        self._waveform.start()
        # Voice button → cancel (✕)
        self.voice_button.setText("✕")
        self.voice_button.setStyleSheet(self._voice_btn_cancel_style)
        # Send button becomes "送出語音"
        self._prev_send_click = None
        try:
            self.send_button.clicked.disconnect()
        except Exception:
            pass
        self.send_button.clicked.connect(self._submit_voice_now)
        # Notify main.py to start recognition
        if self._voice_callback:
            self._voice_callback("__start__")

    def _exit_voice_mode(self) -> None:
        self._voice_active = False
        self._waveform.stop()
        self._waveform.hide()
        self.input_field.show()
        self.input_field.setFocus()
        self.voice_button.setText("🎤")
        self.voice_button.setStyleSheet(self._voice_btn_idle_style)
        # Restore send button
        try:
            self.send_button.clicked.disconnect()
        except Exception:
            pass
        if self._is_running:
            self.send_button.clicked.connect(self._on_stop_requested)
        else:
            self.send_button.clicked.connect(self.on_input_submitted)

    def _cancel_voice(self) -> None:
        self._exit_voice_mode()
        if self._voice_callback:
            self._voice_callback("__cancel__")

    def _submit_voice_now(self) -> None:
        """User pressed send during recording — commit immediately."""
        self._exit_voice_mode()
        if self._voice_callback:
            self._voice_callback("__submit__")

    def set_voice_level(self, level: float) -> None:
        """Called from voice worker thread (via queued signal) to update waveform."""
        if self._voice_active:
            self._waveform.set_level(level)

    def voice_result_ready(self, text: str | None) -> None:
        """Called when recognition finishes. Appends recognized text to the input field."""
        if not self._voice_active:
            return
        self._exit_voice_mode()
        if text:
            existing = self.input_field.text().strip()
            sep = " " if existing else ""
            self.input_field.setText(existing + sep + text)
            self.input_field.setFocus()
            # Move cursor to end
            self.input_field.setCursorPosition(len(self.input_field.text()))

    # --- Mouse Events for dragging the window ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        self.old_pos = None
        event.accept()

    def showEvent(self, event):
        """窗口顯示時更新遮罩"""
        super().showEvent(event)
        # 延遲更新以確保所有子元素都已渲染
        QTimer.singleShot(100, self._update_window_mask)

    def closeEvent(self, event):
        try:
            if self.todo_panel_window is not None:
                self.todo_panel_window.close()
        except Exception:
            pass
        super().closeEvent(event)

    def _update_window_mask(self):
        """更新窗口遮罩，定義可交互區域（跨平台方案）"""
        from PySide6.QtGui import QRegion
        from PySide6.QtCore import QRect

        region = QRegion()

        # 添加輸入框區域（使用更寬鬆的範圍）
        if self.input_container.isVisible():
            # 使用整個底部區域，而不是精確的輸入框位置
            # 這樣可以避免邊緣被截斷
            bottom_area = QRect(
                0,
                self.FIXED_HEIGHT - 150,  # 底部 150 像素（增加高度避免截斷）
                self.FIXED_WIDTH,
                150
            )
            region = region.united(QRegion(bottom_area))
        else:
            # 即使輸入框不可見，也保留一小塊底部區域用於雙擊
            bottom_area = QRect(
                0,
                self.FIXED_HEIGHT - 80,
                self.FIXED_WIDTH,
                80
            )
            region = region.united(QRegion(bottom_area))

        # 添加氣泡區域
        if self.collapse_button.isVisible():
            btn_rect = self.collapse_button.geometry()
            btn_rect.adjust(-6, -6, 6, 6)
            region = region.united(QRegion(btn_rect))

        if self.speech_bubble.isVisible():
            bubble_rect = self.speech_bubble.geometry()
            # 擴大以便於拖拽和完整顯示
            bubble_rect.adjust(-15, -15, 15, 15)
            region = region.united(QRegion(bubble_rect))

        # 添加球的區域（圓形）
        ball_center_x = int(self.FIXED_WIDTH / 2)
        ball_center_y = int(self.FIXED_HEIGHT - self.BALL_CENTER_FROM_BOTTOM)
        ball_radius = 120  # 加大半徑

        ball_region = QRegion(
            ball_center_x - ball_radius,
            ball_center_y - ball_radius,
            ball_radius * 2,
            ball_radius * 2,
            QRegion.RegionType.Ellipse
        )
        region = region.united(ball_region)

        # 設置窗口遮罩
        self.setMask(region)

    def mouseDoubleClickEvent(self, event):
        self.toggle_input_container()
        event.accept()

    def update_speech_bubble(self, text):
        """更新對話框內容，輸出框疊到球的上方一半"""
        self._pending_bubble_text = text or ""
        if not self._bubble_update_timer.isActive():
            self._bubble_update_timer.start(40)

    def _flush_bubble_update(self):
        self.speech_bubble.set_content(self._pending_bubble_text)

        # 延遲處理事件，避免阻塞主線程
        QTimer.singleShot(0, self._update_bubble_geometry)
        # Merge mask refresh requests instead of stacking many singleShots.
        self._mask_update_timer.start(120)

    def start_agent_animation(self):
        """啟動 agent 運行動畫"""
        self.speech_bubble.start_animation()
        self.edge_handle.set_active_glow(True)

    def stop_agent_animation(self):
        """停止 agent 運行動畫"""
        self.speech_bubble.stop_animation()
        self.edge_handle.set_active_glow(False)

    def set_compact_indicator(self, active: bool) -> None:
        """Show or hide the compaction-in-progress indicator."""
        if active:
            self._position_compact_label()
            self._compact_label.show()
            self._compact_label.raise_()
            self._compact_pulse_phase = 0
            self._compact_pulse_timer.start()
        else:
            self._compact_pulse_timer.stop()
            self._compact_label.hide()

    def _pulse_compact_label(self) -> None:
        """Alternate label opacity to create a pulsing effect."""
        self._compact_pulse_phase = 1 - self._compact_pulse_phase
        if self._compact_pulse_phase:
            self._compact_label.setStyleSheet(
                "QLabel { background: rgba(110, 75, 190, 230); color: #eedeff; "
                "border: 1px solid rgba(200,160,255,160); border-radius: 11px; "
                "font-size: 10px; padding: 0 10px; }"
            )
        else:
            self._compact_label.setStyleSheet(
                "QLabel { background: rgba(70, 45, 130, 180); color: #c8aaee; "
                "border: 1px solid rgba(160,120,220,90); border-radius: 11px; "
                "font-size: 10px; padding: 0 10px; }"
            )
    
    def _update_bubble_geometry(self):
        """更新氣泡幾何形狀（延遲調用以避免阻塞）"""
        try:
            # 計算氣泡大小
            padding = 60
            bubble_width = self.FIXED_WIDTH - 20
            self._current_bubble_width = bubble_width

            # 計算內容需要的高度
            needed_height = self.speech_bubble.content_height() + padding
            # 氣泡最大高度限制
            max_bubble_height = self.FIXED_HEIGHT - 200
            bubble_height = min(
                max(needed_height, 80),  # 最小高度改為80
                max_bubble_height,
            )
            
            self.speech_bubble.setFixedSize(bubble_width, bubble_height)



            # 計算氣泡位置：疊到球的一半
            window_center_x = self.FIXED_WIDTH // 2
            # 球心位於底部往上BALL_CENTER_FROM_BOTTOM的位置
            ball_center_y = self.FIXED_HEIGHT - self.BALL_CENTER_FROM_BOTTOM
            
            # 氣泡只疊到球的一半（氣泡下邊緣對齊球心）
            bubble_x = window_center_x - bubble_width // 2
            bubble_y = ball_center_y - bubble_height
            
            # 確保氣泡不會超出視窗邊界
            bubble_x = max(10, min(bubble_x, self.FIXED_WIDTH - bubble_width - 10))
            bubble_y = max(20, min(bubble_y, self.FIXED_HEIGHT - bubble_height - 80))

            # 設置講話框位置
            self.speech_bubble.move(bubble_x, bubble_y)
            if not self.speech_bubble.isVisible():
                self.speech_bubble.show()

            # 更新輸入容器位置（固定在視窗底部）
            if self.input_container.isVisible():
                input_width = min(self.FIXED_WIDTH - 40, 500)
                self.input_container.setGeometry(
                    (self.FIXED_WIDTH - input_width) // 2,
                    self.FIXED_HEIGHT - self.INPUT_HEIGHT - self.INPUT_FROM_BOTTOM,
                    input_width,
                    self.INPUT_HEIGHT,
                )
                self.input_container.show()

            # 更新窗口遮罩
            self._update_window_mask()
        except Exception as e:
            logger.error(f"Bubble geometry update error: {e}")


# ─────────────────────���───────────────────────────────────────────────────────
# ChatWindow — chat-style interface that can switch with the circle mode
# ─────────────────────────────────────────────────────────────────────────────

class _InlineQuestionBubble(QFrame):
    """Left-aligned inline question bubble shown in chat mode for AskUserQuestion.

    Supports single-choice (default) and multi-choice modes.
    Both modes include a custom free-text input option.
    The bubble remains in the chat log after the user answers.
    """
    answered = Signal(str)  # emitted (in main thread) when user picks/submits

    _BTN_STYLE = (
        "QPushButton {"
        "background: rgba(50,80,160,180); color: #c0d8ff;"
        "border: 1px solid rgba(100,150,255,100); border-radius: 8px;"
        "padding: 6px 14px; font-size: 12px; text-align: left;"
        "}"
        "QPushButton:hover { background: rgba(70,110,200,210); color: #d8eaff; }"
        "QPushButton:disabled {"
        "background: rgba(30,40,60,100); color: rgba(120,140,180,100);"
        "border-color: rgba(60,80,120,50);"
        "}"
    )
    _CONFIRM_BTN_STYLE = (
        "QPushButton {"
        "background: rgba(0,100,200,200); color: #fff;"
        "border: none; border-radius: 8px;"
        "padding: 6px 18px; font-size: 12px;"
        "}"
        "QPushButton:hover { background: rgba(0,120,240,220); }"
        "QPushButton:disabled { background: rgba(30,40,60,100); color: rgba(120,140,180,100); }"
    )
    _CB_STYLE = (
        "QCheckBox { color: #c0d8ff; font-size: 12px; background: transparent; spacing: 6px; }"
        "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;"
        "border: 1px solid rgba(100,150,255,100); background: rgba(30,50,100,180); }"
        "QCheckBox::indicator:checked { background: rgba(0,120,220,200);"
        "border-color: rgba(80,160,255,180); }"
        "QCheckBox:disabled { color: rgba(120,140,180,100); }"
    )

    def __init__(self, question: str, options: list[str], multi: bool = False, parent=None):
        super().__init__(parent)
        self._done = False
        self._multi = multi
        self._option_btns: list[QPushButton] = []
        self._checkboxes: list[QCheckBox] = []
        self._custom_input: QLineEdit | None = None
        self._custom_cb: QCheckBox | None = None
        self._confirm_btn: QPushButton | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 60, 4)
        outer.setSpacing(0)

        card = QWidget()
        card.setObjectName("IQCard")
        card.setStyleSheet(
            "#IQCard {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(24,40,80,235),stop:1 rgba(18,32,68,228));"
            "border: 1px solid rgba(56,190,220,70);"
            "border-radius: 14px;"
            "}"
        )
        card_vbox = QVBoxLayout(card)
        card_vbox.setContentsMargins(14, 12, 14, 12)
        card_vbox.setSpacing(8)

        # Question label
        header_text = "☑️ 請選擇（可多選）" if multi else "❓ 請選擇"
        q_lbl = QLabel()
        q_lbl.setTextFormat(Qt.TextFormat.RichText)
        q_lbl.setWordWrap(True)
        q_lbl.setText(
            f'<span style="color:#38c8d8;font-size:11px;">{header_text}</span><br>'
            + html.escape(question).replace("\n", "<br>")
        )
        q_lbl.setStyleSheet(
            "QLabel { color: #d8e8ff; font-size: 13px; background: transparent; }"
        )
        card_vbox.addWidget(q_lbl)

        if multi:
            # ── Multi-select: checkboxes ───────────────────────────────
            for opt in options:
                cb = QCheckBox(opt)
                cb.setStyleSheet(self._CB_STYLE)
                card_vbox.addWidget(cb)
                self._checkboxes.append(cb)

            # Custom input checkbox + line edit
            self._custom_cb = QCheckBox("✏️ 自訂輸入…")
            self._custom_cb.setStyleSheet(self._CB_STYLE)
            card_vbox.addWidget(self._custom_cb)

            self._custom_input = QLineEdit()
            self._custom_input.setPlaceholderText("請輸入自訂答案…")
            self._custom_input.setStyleSheet(
                "QLineEdit { background: rgba(30,45,90,200); color: #d8e8ff;"
                "border: 1px solid rgba(100,150,255,80); border-radius: 6px;"
                "padding: 4px 8px; font-size: 12px; }"
                "QLineEdit:focus { border-color: rgba(80,160,255,180); }"
                "QLineEdit:disabled { background: rgba(20,28,55,100); color: rgba(120,140,180,100); }"
            )
            self._custom_input.setEnabled(False)
            self._custom_input.hide()
            card_vbox.addWidget(self._custom_input)
            self._custom_cb.toggled.connect(self._on_custom_cb_toggled)

            # Confirm button
            self._confirm_btn = QPushButton("✓ 確認")
            self._confirm_btn.setStyleSheet(self._CONFIRM_BTN_STYLE)
            self._confirm_btn.clicked.connect(self._submit_multi)
            card_vbox.addWidget(self._confirm_btn, 0, Qt.AlignmentFlag.AlignRight)

        else:
            # ── Single-select: buttons ─────────────────────────────────
            for opt in options:
                btn = QPushButton(opt)
                btn.setStyleSheet(self._BTN_STYLE)
                btn.clicked.connect(lambda _checked, o=opt: self._select(o))
                card_vbox.addWidget(btn)
                self._option_btns.append(btn)

            # Custom input button
            custom_btn = QPushButton("✏️ 自訂輸入…")
            custom_btn.setStyleSheet(self._BTN_STYLE)
            custom_btn.clicked.connect(self._show_custom_input)
            card_vbox.addWidget(custom_btn)
            self._option_btns.append(custom_btn)

            # Hidden custom input row
            self._custom_input = QLineEdit()
            self._custom_input.setPlaceholderText("請輸入自訂答案…")
            self._custom_input.setStyleSheet(
                "QLineEdit { background: rgba(30,45,90,200); color: #d8e8ff;"
                "border: 1px solid rgba(100,150,255,80); border-radius: 6px;"
                "padding: 4px 8px; font-size: 12px; }"
                "QLineEdit:focus { border-color: rgba(80,160,255,180); }"
            )
            self._custom_input.returnPressed.connect(self._submit_custom)
            self._custom_input.hide()

            self._confirm_btn = QPushButton("✓ 確認")
            self._confirm_btn.setStyleSheet(self._CONFIRM_BTN_STYLE)
            self._confirm_btn.clicked.connect(self._submit_custom)
            self._confirm_btn.hide()

            card_vbox.addWidget(self._custom_input)
            card_vbox.addWidget(self._confirm_btn, 0, Qt.AlignmentFlag.AlignRight)

        # Answer label (hidden until answered)
        self._answer_lbl = QLabel()
        self._answer_lbl.setStyleSheet(
            "QLabel { color: #7ddfb0; font-size: 12px; background: transparent; }"
        )
        self._answer_lbl.hide()
        card_vbox.addWidget(self._answer_lbl)

        outer.addWidget(card, 1)

    # ── single-select helpers ──────────────────────────────────────────────

    def _show_custom_input(self) -> None:
        if self._done:
            return
        for btn in self._option_btns:
            btn.hide()
        self._custom_input.show()
        self._confirm_btn.show()
        self._custom_input.setFocus()

    def _submit_custom(self) -> None:
        text = (self._custom_input.text() or "").strip()
        if not text:
            return
        self._finish(text)

    def _select(self, option: str) -> None:
        if self._done:
            return
        for btn in self._option_btns:
            btn.setEnabled(False)
            if btn.text() == option:
                btn.setStyleSheet(
                    btn.styleSheet()
                    + "QPushButton:disabled {"
                    "background: rgba(40,90,60,160); color: #90e8b8;"
                    "border-color: rgba(80,200,120,120);"
                    "}"
                )
        self._finish(option)

    # ── multi-select helpers ───────────────────────────────────────────────

    def _on_custom_cb_toggled(self, checked: bool) -> None:
        self._custom_input.setEnabled(checked)
        if checked:
            self._custom_input.show()
            self._custom_input.setFocus()
        else:
            self._custom_input.hide()

    def _submit_multi(self) -> None:
        if self._done:
            return
        selected = [cb.text() for cb in self._checkboxes if cb.isChecked()]
        if self._custom_cb and self._custom_cb.isChecked():
            custom_text = (self._custom_input.text() or "").strip() if self._custom_input else ""
            if custom_text:
                selected.append(custom_text)
        if not selected:
            return
        # Disable all controls
        for cb in self._checkboxes:
            cb.setEnabled(False)
        if self._custom_cb:
            self._custom_cb.setEnabled(False)
        if self._custom_input:
            self._custom_input.setEnabled(False)
        if self._confirm_btn:
            self._confirm_btn.setEnabled(False)
        self._finish(", ".join(selected))

    # ── common ────────────────────────────────────────────────────────────

    def _finish(self, result: str) -> None:
        self._done = True
        self._answer_lbl.setText(f"✓ 已選擇：{result}")
        self._answer_lbl.show()
        self.answered.emit(result)


class _InlineConfirmBubble(QFrame):
    """Left-aligned inline permission-confirm bubble for chat mode."""

    answered = Signal(bool)  # True = allow, False = deny

    _DANGER_KEYWORDS = {"delete", "remove", "rm ", "drop", "kill", "truncate", "format", "wipe"}

    def __init__(self, message: str, default_choice: str = '', parent=None):
        super().__init__(parent)
        self._done = False

        is_danger = any(kw in message.lower() for kw in self._DANGER_KEYWORDS)
        icon_char = "⚠️" if is_danger else "🔧"

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 60, 4)
        outer.setSpacing(0)

        card = QWidget()
        card.setObjectName("ICCard")
        _border = "rgba(220,100,80,80)" if is_danger else "rgba(150,100,240,70)"
        card.setStyleSheet(
            "#ICCard {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(28,22,52,235),stop:1 rgba(22,18,44,228));"
            f"border: 1px solid {_border};"
            "border-radius: 14px;"
            "}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(14, 12, 14, 12)
        vbox.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        icon_lbl.setFixedWidth(28)
        title_lbl = QLabel("工具執行請求")
        title_lbl.setStyleSheet(
            "QLabel { color: #d0b0ff; font-size: 13px; font-weight: bold; background: transparent; }"
        )
        hdr.addWidget(icon_lbl)
        hdr.addWidget(title_lbl, 1)
        vbox.addLayout(hdr)

        # Message body
        body_lbl = QLabel()
        body_lbl.setTextFormat(Qt.TextFormat.PlainText)
        body_lbl.setWordWrap(True)
        body_lbl.setText(message)
        body_lbl.setStyleSheet(
            "QLabel { color: #b0b8d8; font-size: 12px; background: transparent; }"
        )
        vbox.addWidget(body_lbl)

        # Buttons
        _allow_style = (
            "QPushButton {"
            "background: rgba(0,100,200,180); color: #c8dfff;"
            "border: 1px solid rgba(80,160,255,120); border-radius: 8px;"
            "padding: 7px 14px; font-size: 12px; text-align: left;"
            "}"
            "QPushButton:hover { background: rgba(0,120,240,210); }"
            "QPushButton:disabled {"
            "background: rgba(20,30,50,100); color: rgba(80,120,180,100);"
            "border-color: rgba(40,60,120,50);"
            "}"
        )
        _deny_style = (
            "QPushButton {"
            "background: rgba(60,60,80,180); color: #c0c0cc;"
            "border: 1px solid rgba(255,255,255,40); border-radius: 8px;"
            "padding: 7px 14px; font-size: 12px; text-align: left;"
            "}"
            "QPushButton:hover { background: rgba(80,80,100,210); }"
            "QPushButton:disabled {"
            "background: rgba(30,30,40,80); color: rgba(100,100,120,80);"
            "border-color: rgba(60,60,80,40);"
            "}"
        )

        self._allow_btn = QPushButton("  ✅ 允許執行  (Y)")
        self._allow_btn.setStyleSheet(_allow_style)
        self._allow_btn.clicked.connect(lambda: self._select(True))
        vbox.addWidget(self._allow_btn)

        self._deny_btn = QPushButton("  ❌ 拒絕  (N)")
        self._deny_btn.setStyleSheet(_deny_style)
        self._deny_btn.clicked.connect(lambda: self._select(False))
        vbox.addWidget(self._deny_btn)

        # Result label (hidden until answered)
        self._result_lbl = QLabel()
        self._result_lbl.setStyleSheet(
            "QLabel { font-size: 12px; background: transparent; }"
        )
        self._result_lbl.hide()
        vbox.addWidget(self._result_lbl)

        if default_choice.upper() == 'Y':
            self._allow_btn.setFocus()
        else:
            self._deny_btn.setFocus()

        outer.addWidget(card, 1)

    def _select(self, allow: bool) -> None:
        if self._done:
            return
        self._done = True
        self._allow_btn.setEnabled(False)
        self._deny_btn.setEnabled(False)
        if allow:
            self._result_lbl.setStyleSheet(
                "QLabel { color: #7ddfb0; font-size: 12px; background: transparent; }"
            )
            self._result_lbl.setText("✓ 已允許")
        else:
            self._result_lbl.setStyleSheet(
                "QLabel { color: #df7d7d; font-size: 12px; background: transparent; }"
            )
            self._result_lbl.setText("✗ 已拒絕")
        self._result_lbl.show()
        self.answered.emit(allow)


class _UserBubble(QFrame):
    """Right-aligned user message bubble."""
    def __init__(self, text: str, image_count: int = 0, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(60, 2, 8, 2)
        row.setSpacing(0)
        row.addStretch(1)

        # Vertical column so image chip can appear above text
        col_w = QWidget()
        col_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        if image_count > 0:
            chip_text = f"🖼 {image_count} 張圖片" if image_count > 1 else "🖼 圖片"
            img_chip = QLabel(chip_text)
            img_chip.setStyleSheet(
                "QLabel { background: rgba(30,60,120,180); color: #a0c8ff; "
                "border: 1px solid rgba(80,130,220,100); border-radius: 8px; "
                "padding: 2px 8px; font-size: 11px; }"
            )
            img_chip.setAlignment(Qt.AlignmentFlag.AlignRight)
            col.addWidget(img_chip, 0, Qt.AlignmentFlag.AlignRight)

        self._text_label = QLabel()
        self._text_label.setTextFormat(Qt.TextFormat.RichText)
        self._text_label.setWordWrap(True)
        self._text_label.setText(html.escape(text).replace("\n", "<br>"))
        self._text_label.setStyleSheet(
            "QLabel {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(55,100,200,230),stop:1 rgba(38,78,168,225));"
            "color: #e8f4ff;"
            "border-radius: 14px;"
            "padding: 8px 12px;"
            "font-size: 13px;"
            "}"
        )
        self._text_label.setMaximumWidth(460)
        col.addWidget(self._text_label, 0, Qt.AlignmentFlag.AlignRight)
        col_w.setMaximumWidth(480)
        row.addWidget(col_w)

    def update_text(self, text: str) -> None:
        self._text_label.setText(html.escape(text).replace("\n", "<br>"))


class _AgentBubble(QFrame):
    """Left-aligned agent message bubble.

    Two-phase rendering:
    - Streaming: lightweight QTextBrowser updated in-place (fast, cheap).
    - Final:     SiriResponseBubble for full markdown / code-block / collapsible rendering.
    """

    _CARD_STYLE = (
        "#ABCard {"
        "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        "stop:0 rgba(28,34,62,218),stop:1 rgba(20,26,52,212));"
        "border: 1px solid rgba(60,110,230,42);"
        "border-radius: 14px;"
        "}"
    )
    _STREAM_BROWSER_STYLE = (
        "QTextBrowser {"
        "background: transparent; border: none;"
        "color: #dde8f8; font-size: 13px; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;"
        "}"
        "QTextBrowser::viewport { background: transparent; }"
    )
    # Regex to strip ALL special XML blocks that appear in _display_text during streaming
    _TAG_RE = re.compile(
        r'<(tool-execution|plan-suggestion|discussion)>.*?</\1>',
        re.DOTALL,
    )
    # Also strip incomplete opening tags that haven't closed yet
    _OPEN_TAG_RE = re.compile(
        r'<(tool-execution|plan-suggestion|discussion)>.*$',
        re.DOTALL,
    )

    # Tool icon map (subset)
    _TOOL_ICONS: dict[str, str] = {
        "bash": "⬛", "read": "📄", "write": "✏️", "edit": "✏️",
        "glob": "🔍", "grep": "🔍", "web": "🌐", "fetch": "🌐",
        "search": "🔍", "skill": "⚡", "agent": "🤖", "subagent": "🤖",
        "todo": "📋",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 2, 20, 2)
        outer.setSpacing(0)

        # Wrapper card
        self._card = QWidget()
        self._card.setObjectName("ABCard")
        self._card.setStyleSheet(self._CARD_STYLE)
        self._card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._card.setMinimumWidth(180)

        self._stack = QVBoxLayout(self._card)
        self._stack.setContentsMargins(12, 10, 12, 10)
        self._stack.setSpacing(0)

        # ── Phase 1: streaming browser ─────────────────────────────────
        self._stream_browser = AutoWrapTextBrowser()
        self._stream_browser.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._stream_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stream_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stream_browser.setFrameShape(QFrame.Shape.NoFrame)
        self._stream_browser.setOpenExternalLinks(True)
        self._stream_browser.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._stream_browser.setStyleSheet(self._STREAM_BROWSER_STYLE)
        self._stream_browser.setViewportMargins(0, 0, 0, 0)
        self._stream_browser.setContentsMargins(0, 0, 0, 0)
        self._stream_browser.document().setDocumentMargin(0)
        self._stream_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._stack.addWidget(self._stream_browser)

        # ── Phase 2: full SiriResponseBubble (hidden until finalized) ──
        self._full_bubble = SiriResponseBubble()
        self._full_bubble.setStyleSheet(
            "SiriResponseBubble { background: transparent; border: none; }"
            "QTextBrowser { background: transparent; border: none; }"
            "QTextBrowser::viewport { padding: 0px; margin: 0px; border: none; }"
        )
        self._full_bubble.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._full_bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._full_bubble.hide()
        self._stack.addWidget(self._full_bubble)

        # ── Tool log (compact, shown above text, hidden until events arrive) ──
        self._tool_lines: list[str] = []
        self._tool_log_browser = AutoWrapTextBrowser()
        self._tool_log_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tool_log_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tool_log_browser.setFrameShape(QFrame.Shape.NoFrame)
        self._tool_log_browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
            "QTextBrowser::viewport { background: transparent; }"
        )
        self._tool_log_browser.setFixedHeight(0)
        self._tool_log_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._stack.insertWidget(0, self._tool_log_browser)  # above stream/full

        self._finalized = False
        self._tool_log_dirty = False
        outer.addWidget(self._card, 1)

        # ── Glow animation (streaming indicator) ──────────────────────────
        self._glow = QGraphicsDropShadowEffect()
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(80, 140, 255, 0))
        self._glow.setOffset(0, 0)
        self._card.setGraphicsEffect(self._glow)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(700)
        self._pulse_timer.timeout.connect(self._pulse_card)
        self._pulse_phase = 0

        # Resize stream browser once laid out
        try:
            self._stream_browser.document().contentsChanged.connect(self._resize_stream)
        except Exception:
            pass

    # ── Tool events ────────────────────────────────────────────────────

    def _tool_icon(self, label: str) -> str:
        low = label.lower()
        for key, icon in self._TOOL_ICONS.items():
            if key in low:
                return icon
        return "🔧"

    def add_tool_event(self, line: str) -> None:
        """Append a tool event line and refresh the compact log."""
        if not line:
            return
        self._tool_lines.append(line)
        if len(self._tool_lines) > 20:
            self._tool_lines = self._tool_lines[-20:]
        self._tool_log_dirty = True
        QTimer.singleShot(0, self._refresh_tool_log)

    def _refresh_tool_log(self) -> None:
        if not self._tool_log_dirty:
            return
        self._tool_log_dirty = False
        esc = html.escape
        rows: list[str] = []
        in_flight: list[str] = []
        for line in self._tool_lines:
            if line.startswith("[>] "):
                label = line[4:]
                in_flight.append(label)
                icon = self._tool_icon(label)
                rows.append(
                    f'<div style="color:#6eaee8;font-size:10px;font-family:monospace;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'▶ {icon} {esc(label)}</div>'
                )
            elif line.startswith("[OK]"):
                if in_flight:
                    label = in_flight.pop(0)
                    icon = self._tool_icon(label)
                    # Replace the last ▶ with ✓ — just append a completion row
                    rows.append(
                        f'<div style="color:#4db87a;font-size:10px;font-family:monospace;">'
                        f'✓ {icon} {esc(label)}</div>'
                    )
                    # Remove the matching ▶ row (last added for this label)
                    for i in reversed(range(len(rows) - 1)):
                        if esc(label) in rows[i] and "▶" in rows[i]:
                            rows.pop(i)
                            break
            elif line.startswith("[ERR] "):
                err = line[6:]
                label = in_flight.pop(0) if in_flight else err
                rows.append(
                    f'<div style="color:#f06b6b;font-size:10px;font-family:monospace;">'
                    f'✗ {esc(label)}</div>'
                )
            elif line.startswith("[SKILL] "):
                label = line[8:]
                rows.append(
                    f'<div style="color:#c792ea;font-size:10px;">'
                    f'⚡ {esc(label)}</div>'
                )
        if not rows:
            self._tool_log_browser.setFixedHeight(0)
            return
        inner = "\n".join(rows[-10:])  # show last 10 completed events
        self._tool_log_browser.setHtml(
            f'<div style="margin:0;padding:0;background:transparent;">{inner}</div>'
        )
        line_count = min(len(rows), 10)
        self._tool_log_browser.setFixedHeight(min(14 * line_count + 6, 140))

    # ── Streaming phase ────────────────────────────────────────────────

    def set_stream_content(self, text: str) -> None:
        """Fast in-place update during streaming — does NOT re-create widgets."""
        if self._finalized:
            return
        # Strip complete <tool-execution> / <plan-suggestion> / <discussion> blocks
        clean = self._TAG_RE.sub('', text)
        # Also strip any incomplete block (opening tag with no closing tag yet)
        clean = self._OPEN_TAG_RE.sub('', clean).strip()
        self._stream_browser.setMarkdown(_prepare_markdown(clean) if clean else '')
        QTimer.singleShot(0, self._resize_stream)

    def _resize_stream(self) -> None:
        try:
            self._stream_browser.update_wrap_width(
                max(1, self._card.width() - 24)
            )
            doc_h = self._stream_browser.document().documentLayout().documentSize().height()
            h = max(32, int(doc_h) + 4)
            self._stream_browser.setMinimumHeight(h)
            self._stream_browser.setMaximumHeight(h)
        except Exception:
            pass

    # ── Final render phase ─────────────────────────────────────────────

    def set_content(self, text: str) -> None:
        """Full render — switch to SiriResponseBubble. Called once on completion."""
        self._finalized = True
        self._stream_browser.hide()
        self._full_bubble.set_content(text)
        self._full_bubble.show()
        QTimer.singleShot(80, self._resize_full)

    def _resize_full(self) -> None:
        try:
            QApplication.processEvents()
            h = self._full_bubble.content_height()
            target = max(54, h + 28)
            self._full_bubble.setMinimumHeight(target)
            self._full_bubble.setMaximumHeight(target)
        except Exception:
            pass

    def _pulse_card(self) -> None:
        self._pulse_phase = 1 - self._pulse_phase
        try:
            if self._pulse_phase:
                self._glow.setBlurRadius(16)
                self._glow.setColor(QColor(80, 140, 255, 130))
            else:
                self._glow.setBlurRadius(6)
                self._glow.setColor(QColor(80, 140, 255, 55))
        except Exception:
            pass

    def start_animation(self) -> None:
        self._pulse_phase = 0
        self._pulse_timer.start()
        self._full_bubble.start_animation()

    def stop_animation(self) -> None:
        self._pulse_timer.stop()
        try:
            self._glow.setBlurRadius(0)
            self._glow.setColor(QColor(80, 140, 255, 0))
        except Exception:
            pass
        self._full_bubble.stop_animation()


class _MemoryViewerDialog(QDialog):
    """Simple read-only viewer for a memory .md file."""

    def __init__(self, fname: str, label: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"記憶檔案 — {label}")
        self.resize(720, 380)
        self.setStyleSheet(
            "QDialog { background: rgb(18,20,30); }"
            "QTextBrowser { background: rgb(22,24,36); border: 1px solid rgba(255,255,255,18); "
            "border-radius: 8px; color: #d0dff0; font-size: 12px; padding: 6px; }"
            "QTextBrowser::viewport { background: transparent; }"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        hdr = QLabel(f"<b style='color:#90b0e0'>{html.escape(label)}</b>"
                     f"<span style='color:#506070;font-size:10px;'> ({html.escape(fname)})</span>")
        hdr.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(hdr)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        if content:
            try:
                browser.setMarkdown(content)
            except Exception:
                browser.setPlainText(content)
        else:
            browser.setPlaceholderText("（此檔案為空）")
        v.addWidget(browser, 1)

        close_btn = QPushButton("關閉")
        close_btn.setFixedHeight(28)
        close_btn.setStyleSheet(
            "QPushButton { background: rgba(50,65,100,200); color: #90b0e0; "
            "border: 1px solid rgba(90,130,200,60); border-radius: 8px; font-size: 11px; padding: 0 16px; }"
            "QPushButton:hover { background: rgba(65,85,130,230); }"
        )
        close_btn.clicked.connect(self.accept)
        v.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)


class ChatWindow(QMainWindow):
    """Chat-style interface — full conversation history, same features as circle mode."""

    switch_to_circle = Signal()   # emitted when user clicks "切換圓圈"
    typing = Signal()             # API compat with MainWindow
    collapse_state_changed = Signal(bool)  # API compat (always emits False)

    # Thread-safe dialog signals (same pattern as MainWindow)
    confirm_requested = Signal(str, str, object)
    question_requested = Signal(str, list, bool, object)  # question, options, multi, result_container

    _CHIP_STYLE = (
        "QLabel { background: rgba(45,55,80,200); color: #a8d4ff; "
        "border: 1px solid rgba(90,140,220,100); border-radius: 8px; "
        "padding: 2px 8px; font-size: 11px; }"
    )
    _CHIP_CLOSE_STYLE = (
        "QPushButton { background: transparent; color: rgba(160,170,200,160); "
        "border: none; font-size: 9px; padding: 0; } "
        "QPushButton:hover { color: #ff6b6b; }"
    )

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("AI Assistant — Chat")
        self.resize(680, 860)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("QMainWindow { background: rgb(12,14,24); }")

        # ── Internal state ─────────────────���──────────────────────────────
        self._bypass_mode: bool = False
        self._bypass_callback = None
        self._stop_callback = None
        self._voice_callback = None
        self._input_callback = None
        self._is_running: bool = False
        self._attached_file_path: str = ""
        self._attached_images: list[bytes] = []
        self._voice_active: bool = False
        self.config_webview_window = None

        # Live exchange tracking
        self._live_user_bubble: _UserBubble | None = None
        self._live_agent_bubble: _AgentBubble | None = None
        self._live_user_text: str = ""
        self._live_agent_text: str = ""

        # Image tracking: count of images attached to the next user message
        self._last_user_image_count: int = 0

        # Todo panel refs (built in _build_ui)
        self._todo_panel: QWidget | None = None
        self._todo_browser: QTextBrowser | None = None

        # Build UI
        self._build_ui()

        # Thread-safe dialogs
        self.confirm_requested.connect(self._handle_confirm_request)
        self.question_requested.connect(self._handle_question_request)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet("background: rgb(12,14,24);")
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Top bar
        top_bar = self._build_top_bar()
        vbox.addWidget(top_bar)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(60,100,255,50),stop:0.5 rgba(120,70,220,60),stop:1 rgba(30,150,200,40));"
        )
        vbox.addWidget(sep)

        # Chat scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: rgb(12,14,24); border: none; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(80,110,200,80); border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        self._chat_container = QWidget()
        self._chat_container.setStyleSheet("background: transparent;")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(12, 16, 12, 16)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch(1)   # keeps messages pushed to top
        self._scroll.setWidget(self._chat_container)

        # Body row: chat area (left) + todo sidebar (right, hidden by default)
        body_row = QWidget()
        body_row.setStyleSheet("background: transparent;")
        body_h = QHBoxLayout(body_row)
        body_h.setContentsMargins(0, 0, 0, 0)
        body_h.setSpacing(0)
        body_h.addWidget(self._scroll, 1)
        self._todo_panel = self._build_todo_panel()
        body_h.addWidget(self._todo_panel)
        vbox.addWidget(body_row, 1)

        # Input area
        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: rgba(255,255,255,12);")
        vbox.addWidget(sep2)
        self._build_input_area(vbox)

    def _build_todo_panel(self) -> QWidget:
        """Build the right-side sidebar: top = todo, bottom = memory file list."""
        _PANEL_STYLE = (
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(16,18,40,245),stop:1 rgba(14,16,36,245));"
            "border-left: 1px solid rgba(80,100,200,30);"
        )
        _BROWSER_STYLE = (
            "QTextBrowser { background: transparent; border: none; "
            "color: #b8cce4; font-size: 11px; }"
            "QTextBrowser::viewport { background: transparent; padding: 0; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(80,110,200,80); border-radius: 2px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        _HDR_STYLE = (
            "QLabel { font-size: 11px; font-weight: bold; "
            "border: none; background: transparent; padding: 2px 0; }"
        )
        _SEP_STYLE = "background: rgba(80,100,200,25);"

        panel = QWidget()
        panel.setFixedWidth(220)
        panel.setStyleSheet(_PANEL_STYLE)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            "QSplitter::handle { background: rgba(255,255,255,20); }"
        )
        outer.addWidget(splitter)

        # ── Top pane: Todo ────────────────────────────────────────────────
        top = QWidget()
        top.setStyleSheet("background: transparent;")
        top_v = QVBoxLayout(top)
        top_v.setContentsMargins(8, 8, 8, 4)
        top_v.setSpacing(4)

        todo_hdr = QLabel("📋 待辦事項")
        todo_hdr.setStyleSheet(_HDR_STYLE + "color: #38c8d8;")
        top_v.addWidget(todo_hdr)

        sep1 = QWidget(); sep1.setFixedHeight(1); sep1.setStyleSheet(_SEP_STYLE)
        top_v.addWidget(sep1)

        self._todo_browser = QTextBrowser()
        self._todo_browser.setStyleSheet(_BROWSER_STYLE)
        self._todo_browser.setOpenExternalLinks(False)
        self._todo_browser.setReadOnly(True)
        self._todo_browser.setPlaceholderText("暫無待辦事項")
        top_v.addWidget(self._todo_browser, 1)

        splitter.addWidget(top)

        # ── Bottom pane: Memory files ─────────────────────────────────────
        bot = QWidget()
        bot.setStyleSheet("background: transparent;")
        bot_v = QVBoxLayout(bot)
        bot_v.setContentsMargins(8, 4, 8, 8)
        bot_v.setSpacing(4)

        mem_hdr = QLabel("🧠 記憶檔案")
        mem_hdr.setStyleSheet(_HDR_STYLE + "color: #b078f0;")
        bot_v.addWidget(mem_hdr)

        sep2 = QWidget(); sep2.setFixedHeight(1); sep2.setStyleSheet(_SEP_STYLE)
        bot_v.addWidget(sep2)

        self._mem_list = QListWidget()
        self._mem_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #b0c8e8; font-size: 11px; }"
            "QListWidget::item { padding: 4px 2px; border-radius: 4px; }"
            "QListWidget::item:hover { background: rgba(80,110,180,60); }"
            "QListWidget::item:selected { background: rgba(60,90,160,100); }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(100,120,180,90); border-radius: 2px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        self._mem_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._mem_list.itemDoubleClicked.connect(self._open_memory_file)
        self._mem_list.itemClicked.connect(self._open_memory_file)
        self._populate_memory_list()
        bot_v.addWidget(self._mem_list, 1)

        splitter.addWidget(bot)
        splitter.setSizes([240, 160])  # default: todo taller

        return panel

    def _populate_memory_list(self) -> None:
        """Fill the memory file list widget."""
        try:
            from internal.memory import MEMORY_FILES, _FILE_LABELS
            self._mem_list.clear()
            for fname in MEMORY_FILES:
                label = _FILE_LABELS.get(fname, fname)
                item = QListWidgetItem(f"  {fname}")
                item.setToolTip(label)
                item.setData(Qt.ItemDataRole.UserRole, fname)
                self._mem_list.addItem(item)
        except Exception as exc:
            logger.warning(f"Memory list populate failed: {exc}")

    def _open_memory_file(self, item: QListWidgetItem) -> None:
        """Open a memory file in a viewer dialog."""
        try:
            from internal.memory import MemoryManager, _FILE_LABELS
            fname = item.data(Qt.ItemDataRole.UserRole) or item.text().strip()
            mm = MemoryManager()
            content = mm.read_file(fname)
            label = _FILE_LABELS.get(fname, fname)
            dlg = _MemoryViewerDialog(fname, label, content, parent=self)
            dlg.exec()
            self._mem_list.clearSelection()
        except Exception as exc:
            logger.warning(f"Open memory file failed: {exc}")

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(18,22,50,255),stop:0.5 rgba(22,18,44,255),stop:1 rgba(16,20,42,255));"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 10, 0)
        h.setSpacing(8)

        # Glowing dot indicator
        dot = QLabel("●")
        dot.setStyleSheet("color: #38c8e0; font-size: 10px;")
        h.addWidget(dot)

        title = QLabel("AI Assistant")
        title.setStyleSheet(
            "color: #c8deff; font-size: 14px; font-weight: bold; letter-spacing: 0.5px;"
        )
        h.addWidget(title)
        h.addStretch(1)

        # Compact indicator
        self._compact_label = QLabel("✂ 壓縮記憶中…")
        self._compact_label.setFixedHeight(22)
        self._compact_label.setStyleSheet(
            "QLabel { background: rgba(90,60,160,210); color: #ddc8ff; "
            "border: 1px solid rgba(180,140,255,120); border-radius: 11px; "
            "font-size: 10px; padding: 0 10px; }"
        )
        self._compact_label.hide()
        self._compact_pulse_timer = QTimer(self)
        self._compact_pulse_timer.setInterval(500)
        self._compact_pulse_timer.timeout.connect(self._pulse_compact_label)
        self._compact_pulse_phase = 0
        h.addWidget(self._compact_label)

        switch_btn = QPushButton("⭕ 切換圓圈")
        switch_btn.setFixedHeight(26)
        switch_btn.setStyleSheet(
            "QPushButton { background: rgba(36,48,90,210); color: #88c0f0; "
            "border: 1px solid rgba(70,110,220,80); border-radius: 8px; "
            "font-size: 11px; padding: 0 12px; }"
            "QPushButton:hover { background: rgba(50,68,120,235); color: #b8d8ff; "
            "border: 1px solid rgba(90,140,255,120); }"
        )
        switch_btn.clicked.connect(self.switch_to_circle.emit)
        h.addWidget(switch_btn)
        return bar

    def _build_input_area(self, parent_layout: QVBoxLayout) -> None:
        wrapper = QWidget()
        wrapper.setStyleSheet("background: rgb(14,16,30);")
        wrapper_vbox = QVBoxLayout(wrapper)
        wrapper_vbox.setContentsMargins(10, 8, 10, 10)
        wrapper_vbox.setSpacing(0)

        # Unified card
        card = QWidget()
        card.setObjectName("ChatInputCard")
        card.setStyleSheet(
            "#ChatInputCard {"
            "background: rgba(22,26,52,235);"
            "border: 1px solid rgba(70,110,220,65);"
            "border-radius: 18px;"
            "}"
        )
        card_vbox = QVBoxLayout(card)
        card_vbox.setContentsMargins(8, 6, 8, 6)
        card_vbox.setSpacing(4)

        # Chip row
        self._attach_row = QWidget()
        self._attach_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._attach_chips_layout = QHBoxLayout(self._attach_row)
        self._attach_chips_layout.setContentsMargins(2, 0, 2, 0)
        self._attach_chips_layout.setSpacing(5)
        self._attach_chips_layout.addStretch(1)
        self._attach_row.setFixedHeight(26)
        self._attach_row.hide()
        card_vbox.addWidget(self._attach_row)

        # Input row
        input_row_w = QWidget()
        input_row_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        input_row = QHBoxLayout(input_row_w)
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(4)

        self._voice_btn_idle_style = (
            "QPushButton { background: transparent; color: rgba(200,200,220,190); "
            "border: none; font-size: 14px; border-radius: 14px; }"
            "QPushButton:hover { background: rgba(255,255,255,12); }"
        )
        self._voice_btn_cancel_style = (
            "QPushButton { background: rgba(180,40,40,200); color: #fff; "
            "border: none; font-size: 13px; border-radius: 14px; }"
            "QPushButton:hover { background: rgba(210,55,55,230); }"
        )

        self.voice_button = QPushButton("🎤")
        self.voice_button.setFixedSize(28, 28)
        self.voice_button.setStyleSheet(self._voice_btn_idle_style)
        self.voice_button.clicked.connect(self.on_voice_requested)

        self.input_field = CommandLineEdit()
        self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
        self.input_field.setStyleSheet(
            "QLineEdit { background: transparent; color: #e8eaf0; "
            "border: none; padding: 2px 4px; font-size: 12px; }"
        )
        self.input_field.returnPressed.connect(self.on_input_submitted)
        try:
            self.input_field.textEdited.connect(self._handle_user_typing)
        except Exception:
            self.input_field.textChanged.connect(self._handle_user_typing)

        self._waveform = WaveformWidget()
        self._waveform.hide()

        self._send_btn_send_style = (
            "QPushButton { background: #2FBF71; color: #fff; border: none; "
            "border-radius: 12px; font-weight: bold; font-size: 12px; }"
            "QPushButton:hover { background: #28A862; }"
        )
        self._send_btn_stop_style = (
            "QPushButton { background: rgba(210,55,55,220); color: #fff; border: none; "
            "border-radius: 12px; font-size: 11px; padding: 0 0 1px 0; }"
            "QPushButton:hover { background: rgba(230,70,70,240); }"
        )

        self.send_button = QPushButton("發送")
        self.send_button.setFixedSize(52, 28)
        self.send_button.setStyleSheet(self._send_btn_send_style)
        self.send_button.clicked.connect(self.on_input_submitted)

        input_row.addWidget(self.voice_button)
        input_row.addWidget(self.input_field, 1)
        input_row.addWidget(self._waveform, 1)
        input_row.addWidget(self.send_button)
        card_vbox.addWidget(input_row_w)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("QWidget { background: rgba(255,255,255,18); border: none; }")
        card_vbox.addWidget(sep)

        # Toolbar row
        _tbtn = (
            "QPushButton { background: transparent; color: rgba(150,165,185,160); "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { color: rgba(210,225,255,220); background: rgba(255,255,255,8); }"
        )
        _tlbl = "QLabel { color: rgba(140,158,180,150); font-size: 10px; background: transparent; }"

        toolbar_row = QWidget()
        toolbar_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        toolbar_layout = QHBoxLayout(toolbar_row)
        toolbar_layout.setContentsMargins(2, 0, 2, 0)
        toolbar_layout.setSpacing(2)

        attach_btn = QPushButton("＋")
        attach_btn.setToolTip("附加檔案")
        attach_btn.setFixedSize(22, 20)
        attach_btn.setStyleSheet(_tbtn)
        attach_btn.clicked.connect(self._on_attach_file)
        toolbar_layout.addWidget(attach_btn)

        slash_btn = QPushButton("／")
        slash_btn.setToolTip("插入 /指令")
        slash_btn.setFixedSize(22, 20)
        slash_btn.setStyleSheet(_tbtn)
        slash_btn.clicked.connect(self._on_slash_shortcut)
        toolbar_layout.addWidget(slash_btn)

        self._total_tok_label = QLabel("Σ —")
        self._total_tok_label.setStyleSheet(_tlbl)
        self._total_tok_label.setToolTip("本次對話累計消耗 token 數")
        toolbar_layout.addWidget(self._total_tok_label)

        self._ctx_label = QLabel("ctx —")
        self._ctx_label.setStyleSheet(_tlbl)
        self._ctx_label.setToolTip("目前 context 窗口用量 / 最大值")
        toolbar_layout.addWidget(self._ctx_label)

        toolbar_layout.addStretch(1)

        self._bypass_btn = QPushButton("🔒")
        self._bypass_btn.setToolTip("全開模式：自動允許所有工具執行（再按恢復）")
        self._bypass_btn.setFixedSize(22, 20)
        self._bypass_btn.setCheckable(True)
        self._bypass_btn.setStyleSheet(_tbtn)
        self._bypass_btn.clicked.connect(self._on_bypass_toggled)
        toolbar_layout.addWidget(self._bypass_btn)

        card_vbox.addWidget(toolbar_row)
        wrapper_vbox.addWidget(card)
        parent_layout.addWidget(wrapper)

    # ── Public API (same interface as MainWindow) ─────────────────────────

    def set_input_callback(self, callback) -> None:
        self._input_callback = callback

    def set_stop_callback(self, callback) -> None:
        self._stop_callback = callback

    def set_bypass_callback(self, callback) -> None:
        self._bypass_callback = callback

    def set_voice_callback(self, cb) -> None:
        self._voice_callback = cb

    def show_input_container(self) -> None:
        pass  # input is always visible in chat mode

    def is_bypass_mode(self) -> bool:
        return self._bypass_mode

    def collapse_to_edge(self) -> None:
        pass  # no-op for chat window

    def expand_from_edge(self) -> None:
        pass  # no-op for chat window

    # ── update_speech_bubble: maps circle-mode text to chat bubbles ───────

    def update_speech_bubble(self, text: str) -> None:
        """Route circle-mode text updates to chat bubbles.

        "You: xxx"        → create/update user bubble (user echo line)
        "You: xxx\\n\\nyyy" → user bubble + status hint
        anything else     → update/create live agent bubble
        """
        if not isinstance(text, str):
            return

        if text.startswith("You: "):
            # Extract user message part (may have "\n\nstatus" appended)
            body = text[5:]
            if "\n\n" in body:
                user_msg = body[: body.index("\n\n")]
            else:
                user_msg = body
            if user_msg and user_msg != self._live_user_text:
                self._live_user_text = user_msg
                self._ensure_live_user_bubble(user_msg)
        else:
            # Agent response content — use fast streaming path
            if text and text != self._live_agent_text:
                self._live_agent_text = text
                self._ensure_live_agent_bubble()
                if self._live_agent_bubble:
                    self._live_agent_bubble.set_stream_content(text)
                    QTimer.singleShot(0, self._scroll_to_bottom)

    def _ensure_live_user_bubble(self, user_msg: str) -> None:
        """Create or update the live user bubble at the bottom of the chat."""
        if self._live_user_bubble is None:
            img_count = self._last_user_image_count
            self._last_user_image_count = 0
            self._live_user_bubble = _UserBubble(user_msg, image_count=img_count)
            # Insert before the last stretch item
            count = self._chat_layout.count()
            self._chat_layout.insertWidget(count - 1, self._live_user_bubble)
            self._scroll_to_bottom()
        else:
            self._live_user_bubble.update_text(user_msg)

    def _ensure_live_agent_bubble(self) -> None:
        """Create the live agent bubble if it doesn't exist yet."""
        if self._live_agent_bubble is None:
            self._live_agent_bubble = _AgentBubble()
            count = self._chat_layout.count()
            self._chat_layout.insertWidget(count - 1, self._live_agent_bubble)
            QTimer.singleShot(0, self._scroll_to_bottom)

    def start_agent_animation(self) -> None:
        self._ensure_live_agent_bubble()
        if self._live_agent_bubble:
            self._live_agent_bubble.start_animation()

    def stop_agent_animation(self) -> None:
        if self._live_agent_bubble:
            self._live_agent_bubble.stop_animation()

    def set_running(self, running: bool) -> None:
        self._is_running = running
        if running:
            self.send_button.setText("")
            self.send_button.setIcon(_make_stop_icon(20))
            self.send_button.setIconSize(QSize(20, 20))
            self.send_button.setStyleSheet(self._send_btn_stop_style)
            try:
                self.send_button.clicked.disconnect()
            except Exception:
                pass
            self.send_button.clicked.connect(self._on_stop_requested)
        else:
            self.send_button.setIcon(QIcon())
            self.send_button.setText("發送")
            self.send_button.setStyleSheet(self._send_btn_send_style)
            try:
                self.send_button.clicked.disconnect()
            except Exception:
                pass
            self.send_button.clicked.connect(self.on_input_submitted)
            # Finalize: stop glow, do full SiriResponseBubble render, then detach refs
            if self._live_agent_bubble is not None:
                self._live_agent_bubble.stop_animation()
                if self._live_agent_text:
                    self._live_agent_bubble.set_content(self._live_agent_text)
            self._live_user_bubble = None
            self._live_agent_bubble = None
            self._live_user_text = ""
            self._live_agent_text = ""

    def set_compact_indicator(self, active: bool) -> None:
        if active:
            self._compact_label.show()
            self._compact_pulse_phase = 0
            self._compact_pulse_timer.start()
        else:
            self._compact_pulse_timer.stop()
            self._compact_label.hide()

    def _pulse_compact_label(self) -> None:
        self._compact_pulse_phase = 1 - self._compact_pulse_phase
        if self._compact_pulse_phase:
            self._compact_label.setStyleSheet(
                "QLabel { background: rgba(110,75,190,230); color: #eedeff; "
                "border: 1px solid rgba(200,160,255,160); border-radius: 11px; "
                "font-size: 10px; padding: 0 10px; }"
            )
        else:
            self._compact_label.setStyleSheet(
                "QLabel { background: rgba(70,45,130,180); color: #c8aaee; "
                "border: 1px solid rgba(160,120,220,90); border-radius: 11px; "
                "font-size: 10px; padding: 0 10px; }"
            )

    def update_context_meter(self, used_tokens: int, max_tokens: int, total_tokens: int = 0) -> None:
        def _fmt(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}k"
            return str(n)

        if max_tokens > 0:
            pct = min(100, round(used_tokens * 100 / max_tokens))
            ctx_color = "#f06b6b" if pct >= 80 else "#f0c060" if pct >= 50 else "rgba(160,180,200,160)"
            self._ctx_label.setText(f"ctx {_fmt(used_tokens)}/{_fmt(max_tokens)} ({pct}%)")
            self._ctx_label.setStyleSheet(f"QLabel {{ color: {ctx_color}; font-size: 10px; }}")
        if total_tokens > 0:
            self._total_tok_label.setText(f"Σ {_fmt(total_tokens)}")
        else:
            self._total_tok_label.setText("Σ —")

    def update_todo_drawer(self, text: str) -> None:
        if self._todo_browser is None:
            return
        if not text:
            self._todo_browser.setPlaceholderText("暫無待辦事項")
            self._todo_browser.clear()
            return
        try:
            self._todo_browser.setMarkdown(text)
        except Exception:
            self._todo_browser.setPlainText(text)

    def voice_result_ready(self, text: str | None) -> None:
        if not self._voice_active:
            return
        self._exit_voice_mode()
        if text:
            existing = self.input_field.text().strip()
            sep = " " if existing else ""
            self.input_field.setText(existing + sep + text)
            self.input_field.setFocus()
            self.input_field.setCursorPosition(len(self.input_field.text()))

    def get_attached_file_path(self) -> str:
        path = self._attached_file_path
        if path:
            self._attached_file_path = ""
            self._clear_attachment()
        return path

    def pop_attached_images_as_tempfiles(self) -> list[str]:
        if not self._attached_images:
            return []
        # Track count so user bubble can show an image chip
        self._last_user_image_count = len(self._attached_images)
        import tempfile, os
        paths = []
        for data in self._attached_images:
            fd, path = tempfile.mkstemp(suffix=".png", prefix="agent_clip_")
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            paths.append(path)
        self._attached_images = []
        self._clear_attachment()
        return paths

    def open_config_webview(self) -> None:
        try:
            if not HAS_WEBENGINE:
                return
            from internal.services import config_webui
            url = config_webui.ensure_webui_running()
            if self.config_webview_window is not None:
                try:
                    self.config_webview_window.show()
                    self.config_webview_window.activateWindow()
                    self.config_webview_window.raise_()
                    return
                except RuntimeError:
                    self.config_webview_window = None
            self.config_webview_window = ConfigWebViewWindow(url, parent=None)
            self.config_webview_window.show()
        except Exception as exc:
            logger.error(f"ChatWindow: open_config_webview failed: {exc}")

    # ── Chat history ──────────────────────────────────────────────────────

    def load_history(self, history: list[tuple[str, str]]) -> None:
        """Populate chat from a list of (user_input, agent_output) pairs.

        Clears existing completed history widgets first, then re-renders.
        Live widgets (if any) are preserved.
        """
        # Remove all non-stretch widgets that are NOT the current live bubbles
        live_set = {
            id(self._live_user_bubble),
            id(self._live_agent_bubble),
        }
        for i in reversed(range(self._chat_layout.count())):
            item = self._chat_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None and id(w) not in live_set:
                self._chat_layout.removeWidget(w)
                w.deleteLater()

        # Re-add history pairs (insert before live bubbles / stretch)
        insert_pos = 0
        for user_text, agent_text in history:
            ub = _UserBubble(user_text)
            ab = _AgentBubble()
            if agent_text:
                ab.set_content(agent_text)
            self._chat_layout.insertWidget(insert_pos, ub)
            self._chat_layout.insertWidget(insert_pos + 1, ab)
            insert_pos += 2

        QTimer.singleShot(100, self._scroll_to_bottom)

    def sync_live_state(self, user_text: str, agent_text: str, is_running: bool) -> None:
        """Sync the live (current) exchange state when switching from circle mode.

        Call this after load_history() so the current in-progress turn is shown.
        """
        if user_text:
            self._live_user_text = user_text
            self._ensure_live_user_bubble(user_text)
        if agent_text:
            self._live_agent_text = agent_text
            self._ensure_live_agent_bubble()
            if self._live_agent_bubble:
                self._live_agent_bubble.set_content(agent_text)
        if is_running and self._live_agent_bubble:
            self._live_agent_bubble.start_animation()
        self.set_running(is_running)
        QTimer.singleShot(150, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Bypass mode ──────────────────────────────���────────────────────────

    def _on_bypass_toggled(self, checked: bool) -> None:
        self._bypass_mode = checked
        _on = (
            "QPushButton { background: rgba(220,120,0,180); color: #ffe0a0; "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { background: rgba(240,140,0,210); }"
        )
        _off = (
            "QPushButton { background: transparent; color: rgba(150,165,185,160); "
            "border: none; font-size: 12px; padding: 0 4px; border-radius: 4px; } "
            "QPushButton:hover { color: rgba(210,225,255,220); background: rgba(255,255,255,8); }"
        )
        if checked:
            self._bypass_btn.setText("🔓")
            self._bypass_btn.setToolTip("全開模式已開啟 — 自動允許所有工具（點擊關閉）")
            self._bypass_btn.setStyleSheet(_on)
        else:
            self._bypass_btn.setText("🔒")
            self._bypass_btn.setToolTip("全開模式：自動允許所有工具執行（再按恢復）")
            self._bypass_btn.setStyleSheet(_off)
        cb = getattr(self, "_bypass_callback", None)
        if cb:
            cb(checked)

    def sync_bypass_state(self, enabled: bool) -> None:
        """Called when switching from circle mode to sync bypass toggle state."""
        if enabled != self._bypass_mode:
            self._bypass_btn.setChecked(enabled)
            self._on_bypass_toggled(enabled)

    # ── Stop button ───────────────────────────────────────────────────────

    def _on_stop_requested(self) -> None:
        if self._stop_callback:
            self._stop_callback()

    # ── Voice mode ─────────────────────────────────��──────────────────────

    def on_voice_requested(self) -> None:
        if self._voice_active:
            self._cancel_voice()
        else:
            self._enter_voice_mode()

    def _enter_voice_mode(self) -> None:
        self._voice_active = True
        self.input_field.hide()
        self._waveform.show()
        self._waveform.start()
        self.voice_button.setText("✕")
        self.voice_button.setStyleSheet(self._voice_btn_cancel_style)
        try:
            self.send_button.clicked.disconnect()
        except Exception:
            pass
        self.send_button.clicked.connect(self._submit_voice_now)
        if self._voice_callback:
            self._voice_callback("__start__")

    def _exit_voice_mode(self) -> None:
        self._voice_active = False
        self._waveform.stop()
        self._waveform.hide()
        self.input_field.show()
        self.input_field.setFocus()
        self.voice_button.setText("🎤")
        self.voice_button.setStyleSheet(self._voice_btn_idle_style)
        try:
            self.send_button.clicked.disconnect()
        except Exception:
            pass
        if self._is_running:
            self.send_button.clicked.connect(self._on_stop_requested)
        else:
            self.send_button.clicked.connect(self.on_input_submitted)

    def _cancel_voice(self) -> None:
        self._exit_voice_mode()
        if self._voice_callback:
            self._voice_callback("__cancel__")

    def _submit_voice_now(self) -> None:
        self._exit_voice_mode()
        if self._voice_callback:
            self._voice_callback("__submit__")

    def set_voice_level(self, level: float) -> None:
        if self._voice_active:
            self._waveform.set_level(level)

    # ── Input submission ─────────────────────────────────���────────────────

    def on_input_submitted(self) -> None:
        text = self.input_field.text().strip()
        if text and self._input_callback:
            if isinstance(self.input_field, CommandLineEdit):
                self.input_field.add_to_history(text)
            self.input_field.clear()
            self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
            self._input_callback(text)

    def _handle_user_typing(self, *_args) -> None:
        try:
            self.typing.emit()
        except Exception:
            pass

    # ── File attachment ───────────────────────────────────────────────────

    def _on_attach_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "附加檔案", "", "All Files (*.*)")
        if path:
            self._attached_file_path = path
            name = path.split("/")[-1].split("\\")[-1]
            short = name if len(name) <= 20 else name[:17] + "…"

            def on_remove():
                self._attached_file_path = ""

            self._add_chip(f"📎 {short}", on_remove)

    def _on_slash_shortcut(self) -> None:
        if not self.input_field.text():
            self.input_field.setText("/")
            self.input_field.setFocus()
            self.input_field.setCursorPosition(1)

    def _add_chip(self, label: str, on_remove) -> None:
        chip = QLabel(label)
        chip.setStyleSheet(self._CHIP_STYLE)
        chip.setMaximumWidth(200)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(14, 14)
        close_btn.setStyleSheet(self._CHIP_CLOSE_STYLE)

        def _remove():
            on_remove()
            for w in (chip, close_btn):
                self._attach_chips_layout.removeWidget(w)
                w.deleteLater()
            self._refresh_chip_row()

        close_btn.clicked.connect(_remove)
        insert_pos = max(0, self._attach_chips_layout.count() - 1)
        self._attach_chips_layout.insertWidget(insert_pos, chip)
        self._attach_chips_layout.insertWidget(insert_pos + 1, close_btn)
        self._refresh_chip_row()

    def _refresh_chip_row(self) -> None:
        has_chips = self._attach_chips_layout.count() > 1
        if has_chips:
            self._attach_row.show()
        else:
            self._attach_row.hide()

    def _clear_attachment(self) -> None:
        self._attached_file_path = ""
        self._attached_images = []
        while self._attach_chips_layout.count() > 1:
            item = self._attach_chips_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._refresh_chip_row()

    def _show_attach_chip(self, label: str) -> None:
        idx = len(self._attached_images) - 1

        def on_remove():
            try:
                if 0 <= idx < len(self._attached_images):
                    self._attached_images.pop(idx)
            except Exception:
                pass

        self._add_chip(label, on_remove)

    # ── Clipboard paste (images) ───────────��─────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_V and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime and mime.hasImage():
                image = clipboard.image()
                if not image.isNull():
                    ba = QImage.toBytes(image.convertToFormat(QImage.Format.Format_RGBA8888))
                    # Save as PNG bytes
                    buf = io.BytesIO()
                    # Use PIL if available, else raw
                    if Image is not None:
                        pil_img = Image.frombytes("RGBA", (image.width(), image.height()), bytes(ba))
                        pil_img.save(buf, format="PNG")
                    else:
                        buf.write(bytes(ba))
                    self._attached_images.append(buf.getvalue())
                    self._show_attach_chip(f"🖼 剪貼板圖片 {len(self._attached_images)}")
                    event.accept()
                    return
        super().keyPressEvent(event)

    # ── Thread-safe confirm/question dialogs (same as MainWindow) ─────────

    @Slot(str, str, object)
    def _handle_confirm_request(self, message: str, default_choice: str, result_container: object) -> None:
        """In chat mode: insert an inline confirm bubble instead of a popup dialog."""
        try:
            bubble = _InlineConfirmBubble(message, default_choice)

            def _on_answered(allow: bool) -> None:
                result_container.result = allow
                result_container.done.set()
                logger.info(f"[ChatWindow inline] confirm answered: {allow}")
                # Reset live agent bubble so continuation appears BELOW this card
                self._live_agent_bubble = None
                self._live_agent_text = ""

            bubble.answered.connect(_on_answered)
            count = self._chat_layout.count()
            self._chat_layout.insertWidget(count - 1, bubble)
            self._scroll_to_bottom()
        except Exception as exc:
            logger.error(f"ChatWindow inline confirm error: {exc}", exc_info=True)
            result_container.done.set()

    def show_confirm_dialog(self, message: str, default_choice: str = '') -> bool:
        import threading

        class ResultContainer:
            def __init__(self):
                self.result = False
                self.done = threading.Event()

        rc = ResultContainer()
        self.confirm_requested.emit(message, default_choice, rc)
        rc.done.wait(timeout=300)
        return rc.result

    @Slot(str, list, bool, object)
    def _handle_question_request(self, question: str, options: list, multi: bool, result_container: object) -> None:
        """In chat mode: insert an inline question bubble instead of a popup dialog.

        We do NOT call result_container.done.set() here — the bubble's `answered`
        signal does that once the user clicks, keeping the background thread blocked
        until a choice is made.
        """
        try:
            bubble = _InlineQuestionBubble(question, list(options), multi=multi)

            def _on_answered(option: str) -> None:
                result_container.result = option
                result_container.done.set()
                logger.info(f"[ChatWindow inline] question answered: {option!r}")
                # Reset live agent bubble so continuation appears BELOW this card
                self._live_agent_bubble = None
                self._live_agent_text = ""

            bubble.answered.connect(_on_answered)

            # Insert before the trailing stretch item
            count = self._chat_layout.count()
            self._chat_layout.insertWidget(count - 1, bubble)
            self._scroll_to_bottom()
        except Exception as exc:
            logger.error(f"ChatWindow inline question error: {exc}", exc_info=True)
            result_container.done.set()  # unblock on error

    def show_question_dialog(self, question: str, options: list[str], multi: bool = False) -> str:
        import threading

        class ResultContainer:
            def __init__(self):
                self.result: str = ""
                self.done = threading.Event()

        rc = ResultContainer()
        self.question_requested.emit(question, options, multi, rc)
        rc.done.wait(timeout=300)
        return rc.result


class ConfigWebViewWindow(QMainWindow):
    """配置頁面 WebView 窗口"""

    def __init__(self, url: str, parent=None):
        # 不傳遞 parent 以避免繼承 always on top 屬性
        super().__init__(None)

        if not HAS_WEBENGINE:
            raise ImportError("PySide6-WebEngine is not installed. Please run: pip install PySide6-WebEngine")

        self.setWindowTitle("Agent 配置管理")
        self.setGeometry(100, 100, 1000, 700)

        # 明確設置為普通窗口（不使用 WindowStaysOnTopHint）
        self.setWindowFlags(Qt.WindowType.Window)

        # 創建 WebView
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl(url))

        # 直接將 WebView 設置為中央組件，不添加工具欄
        self.setCentralWidget(self.webview)


class ChoiceDialog(QDialog):
    """問題選單對話框 — 顯示 agent 的問題及可點擊的選項按鈕"""

    _STYLE = """
        QDialog {
            background-color: #1c1c1e;
            border-radius: 14px;
        }
        QLabel#icon {
            font-size: 22px;
        }
        QLabel#question {
            color: #f0f0f0;
            font-size: 14px;
            line-height: 1.5;
        }
        QFrame#sep {
            color: rgba(255, 255, 255, 25);
        }
        QPushButton#option {
            background-color: rgba(58, 58, 68, 220);
            color: #dde8f8;
            border: 1px solid rgba(255, 255, 255, 40);
            border-radius: 9px;
            padding: 10px 16px;
            font-size: 13px;
            text-align: left;
        }
        QPushButton#option:hover {
            background-color: rgba(0, 112, 240, 200);
            border-color: rgba(80, 160, 255, 180);
        }
        QPushButton#option:pressed {
            background-color: rgba(0, 80, 180, 230);
        }
    """

    _INPUT_STYLE = (
        "QLineEdit { "
        "background: rgba(50,52,65,220); color: #e8eaf0; "
        "border: 1px solid rgba(255,255,255,50); border-radius: 8px; "
        "padding: 8px 12px; font-size: 13px; "
        "}"
        "QLineEdit:focus { border-color: rgba(80,150,255,180); }"
        "QLineEdit:disabled { background: rgba(30,35,48,180); color: rgba(140,150,170,120); }"
    )
    _CB_STYLE = (
        "QCheckBox { color: #dde8f8; font-size: 13px; spacing: 8px; }"
        "QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;"
        "border: 1px solid rgba(255,255,255,40); background: rgba(58,58,68,220); }"
        "QCheckBox::indicator:checked { background: rgba(0,112,240,200);"
        "border-color: rgba(80,160,255,180); }"
        "QCheckBox:disabled { color: rgba(140,150,170,120); }"
    )

    def __init__(self, question: str, options: list[str], multi: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent 問題")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(self._STYLE)
        self._selected: str = ""
        self._multi = multi
        self._checkboxes: list[QCheckBox] = []
        self._custom_cb: QCheckBox | None = None
        self._text_input: QLineEdit | None = None
        self._option_btns: list[QPushButton] = []
        self._custom_input: QLineEdit | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(22, 22, 22, 22)

        # Header: icon + question text
        header = QHBoxLayout()
        header.setSpacing(10)
        icon_char = "☑️" if multi else "❓"
        icon = QLabel(icon_char)
        icon.setObjectName("icon")
        icon.setFixedWidth(30)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon)

        q_label = QLabel(question)
        q_label.setObjectName("question")
        q_label.setWordWrap(True)
        header.addWidget(q_label, 1)
        layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)
        layout.addSpacing(2)

        if not options:
            # Open-ended: free-text input + confirm
            self._text_input = QLineEdit()
            self._text_input.setPlaceholderText("請輸入回覆…")
            self._text_input.setStyleSheet(self._INPUT_STYLE)
            self._text_input.returnPressed.connect(self._submit_text)
            layout.addWidget(self._text_input)
            layout.addSpacing(4)
            confirm_btn = QPushButton("確認")
            confirm_btn.setObjectName("option")
            confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            confirm_btn.setStyleSheet(
                "QPushButton { background: rgba(0,100,220,200); color: #fff; "
                "border: none; border-radius: 9px; padding: 10px 16px; font-size: 13px; }"
                "QPushButton:hover { background: rgba(0,120,255,220); }"
            )
            confirm_btn.clicked.connect(self._submit_text)
            layout.addWidget(confirm_btn)
            QTimer.singleShot(0, self._text_input.setFocus)

        elif multi:
            # ── Multi-select: checkboxes ──────────────────────────────
            for opt in options:
                cb = QCheckBox(f"  {opt}")
                cb.setStyleSheet(self._CB_STYLE)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                layout.addWidget(cb)
                self._checkboxes.append(cb)

            # Custom input checkbox
            self._custom_cb = QCheckBox("  ✏️ 自訂輸入…")
            self._custom_cb.setStyleSheet(self._CB_STYLE)
            self._custom_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(self._custom_cb)

            self._custom_input = QLineEdit()
            self._custom_input.setPlaceholderText("請輸入自訂答案…")
            self._custom_input.setStyleSheet(self._INPUT_STYLE)
            self._custom_input.setEnabled(False)
            layout.addWidget(self._custom_input)
            self._custom_cb.toggled.connect(
                lambda checked: (
                    self._custom_input.setEnabled(checked),
                    self._custom_input.setFocus() if checked else None,
                )
            )

            layout.addSpacing(4)
            confirm_btn = QPushButton("✓ 確認選擇")
            confirm_btn.setObjectName("option")
            confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            confirm_btn.setStyleSheet(
                "QPushButton { background: rgba(0,100,220,200); color: #fff; "
                "border: none; border-radius: 9px; padding: 10px 16px; font-size: 13px; }"
                "QPushButton:hover { background: rgba(0,120,255,220); }"
            )
            confirm_btn.clicked.connect(self._submit_multi)
            layout.addWidget(confirm_btn)

        else:
            # ── Single-select: option buttons ─────────────────────────
            for opt in options:
                btn = QPushButton(f"  {opt}")
                btn.setObjectName("option")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _checked, o=opt: self._select(o))
                layout.addWidget(btn)
                self._option_btns.append(btn)

            # Custom input button (expands inline)
            custom_btn = QPushButton("  ✏️ 自訂輸入…")
            custom_btn.setObjectName("option")
            custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            custom_btn.clicked.connect(self._show_custom_input)
            layout.addWidget(custom_btn)
            self._option_btns.append(custom_btn)

            self._custom_input = QLineEdit()
            self._custom_input.setPlaceholderText("請輸入自訂答案…")
            self._custom_input.setStyleSheet(self._INPUT_STYLE)
            self._custom_input.returnPressed.connect(self._submit_custom)
            self._custom_input.hide()
            layout.addWidget(self._custom_input)

            confirm_custom_btn = QPushButton("✓ 確認")
            confirm_custom_btn.setObjectName("option")
            confirm_custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            confirm_custom_btn.setStyleSheet(
                "QPushButton { background: rgba(0,100,220,200); color: #fff; "
                "border: none; border-radius: 9px; padding: 10px 16px; font-size: 13px; }"
                "QPushButton:hover { background: rgba(0,120,255,220); }"
            )
            confirm_custom_btn.clicked.connect(self._submit_custom)
            confirm_custom_btn.hide()
            layout.addWidget(confirm_custom_btn)
            self._confirm_custom_btn = confirm_custom_btn

    # ── single-select helpers ──────────────────────────────────────────────

    def _show_custom_input(self) -> None:
        for btn in self._option_btns:
            btn.hide()
        if self._custom_input:
            self._custom_input.show()
            self._custom_input.setFocus()
        if hasattr(self, "_confirm_custom_btn"):
            self._confirm_custom_btn.show()

    def _submit_custom(self) -> None:
        text = (self._custom_input.text() or "").strip() if self._custom_input else ""
        if not text:
            return
        self._selected = text
        self.accept()

    def _select(self, option: str) -> None:
        self._selected = option
        self.accept()

    # ── multi-select helpers ───────────────────────────────────────────────

    def _submit_multi(self) -> None:
        selected = [cb.text().lstrip() for cb in self._checkboxes if cb.isChecked()]
        if self._custom_cb and self._custom_cb.isChecked() and self._custom_input:
            custom_text = self._custom_input.text().strip()
            if custom_text:
                selected.append(custom_text)
        if not selected:
            return
        self._selected = ", ".join(selected)
        self.accept()

    # ── open-ended helpers ─────────────────────────────────────────────────

    def _submit_text(self) -> None:
        text = self._text_input.text().strip() if self._text_input else ""
        self._selected = text
        self.accept()

    def get_result(self) -> str:
        """顯示對話框並返回使用者選擇的選項或輸入的文字（取消時返回空字串）"""
        self.exec()
        return self._selected


class ConfirmDialog(QDialog):
    """確認對話框，用於工具執行確認（與 ChoiceDialog 共用視覺語言）"""

    _STYLE = """
        QDialog {
            background-color: #1c1c1e;
            border-radius: 14px;
        }
        QLabel#icon { font-size: 22px; }
        QLabel#title {
            color: #f0f0f0;
            font-size: 15px;
            font-weight: bold;
        }
        QFrame#sep { color: rgba(255,255,255,25); }
        QTextBrowser#body {
            background-color: rgba(30,30,38,180);
            color: #b8b8bc;
            font-size: 12px;
            border: 1px solid rgba(255,255,255,18);
            border-radius: 6px;
            padding: 6px;
            selection-background-color: rgba(0,112,240,120);
        }
        QScrollBar:vertical {
            border: none; background: transparent; width: 4px; margin: 4px 0;
        }
        QScrollBar::handle:vertical {
            background: rgba(255,255,255,40); min-height: 20px; border-radius: 2px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QPushButton#allow {
            background-color: rgba(0, 112, 240, 200);
            color: #e8f0ff;
            border: 1px solid rgba(80, 160, 255, 180);
            border-radius: 9px;
            padding: 10px 16px;
            font-size: 13px;
            text-align: left;
        }
        QPushButton#allow:hover  { background-color: rgba(0, 130, 255, 220); }
        QPushButton#allow:pressed { background-color: rgba(0, 80, 200, 240); }
        QPushButton#deny {
            background-color: rgba(58, 58, 68, 200);
            color: #c0c0c4;
            border: 1px solid rgba(255,255,255,35);
            border-radius: 9px;
            padding: 10px 16px;
            font-size: 13px;
            text-align: left;
        }
        QPushButton#deny:hover  { background-color: rgba(80, 80, 92, 220); }
        QPushButton#deny:pressed { background-color: rgba(45, 45, 55, 240); }
    """

    _DANGER_KEYWORDS = {"delete", "remove", "rm ", "drop", "kill", "truncate", "format", "wipe"}

    def __init__(self, message: str, default_choice: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具執行確認")
        self.setModal(True)
        # Fixed width; height is bounded by the scroll area
        self.setFixedWidth(460)
        self.setStyleSheet(self._STYLE)

        msg_lower = message.lower()
        is_danger = any(kw in msg_lower for kw in self._DANGER_KEYWORDS)
        icon_char = "⚠️" if is_danger else "🔧"

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(22, 20, 22, 20)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(10)
        icon = QLabel(icon_char)
        icon.setObjectName("icon")
        icon.setFixedWidth(32)
        icon.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(icon)
        title = QLabel("工具執行請求")
        title.setObjectName("title")
        header.addWidget(title, 1)
        layout.addLayout(header)

        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Scrollable body — fixed height so long messages don't overflow
        body = QTextBrowser()
        body.setObjectName("body")
        body.setOpenLinks(False)
        body.setReadOnly(True)
        body.setFixedHeight(140)          # shows ~6-7 lines; scrolls if more
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body.setPlainText(message)
        layout.addWidget(body)

        layout.addSpacing(4)

        # Full-width option buttons
        allow_btn = QPushButton("  ✅ 允許執行  (Y)")
        allow_btn.setObjectName("allow")
        allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        allow_btn.clicked.connect(self.accept)
        layout.addWidget(allow_btn)

        deny_btn = QPushButton("  ❌ 拒絕  (N)")
        deny_btn.setObjectName("deny")
        deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        deny_btn.clicked.connect(self.reject)
        layout.addWidget(deny_btn)

        if default_choice.upper() == 'Y':
            allow_btn.setDefault(True)
            allow_btn.setFocus()
        else:
            deny_btn.setDefault(True)
            deny_btn.setFocus()

    def get_result(self) -> bool:
        """顯示對話框並返回結果"""
        return self.exec() == QDialog.DialogCode.Accepted


if __name__ == "__main__":
    app = QApplication(sys.argv)

    mainWindow = MainWindow()
    mainWindow.show()

    app.exec()
