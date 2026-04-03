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
    QEventLoop,
    QMetaObject,
    Property,
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
    QGuiApplication,
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
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


class AutoWrapTextBrowser(QTextBrowser):
    """QTextBrowser that keeps document width aligned to viewport width."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
                title = "Tool execution" if kind == "tool" else "Discussion"
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
        r"^\s*(?:[-*>]\s*)?(?:still\s+|currently\s+)?(?P<status>thinking|listening)(?:\s*(?:\.{3,}|\?\?)?\s*)$",
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
                title = "Tool execution" if kind == "tool" else "Discussion"
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
        self._last_y = None
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
        self._last_y = y

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

        if self._last_y is None:
            y = geo.bottom() - self._height
        else:
            y = self._last_y
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
            self._last_y = self.y()
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


class MainWindow(QMainWindow):
    # 信号：请求显示确认对话框
    confirm_requested = Signal(str, str, object)  # message, default_choice, result_container
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
        
        # 固定球的位置參數（球心在底部往上130px，縮小與輸入框的距離）
        self.BALL_CENTER_FROM_BOTTOM = 130
        # 固定輸入框的位置（距離底部40px，使輸入框上移，與球更接近）
        self.INPUT_FROM_BOTTOM = 40
        self.INPUT_HEIGHT = 45

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

        # 創建輸入區域
        self.input_container = QWidget(self)
        self.input_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.input_layout = QHBoxLayout(self.input_container)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(5)

        # 使用自定義的 CommandLineEdit 替代 QLineEdit
        self.input_field = CommandLineEdit()
        self.input_field.setPlaceholderText("輸入文字、指令或按🎤啟動語音...")
        self.input_field.setStyleSheet(
            "QLineEdit { "
            "background-color: rgba(50, 50, 50, 220); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 60); "
            "border-radius: 15px; "
            "padding: 8px 12px; "
            "}"
        )
        self.input_field.returnPressed.connect(self.on_input_submitted)
        # 當使用者正在輸入時，發出 typing 信號（用於重置閒置計時）
        try:
            self.input_field.textEdited.connect(self._handle_user_typing)
        except Exception:
            # fallback to textChanged if textEdited not available
            self.input_field.textChanged.connect(self._handle_user_typing)

        self.voice_button = QPushButton("🎤")
        self.voice_button.setFixedSize(35, 35)
        self.voice_button.setStyleSheet(
            "QPushButton { "
            "background-color: rgba(70, 70, 70, 180); "
            "color: white; "
            "border: 1px solid rgba(255, 255, 255, 40); "
            "border-radius: 17px; "
            "font-size: 16px; "
            "}"
            "QPushButton:hover { background-color: rgba(100, 100, 100, 220); }"
        )
        self.voice_button.clicked.connect(self.on_voice_requested)

        self.send_button = QPushButton("發送")
        self.send_button.setFixedSize(60, 35)
        self.send_button.setStyleSheet(
            "QPushButton { "
            "background-color: #2FBF71; "
            "color: #FFFFFF; "
            "border: none; "
            "border-radius: 15px; "
            "font-weight: bold; "
            "}"
            "QPushButton:hover { background-color: #28A862; }"
        )
        self.send_button.clicked.connect(self.on_input_submitted)
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


        self.input_layout.addWidget(self.voice_button)
        self.input_layout.addWidget(self.input_field)
        self.input_layout.addWidget(self.send_button)

        self.input_container.hide()  # 初始隱藏

        self.edge_handle = EdgeHandle(on_activate=self.expand_from_edge)
        self._input_visible_before_collapse = False
        self._collapsed = False


        self.config_webview_window = None  # WebView 窗口引用

        self._pending_geometry_refresh = False

        # 连接确认信号到槽
        self.confirm_requested.connect(self._handle_confirm_request)

        # 初始化窗口遮罩（點擊穿透）- 多次延遲更新確保完全渲染
        QTimer.singleShot(0, self._update_window_mask)
        QTimer.singleShot(100, self._update_window_mask)
        QTimer.singleShot(300, self._update_window_mask)

    def set_input_callback(self, callback):
        """設置輸入回調函數"""
        self.input_callback = callback
    
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
        """
        槽函数：在主线程中处理确认请求
        """
        try:
            logger.info(f"[主线程] Creating ConfirmDialog for: {message[:50]}...")
            dialog = ConfirmDialog(message, default_choice, parent=self)
            result_container.result = dialog.get_result()
            logger.info(f"[主线程] Dialog result: {result_container.result}")
        except Exception as e:
            logger.error(f"[主线程] Error in _handle_confirm_request: {e}", exc_info=True)
        finally:
            # 退出事件循环
            if hasattr(result_container, 'loop'):
                result_container.loop.quit()
    
    def show_confirm_dialog(self, message: str, default_choice: str = '') -> bool:
        """
        顯示確認對話框（線程安全）
        使用信号-槽机制和 QEventLoop 确保对话框在主线程中创建和显示
        """
        logger.info(f"[工作线程] show_confirm_dialog called: {message[:50]}...")
        
        # 使用简单的对象来存储结果和事件循环
        class ResultContainer:
            def __init__(self):
                self.result = False
                self.loop = None
        
        result_container = ResultContainer()
        
        # 创建事件循环用于等待
        result_container.loop = QEventLoop()
        
        # 发送信号（Qt 会自动调度到主线程）
        logger.info("[工作线程] Emitting confirm_requested signal...")
        self.confirm_requested.emit(message, default_choice, result_container)
        
        # 运行事件循环，直到槽函数调用 loop.quit()
        logger.info("[工作线程] Starting event loop...")
        result_container.loop.exec()
        
        logger.info(f"[工作线程] Dialog closed, returning: {result_container.result}")
        return result_container.result

    def _position_input_container(self) -> None:
        bubble_width = getattr(self, "_current_bubble_width", None)
        if bubble_width:
            input_width = min(bubble_width, self.FIXED_WIDTH - 40)
        else:
            input_width = min(self.FIXED_WIDTH - 40, 500)
        self.input_container.setGeometry(
            (self.FIXED_WIDTH - input_width) // 2,
            self.FIXED_HEIGHT - self.INPUT_HEIGHT - self.INPUT_FROM_BOTTOM,
            input_width,
            self.INPUT_HEIGHT,
        )
        self._position_collapse_button()

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
        self._update_window_mask()

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

    def on_voice_requested(self):
        """處理語音請求"""
        if self.input_callback:
            self.input_callback(None)  # None 表示使用語音輸入

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


class ConfirmDialog(QDialog):
    """確認對話框，用於工具執行確認"""
    
    def __init__(self, message: str, default_choice: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具執行確認")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # 設置樣式
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
                border-radius: 10px;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px;
            }
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #329DFF;
            }
            QPushButton:pressed {
                background-color: #0051D5;
            }
            QPushButton#cancelButton {
                background-color: #5a5a5a;
            }
            QPushButton#cancelButton:hover {
                background-color: #6a6a6a;
            }
        """)
        
        # 創建佈局
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 訊息標籤
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(message_label)
        
        # 按鈕區域
        button_box = QDialogButtonBox()
        
        yes_button = button_box.addButton("允許", QDialogButtonBox.ButtonRole.AcceptRole)
        no_button = button_box.addButton("拒絕", QDialogButtonBox.ButtonRole.RejectRole)
        no_button.setObjectName("cancelButton")
        
        # 根據默認選擇設置默認按鈕
        if default_choice.upper() == 'Y':
            yes_button.setDefault(True)
            yes_button.setFocus()
        elif default_choice.upper() == 'N':
            no_button.setDefault(True)
            no_button.setFocus()
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
        
        self.result_value = False
    
    def get_result(self) -> bool:
        """顯示對話框並返回結果"""
        result = self.exec()
        return result == QDialog.DialogCode.Accepted


if __name__ == "__main__":
    app = QApplication(sys.argv)

    mainWindow = MainWindow()
    mainWindow.show()

    app.exec()
