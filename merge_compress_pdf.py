import os
import sys
from dataclasses import dataclass
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QListWidget, QFileDialog, QMessageBox,
    QProgressBar, QCheckBox, QRadioButton, QButtonGroup, QTabWidget, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QScrollArea,
    QAbstractItemView, QSplitter, QListWidgetItem, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QImage, QPixmap
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import subprocess

# NEW: 添加用于文件转换的库
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pdf_file_utils import collect_relative_files, make_unique_path, resolve_ghostscript_command
from duplicate_detector import (
    DetectionReport,
    find_duplicate_images,
    find_duplicate_pdfs,
    render_preview_image,
)

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
TEXT_EXTENSIONS = (".txt", ".md")


@dataclass(frozen=True)
class FileEntry:
    path: str
    display_name: str
    source_root: str = ""
    kind: str = "unknown"

    @classmethod
    def from_path(cls, path, source_root=""):
        absolute_path = os.path.abspath(path)
        extension = os.path.splitext(absolute_path)[1].lower()
        if extension == ".pdf":
            kind = "pdf"
        elif extension in IMAGE_EXTENSIONS:
            kind = "image"
        elif extension in TEXT_EXTENSIONS:
            kind = "text"
        else:
            kind = "unknown"

        return cls(
            path=absolute_path,
            display_name=os.path.basename(absolute_path),
            source_root=os.path.abspath(source_root) if source_root else "",
            kind=kind,
        )

class MergeThread(QThread):
    status_update = Signal(str, str)  # message, color
    finished = Signal(str)

    def __init__(self, output_path, pdf_paths, compress_after_merge):
        super().__init__()
        self.output_path = output_path
        self.pdf_paths = [os.path.abspath(path) for path in pdf_paths]
        self.compress_after_merge = compress_after_merge

    def run(self):
        merger = PdfMerger()
        try:
            appended_count = 0
            for pdf_path in self.pdf_paths:
                pdf_name = os.path.basename(pdf_path)
                try:
                    with open(pdf_path, 'rb') as f:
                        reader = PdfReader(f)
                        if len(reader.pages) > 0:
                            merger.append(pdf_path)
                            appended_count += 1
                        else:
                            print(f"警告: {pdf_name} 没有页面，已跳过")
                except Exception as e:
                    print(f"错误: 无法读取 {pdf_path}: {str(e)}")

            if appended_count == 0:
                raise ValueError("没有可合并的有效 PDF 文件")

            with open(self.output_path, 'wb') as out_file:
                merger.write(out_file)

            if self.compress_after_merge:
                self.status_update.emit("合并完成，开始压缩...", "blue")
                compressed_path = make_unique_path(os.path.splitext(self.output_path)[0] + "_compressed.pdf")
                self.compress_pdf(self.output_path, compressed_path)
                self.output_path = compressed_path

            self.status_update.emit(f"处理完成: {self.output_path}", "green")
            self.finished.emit(f"PDF文件已成功处理到 {self.output_path}")

        except Exception as e:
            error_msg = f"处理过程中发生错误: {str(e)}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg)
        finally:
            merger.close()

    def compress_pdf(self, input_pdf, output_pdf):
        try:
            gs_command = [
                resolve_ghostscript_command(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={output_pdf}", input_pdf
            ]
            subprocess.run(gs_command, check=True, capture_output=True)
        except Exception as e:
            raise e

class CompressThread(QThread):
    status_update = Signal(str, str)  # message, color
    finished = Signal(str)

    def __init__(self, input_path, output_path, compression_level, target_size_mb):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.compression_level = compression_level
        self.target_size_mb = target_size_mb

    def run(self):
        try:
            gs_command = [
                resolve_ghostscript_command(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={self.compression_level}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={self.output_path}", self.input_path
            ]
            subprocess.run(gs_command, check=True, capture_output=True)

            output_size_mb = os.path.getsize(self.output_path) / (1024 * 1024)
            if self.target_size_mb > 0 and output_size_mb > self.target_size_mb:
                msg = f"文件压缩后大小 ({output_size_mb:.2f}MB) 仍大于目标大小 ({self.target_size_mb}MB)"
                self.status_update.emit(msg, "orange")
                self.finished.emit(msg + "。您可以尝试选择更低的压缩质量。")
            else:
                msg = f"压缩完成，文件大小为 {output_size_mb:.2f}MB"
                self.status_update.emit(msg, "green")
                self.finished.emit(f"PDF文件已成功压缩到 {self.output_path}\n压缩后大小: {output_size_mb:.2f}MB")

        except subprocess.CalledProcessError as e:
            error_msg = f"压缩过程中发生错误: Ghostscript 返回错误代码 {e.returncode}"
            if e.stderr:
                error_msg += f"\n错误信息: {e.stderr.decode()}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg)
        except Exception as e:
            error_msg = f"压缩过程中发生错误: {str(e)}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg)

# NEW: 新增转换线程
class ConversionThread(QThread):
    status_update = Signal(str, str)  # message, color
    finished = Signal(str, list)  # message, list of converted pdfs

    def __init__(self, folder, output_dir, file_list):
        super().__init__()
        self.folder = folder
        self.output_dir = output_dir
        self.file_list = file_list

    def run(self):
        converted_pdfs = []
        try:
            for file_name in self.file_list:
                input_path = file_name if os.path.isabs(file_name) else os.path.join(self.folder, file_name)
                output_pdf = make_unique_path(os.path.join(self.output_dir, os.path.splitext(os.path.basename(file_name))[0] + ".pdf"))
                
                if file_name.lower().endswith('.pdf'):
                    # 如果已经是PDF，直接复制
                    with open(input_path, 'rb') as src, open(output_pdf, 'wb') as dst:
                        dst.write(src.read())
                elif file_name.lower().endswith(('.jpg', '.png', '.bmp', '.gif')):
                    # 图像转换为PDF
                    self.image_to_pdf(input_path, output_pdf)
                elif file_name.lower().endswith(('.txt', '.md')):
                    # 文本转换为PDF
                    self.text_to_pdf(input_path, output_pdf)
                else:
                    self.status_update.emit(f"不支持的文件类型: {file_name}, 已跳过", "orange")
                    continue
                
                converted_pdfs.append(os.path.abspath(output_pdf))
                self.status_update.emit(f"转换完成: {file_name} -> {output_pdf}", "blue")

            msg = f"转换完成，共处理 {len(converted_pdfs)} 个文件"
            self.status_update.emit(msg, "green")
            self.finished.emit(msg, converted_pdfs)

        except Exception as e:
            error_msg = f"转换过程中发生错误: {str(e)}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg, [])

    def image_to_pdf(self, image_path, pdf_path):
        image = Image.open(image_path)
        image = image.convert('RGB')  # 确保兼容PDF
        image.save(pdf_path, "PDF", resolution=100.0)

    def text_to_pdf(self, text_path, pdf_path):
        c = canvas.Canvas(pdf_path, pagesize=letter)
        with open(text_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        y = 750
        for line in lines:
            c.drawString(10, y, line.strip())
            y -= 12
            if y < 50:
                c.showPage()
                y = 750
        c.save()

# NEW: 新增拆分线程
class SplitThread(QThread):
    status_update = Signal(str, str)  # message, color
    finished = Signal(str)

    def __init__(self, input_path, output_dir, split_mode, page_ranges=None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.split_mode = split_mode  # 'page_by_page' or 'ranges'
        self.page_ranges = page_ranges  # for ranges mode, e.g., '2-10,12,15-20'

    def run(self):
        try:
            with open(self.input_path, 'rb') as f:
                reader = PdfReader(f)
                total_pages = len(reader.pages)
                if total_pages == 0:
                    raise ValueError("PDF文件没有页面")

                base_name = os.path.splitext(os.path.basename(self.input_path))[0]

                if self.split_mode == 'page_by_page':
                    for page_num in range(1, total_pages + 1):
                        writer = PdfWriter()
                        writer.add_page(reader.pages[page_num - 1])
                        output_pdf = make_unique_path(os.path.join(self.output_dir, f"{base_name}_page{page_num}.pdf"))
                        with open(output_pdf, 'wb') as out_file:
                            writer.write(out_file)
                        self.status_update.emit(f"拆分页面 {page_num}/{total_pages}", "blue")
                elif self.split_mode == 'ranges':
                    if not self.page_ranges:
                        raise ValueError("未指定页码范围")
                    pages = self.parse_page_ranges(self.page_ranges, total_pages)
                    writer = PdfWriter()
                    for page_num in pages:
                        writer.add_page(reader.pages[page_num - 1])
                    output_pdf = make_unique_path(os.path.join(self.output_dir, f"{base_name}_split.pdf"))
                    with open(output_pdf, 'wb') as out_file:
                        writer.write(out_file)
                    self.status_update.emit(f"拆分指定范围: {self.page_ranges}", "blue")

            msg = "PDF拆分完成"
            self.status_update.emit(msg, "green")
            self.finished.emit(msg)

        except Exception as e:
            error_msg = f"拆分过程中发生错误: {str(e)}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg)

    def parse_page_ranges(self, ranges_str, total_pages):
        pages = set()
        for part in ranges_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                if start < 1 or end > total_pages or start > end:
                    raise ValueError(f"无效页码范围: {part}")
                pages.update(range(start, end + 1))
            else:
                page = int(part)
                if page < 1 or page > total_pages:
                    raise ValueError(f"无效页码: {part}")
                pages.add(page)
        return sorted(pages)


def pil_image_to_pixmap(image):
    image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    image_format = getattr(QImage, "Format_RGBA8888", QImage.Format.Format_RGBA8888)
    qimage = QImage(data, image.width, image.height, image.width * 4, image_format)
    return QPixmap.fromImage(qimage.copy())


def scaled_pixmap_for_label(pixmap, label, fallback_size=(420, 260)):
    keep_aspect = getattr(Qt, "KeepAspectRatio", Qt.AspectRatioMode.KeepAspectRatio)
    smooth = getattr(Qt, "SmoothTransformation", Qt.TransformationMode.SmoothTransformation)
    width = max(label.width(), fallback_size[0])
    height = max(label.height(), fallback_size[1])
    return pixmap.scaled(width, height, keep_aspect, smooth)


class FilePreviewPanel(QScrollArea):
    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.current_path = ""
        self.render_generation = 0
        self.last_render_width = 0
        self.setObjectName("previewScrollArea")
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.refresh_current_file)

        self.content = QWidget()
        self.content.setObjectName("previewContent")
        self.content.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(22, 20, 22, 24)
        self.content_layout.setSpacing(16)
        self.content_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setWidget(self.content)
        self.show_message(placeholder)

    def clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def show_message(self, message):
        self.render_generation += 1
        self.current_path = ""
        self.clear_content()
        label = QLabel(message)
        label.setObjectName("previewMessage")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumSize(420, 520)
        self.content_layout.addWidget(label)
        self.content.adjustSize()

    def show_file(self, path):
        if not path or not os.path.isfile(path):
            self.show_message("文件不存在，无法预览")
            return

        self.current_path = path
        extension = os.path.splitext(path)[1].lower()
        try:
            if extension == ".pdf":
                self.show_pdf(path)
            elif extension in IMAGE_EXTENSIONS:
                image = render_preview_image(path, max_size=self.preview_image_max_size())
                self.show_pixmap(pil_image_to_pixmap(image), path)
            elif extension in TEXT_EXTENSIONS:
                with open(path, "r", encoding="utf-8", errors="replace") as file:
                    text = file.read(5000)
                self.show_text(text or "空文本文件", path)
            else:
                self.show_message("此文件类型暂不支持预览")
        except Exception as exc:
            self.show_message(f"预览失败: {exc}")

    def show_pixmap(self, pixmap, tooltip=""):
        self.render_generation += 1
        self.clear_content()
        label = self.create_page_label(tooltip)
        label.setPixmap(pixmap)
        label.setFixedSize(max(pixmap.width() + 24, 360), max(pixmap.height() + 24, 420))
        self.content_layout.addWidget(label)
        self.content.adjustSize()

    def show_text(self, text, tooltip=""):
        self.render_generation += 1
        self.clear_content()
        label = QLabel(text)
        label.setObjectName("previewText")
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setWordWrap(True)
        label.setMinimumSize(720, 900)
        label.setToolTip(tooltip)
        self.content_layout.addWidget(label)
        self.content.adjustSize()

    def show_pdf(self, path):
        if fitz is None:
            raise RuntimeError("缺少 PyMuPDF，请先运行: python -m pip install PyMuPDF")

        self.render_generation += 1
        generation = self.render_generation
        self.clear_content()

        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError("加密 PDF，无法预览")
            page_count = document.page_count
            if page_count == 0:
                raise ValueError("空 PDF，无法预览")

        labels = []
        for page_number in range(1, page_count + 1):
            page_title = QLabel(f"第 {page_number} 页")
            page_title.setObjectName("previewPageTitle")
            page_title.setAlignment(Qt.AlignCenter)
            page_label = self.create_page_label(path)
            page_label.setText("正在渲染...")
            self.content_layout.addWidget(page_title)
            self.content_layout.addWidget(page_label)
            labels.append(page_label)

        self.content.adjustSize()
        QTimer.singleShot(0, lambda: self.render_pdf_page(path, labels, generation, 0))

    def render_pdf_page(self, path, labels, generation, index):
        if generation != self.render_generation or index >= len(labels):
            return

        label = labels[index]
        try:
            image = render_preview_image(path, index + 1, max_size=self.preview_image_max_size())
            pixmap = pil_image_to_pixmap(image)
            label.setText("")
            label.setPixmap(pixmap)
            label.setFixedSize(max(pixmap.width() + 24, 360), max(pixmap.height() + 24, 420))
            self.content.adjustSize()
        except Exception as exc:
            label.setText(f"第 {index + 1} 页预览失败: {exc}")

        QTimer.singleShot(0, lambda: self.render_pdf_page(path, labels, generation, index + 1))

    def preview_image_max_size(self):
        viewport_width = self.viewport().width() or self.width()
        viewport_width = max(viewport_width, 416)
        available_width = max(360, viewport_width - 56)
        self.last_render_width = viewport_width
        return min(available_width, 1100), 1800

    def refresh_current_file(self):
        if self.current_path and os.path.isfile(self.current_path):
            self.show_file(self.current_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        viewport_width = self.viewport().width()
        if self.current_path and abs(viewport_width - self.last_render_width) > 32:
            self.resize_timer.start(180)

    def create_page_label(self, tooltip=""):
        label = QLabel()
        label.setObjectName("previewPage")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumSize(360, 420)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        label.setToolTip(tooltip)
        return label


class DuplicateDetectionThread(QThread):
    status_update = Signal(str, str)
    finished = Signal(object)

    def __init__(self, folder, mode, recursive, threshold):
        super().__init__()
        self.folder = folder
        self.mode = mode
        self.recursive = recursive
        self.threshold = threshold

    def run(self):
        try:
            if self.mode == "images":
                self.status_update.emit("正在检测图片重复内容...", "blue")
                report = find_duplicate_images(self.folder, self.recursive, self.threshold)
            else:
                self.status_update.emit("正在渲染并检测 PDF 页面重复内容...", "blue")
                report = find_duplicate_pdfs(self.folder, self.recursive, self.threshold)
            self.finished.emit(report)
        except Exception as exc:
            self.finished.emit(DetectionReport(error=str(exc)))


class ComparisonDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("重复内容对比")
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        title = QLabel(self._result_title())
        title.setStyleSheet("font: bold 14px;")
        layout.addWidget(title)

        preview_layout = QHBoxLayout()
        self.left_label = self._create_preview_area(preview_layout, result.display_a, result.page_a)
        self.right_label = self._create_preview_area(preview_layout, result.display_b, result.page_b)
        layout.addLayout(preview_layout)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._load_preview(self.left_label, result.file_a, result.page_a)
        self._load_preview(self.right_label, result.file_b, result.page_b)

    def _result_title(self):
        page_a = f" 第 {self.result.page_a} 页" if self.result.page_a else ""
        page_b = f" 第 {self.result.page_b} 页" if self.result.page_b else ""
        return f"{self.result.kind}: {self.result.display_a}{page_a}  <->  {self.result.display_b}{page_b}"

    def _create_preview_area(self, parent_layout, title, page_number):
        container = QWidget()
        layout = QVBoxLayout(container)
        suffix = f" 第 {page_number} 页" if page_number else ""
        label_title = QLabel(f"{title}{suffix}")
        label_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(label_title)

        preview = QLabel("暂无预览")
        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumSize(480, 560)
        preview.setStyleSheet("background: #f8fafc; border: 1px solid #d8dee9; border-radius: 5px;")

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(preview)
        layout.addWidget(scroll_area)
        parent_layout.addWidget(container)
        return preview

    def _load_preview(self, label, path, page_number):
        try:
            image = render_preview_image(path, page_number, max_size=(900, 900))
            pixmap = pil_image_to_pixmap(image)
            label.setPixmap(scaled_pixmap_for_label(pixmap, label, fallback_size=(520, 620)))
        except Exception as exc:
            label.setText(f"预览失败: {exc}")


class PDFMergerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 文件处理工具")
        self.setGeometry(700, 250, 1280, 820)
        self.setMinimumSize(1040, 680)
        self.apply_app_style()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.shell_splitter = QSplitter(Qt.Horizontal)
        self.shell_splitter.setObjectName("shellSplitter")
        self.shell_splitter.setChildrenCollapsible(False)
        self.shell_splitter.setHandleWidth(7)
        main_layout.addWidget(self.shell_splitter, 1)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(176)
        self.sidebar.setMaximumWidth(360)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 18, 16, 18)
        sidebar_layout.setSpacing(14)

        app_title = QLabel("PDF Tool")
        app_title.setObjectName("appTitle")
        sidebar_layout.addWidget(app_title)

        app_subtitle = QLabel("文件处理工作台")
        app_subtitle.setObjectName("appSubtitle")
        sidebar_layout.addWidget(app_subtitle)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setSelectionMode(QListWidget.SingleSelection)
        sidebar_layout.addWidget(self.nav_list, 1)
        self.shell_splitter.addWidget(self.sidebar)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("contentTabs")
        self.tab_widget.tabBar().hide()
        self.shell_splitter.addWidget(self.tab_widget)
        self.shell_splitter.setStretchFactor(0, 0)
        self.shell_splitter.setStretchFactor(1, 1)
        self.shell_splitter.setSizes([214, 1066])
        self.merge_tab = QWidget()
        self.setup_merge_tab()
        self.tab_widget.addTab(self.merge_tab, "PDF合并")

        self.compress_tab = QWidget()
        self.setup_compress_tab()
        self.tab_widget.addTab(self.compress_tab, "PDF压缩")

        self.convert_tab = QWidget()
        self.setup_convert_tab()
        self.tab_widget.addTab(self.convert_tab, "文件转换")

        # NEW: 新增拆分Tab
        self.split_tab = QWidget()
        self.setup_split_tab()
        self.duplicate_tab = QWidget()
        self.setup_duplicate_tab()
        self.tab_widget.addTab(self.duplicate_tab, "重复检测")
        self.tab_widget.addTab(self.split_tab, "PDF拆分")

        self.status_label = QLabel("就绪")
        for nav_text in ("PDF合并", "PDF压缩", "文件转换", "重复检测", "PDF拆分"):
            self.nav_list.addItem(nav_text)
        self.nav_list.currentRowChanged.connect(self.switch_workspace)
        self.tab_widget.currentChanged.connect(self.sync_navigation)
        self.nav_list.setCurrentRow(0)

        self.status_label.setObjectName("statusLabel")
        self.status_label.setStyleSheet("color: green;")
        main_layout.addWidget(self.status_label)

        self.output_directory = None
        self.compress_output_directory = None
        self.convert_output_directory = None
        self.split_output_directory = None  # NEW

    def switch_workspace(self, index):
        if 0 <= index < self.tab_widget.count() and self.tab_widget.currentIndex() != index:
            self.tab_widget.setCurrentIndex(index)

    def sync_navigation(self, index):
        if 0 <= index < self.nav_list.count() and self.nav_list.currentRow() != index:
            self.nav_list.setCurrentRow(index)

    def create_page_layout(self, tab):
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("pageScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        content.setObjectName("pageContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(14)
        scroll_area.setWidget(content)
        tab_layout.addWidget(scroll_area)
        return content_layout

    def create_page_title(self, title, subtitle):
        container = QWidget()
        container.setObjectName("pageHeader")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return container

    def create_preview_group(self, title, placeholder):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        preview = FilePreviewPanel(placeholder)
        layout.addWidget(preview)
        return group, preview

    def apply_app_style(self):
        self.setStyleSheet("""
            QMainWindow {
                background: #f5f5f7;
            }
            QWidget {
                font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", "Noto Sans CJK SC", Arial, sans-serif;
                font-size: 13px;
                color: #1d1d1f;
            }
            QWidget#sidebar {
                background: #eef1f5;
                border-right: 1px solid #d8dde6;
                min-width: 176px;
                max-width: 360px;
            }
            QLabel#appTitle {
                color: #111827;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#appSubtitle {
                color: #6b7280;
                font-size: 12px;
            }
            QListWidget#navList {
                border: none;
                border-radius: 0;
                background: transparent;
                color: #374151;
                padding: 4px;
                outline: none;
            }
            QListWidget#navList::item {
                min-height: 34px;
                padding: 7px 11px;
                margin: 2px 0;
                border-radius: 7px;
            }
            QListWidget#navList::item:hover {
                background: #e3e7ed;
                color: #111827;
            }
            QListWidget#navList::item:selected {
                background: #d7e8ff;
                color: #0a58ca;
                font-weight: 600;
            }
            QTabWidget#contentTabs::pane {
                border: none;
                background: #f5f5f7;
            }
            QTabWidget#contentTabs > QTabBar::tab {
                width: 0px;
                height: 0px;
                margin: 0px;
                padding: 0px;
                border: none;
            }
            QWidget#pageContent {
                background: #f5f5f7;
            }
            QWidget#pageHeader {
                background: transparent;
            }
            QLabel#pageTitle {
                color: #111827;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#pageSubtitle {
                color: #6b7280;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #d9dee7;
                border-radius: 9px;
                background: #ffffff;
                margin-top: 20px;
                padding: 22px 16px 16px 16px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                color: #374151;
                background: #ffffff;
                left: 14px;
                top: 2px;
                padding: 0 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QLineEdit {
                min-height: 36px;
                border: 1px solid #cfd6e1;
                border-radius: 6px;
                padding: 6px 11px;
                background: #fbfbfd;
            }
            QLineEdit:focus {
                border-color: #0a84ff;
                background: #ffffff;
            }
            QPushButton {
                min-height: 34px;
                border: 1px solid #cfd6e1;
                border-radius: 6px;
                padding: 6px 15px;
                background: #fbfbfd;
                color: #1d1d1f;
            }
            QPushButton:hover {
                background: #f2f5f9;
                border-color: #b8c1ce;
            }
            QPushButton:disabled {
                color: #9aa3af;
                background: #eceff3;
            }
            QPushButton#primaryButton {
                color: #ffffff;
                background: #0a84ff;
                border-color: #0a84ff;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover {
                background: #006edb;
                border-color: #006edb;
            }
            QListWidget, QTableWidget {
                border: 1px solid #d9dee7;
                border-radius: 7px;
                background: #fbfbfd;
                alternate-background-color: #f6f7f9;
                selection-background-color: #d7e8ff;
                selection-color: #111827;
            }
            QListWidget::item {
                min-height: 26px;
                padding: 4px 6px;
            }
            QHeaderView::section {
                background: #f6f7f9;
                border: none;
                border-bottom: 1px solid #d9dee7;
                padding: 8px;
                color: #4b5563;
                font-weight: 600;
            }
            QScrollArea {
                border: 1px solid #d9dee7;
                border-radius: 7px;
                background: #f0f2f5;
            }
            QScrollArea#pageScrollArea {
                border: none;
                border-radius: 0;
                background: #f5f5f7;
            }
            QScrollArea#previewScrollArea {
                min-height: 440px;
                background: #eef1f5;
            }
            QWidget#previewContent {
                background: #eef1f5;
            }
            QLabel#previewMessage, QLabel#previewPage, QLabel#previewText {
                background: #ffffff;
                border: 1px solid #dde3ec;
                border-radius: 9px;
                padding: 12px;
                color: #374151;
            }
            QLabel#previewPageTitle {
                color: #596579;
                font-size: 12px;
                font-weight: 500;
            }
            QSplitter::handle {
                background: #d9dee7;
            }
            QSplitter::handle:horizontal {
                width: 3px;
            }
            QSplitter#shellSplitter::handle {
                background: #d8dde6;
                width: 7px;
            }
            QSplitter#shellSplitter::handle:hover {
                background: #b9c4d4;
            }
            QProgressBar {
                min-height: 8px;
                max-height: 8px;
                border: none;
                border-radius: 4px;
                background: #e5e7eb;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 4px;
                background: #0a84ff;
            }
            QLabel#statusLabel {
                margin: 0;
                padding: 9px 16px;
                border-radius: 0;
                background: #ffffff;
                border-top: 1px solid #d9dee7;
                color: #167a3f;
            }
        """)

    def setup_inline_preview_label(self, label):
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(420, 520)
        label.setWordWrap(True)
        label.setStyleSheet("background: #f8fafc; border: 1px solid #d8dee9; border-radius: 5px; padding: 8px;")

    def set_preview_message(self, label, message):
        if hasattr(label, "show_message"):
            label.show_message(message)
            return

        label.clear()
        label.setAlignment(Qt.AlignCenter)
        label.setText(message)
        label.resize(max(label.minimumWidth(), 520), max(label.minimumHeight(), 520))

    def preview_file_in_label(self, label, path):
        if hasattr(label, "show_file"):
            label.show_file(path)
            return

        if not path or not os.path.isfile(path):
            self.set_preview_message(label, "文件不存在，无法预览")
            return

        extension = os.path.splitext(path)[1].lower()
        try:
            if extension == ".pdf":
                image = render_preview_image(path, 1, max_size=(1000, 1400))
                pixmap = pil_image_to_pixmap(image)
                label.setAlignment(Qt.AlignCenter)
                label.setPixmap(pixmap)
                label.resize(max(pixmap.width() + 24, label.minimumWidth()), max(pixmap.height() + 24, label.minimumHeight()))
                label.setToolTip(path)
            elif extension in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"):
                image = render_preview_image(path, max_size=(1200, 1600))
                pixmap = pil_image_to_pixmap(image)
                label.setAlignment(Qt.AlignCenter)
                label.setPixmap(pixmap)
                label.resize(max(pixmap.width() + 24, label.minimumWidth()), max(pixmap.height() + 24, label.minimumHeight()))
                label.setToolTip(path)
            elif extension in (".txt", ".md"):
                with open(path, "r", encoding="utf-8", errors="replace") as file:
                    text = file.read(3000)
                self.set_preview_message(label, text or "空文本文件")
                label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                label.resize(max(label.minimumWidth(), 720), max(label.minimumHeight(), 900))
                label.setToolTip(path)
            else:
                self.set_preview_message(label, "此文件类型暂不支持预览")
        except Exception as exc:
            self.set_preview_message(label, f"预览失败: {exc}")

    def update_merge_preview(self, *args):
        current_item = self.list_widget.currentItem()
        if not current_item:
            self.set_preview_message(self.merge_preview_label, "点击 PDF 文件列表中的文件后显示预览")
            return
        entry = self.file_entry_from_item(current_item)
        self.preview_file_in_label(self.merge_preview_label, entry.path)

    def update_compress_preview(self):
        self.preview_file_in_label(self.compress_preview_label, self.compress_input_path.text().strip())

    def update_convert_preview(self, *args):
        current_item = self.convert_list_widget.currentItem()
        if not current_item:
            self.set_preview_message(self.convert_preview_label, "点击文件列表中的图片、PDF 或文本后显示预览")
            return
        entry = self.file_entry_from_item(current_item)
        self.preview_file_in_label(self.convert_preview_label, entry.path)

    def update_split_preview(self):
        self.preview_file_in_label(self.split_preview_label, self.split_input_path.text().strip())

    def file_entry_from_item(self, item):
        data = item.data(Qt.UserRole)
        if isinstance(data, FileEntry):
            return data
        if isinstance(data, str):
            return FileEntry.from_path(data)
        root = self.convert_folder_path.text() if item.listWidget() is self.convert_list_widget else self.folder_path.text()
        return FileEntry.from_path(os.path.join(root, item.text()), root)

    def add_file_entry(self, list_widget, entry):
        item = QListWidgetItem(entry.display_name)
        item.setData(Qt.UserRole, entry)
        item.setToolTip(entry.path)
        list_widget.addItem(item)
        return item

    def add_merge_file(self, entry):
        return self.add_file_entry(self.list_widget, entry)

    def add_merge_pdf_path(self, path, source_root=""):
        return self.add_merge_file(FileEntry.from_path(path, source_root))

    def get_merge_pdf_paths(self):
        paths = []
        for index in range(self.list_widget.count()):
            entry = self.file_entry_from_item(self.list_widget.item(index))
            paths.append(entry.path)
        return paths

    def setup_merge_tab(self):
        layout = self.create_page_layout(self.merge_tab)
        layout.addWidget(self.create_page_title("PDF 文件合并", "整理多个 PDF 的顺序，预览内容后输出为一个文件。"))

        folder_group = QGroupBox("选择包含PDF的文件夹")
        folder_layout = QVBoxLayout(folder_group)
        self.folder_path = QLineEdit()
        self.folder_path.setPlaceholderText("选择一个文件夹，可只加载当前目录或遍历所有子文件夹")
        browse_folder_btn = QPushButton("浏览")
        browse_folder_btn.clicked.connect(self.browse_folder)
        recursive_folder_btn = QPushButton("遍历子文件夹")
        recursive_folder_btn.clicked.connect(self.load_pdf_files_recursive)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.folder_path)
        h_layout.addWidget(browse_folder_btn)
        h_layout.addWidget(recursive_folder_btn)
        folder_layout.addLayout(h_layout)
        layout.addWidget(folder_group)

        list_group = QGroupBox("PDF文件列表 (拖动可以调整顺序)")
        list_layout = QVBoxLayout(list_group)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.currentItemChanged.connect(self.update_merge_preview)
        list_layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(self.move_up)
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(self.move_down)
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("清除列表")
        clear_btn.clicked.connect(self.clear_list)
        btn_layout.addWidget(up_btn)
        btn_layout.addWidget(down_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        merge_preview_group, self.merge_preview_label = self.create_preview_group(
            "PDF内容预览",
            "点击 PDF 文件列表中的文件后显示预览",
        )
        merge_splitter = QSplitter(Qt.Horizontal)
        merge_splitter.addWidget(list_group)
        merge_splitter.addWidget(merge_preview_group)
        merge_splitter.setStretchFactor(0, 3)
        merge_splitter.setStretchFactor(1, 2)
        merge_splitter.setMinimumHeight(520)
        layout.addWidget(merge_splitter, 1)

        output_group = QGroupBox("输出文件路径")
        output_layout = QVBoxLayout(output_group)
        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText("例如：merged.pdf，若已存在会自动生成 merged(1).pdf")
        choose_save_btn = QPushButton("选择保存位置")
        choose_save_btn.clicked.connect(self.choose_save_location)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.output_name)
        h_layout.addWidget(choose_save_btn)
        output_layout.addLayout(h_layout)
        layout.addWidget(output_group)

        compress_check = QCheckBox("合并后压缩PDF")
        self.compress_after_merge = compress_check
        layout.addWidget(compress_check)

        self.merge_progress = QProgressBar()
        self.merge_progress.setRange(0, 0)  # Indeterminate
        self.merge_progress.setVisible(False)
        layout.addWidget(self.merge_progress)

        merge_btn = QPushButton("合并PDF文件")
        merge_btn.setObjectName("primaryButton")
        merge_btn.clicked.connect(self.start_merge)
        layout.addWidget(merge_btn)
        self.merge_btn = merge_btn
        layout.addStretch()

    def setup_compress_tab(self):
        layout = self.create_page_layout(self.compress_tab)
        layout.addWidget(self.create_page_title("PDF 文件压缩", "选择压缩质量和目标大小，预览源文件后生成更小的 PDF。"))

        file_group = QGroupBox("选择要压缩的PDF文件")
        file_layout = QVBoxLayout(file_group)
        self.compress_input_path = QLineEdit()
        self.compress_input_path.editingFinished.connect(self.update_compress_preview)
        self.compress_input_path.setPlaceholderText("选择要压缩的 PDF 文件")
        browse_input_btn = QPushButton("浏览")
        browse_input_btn.clicked.connect(self.browse_compress_input)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.compress_input_path)
        h_layout.addWidget(browse_input_btn)
        file_layout.addLayout(h_layout)

        compress_preview_group, self.compress_preview_label = self.create_preview_group(
            "PDF内容预览",
            "选择 PDF 文件后显示预览",
        )

        compress_splitter = QSplitter(Qt.Horizontal)
        compress_splitter.addWidget(file_group)
        compress_splitter.addWidget(compress_preview_group)
        compress_splitter.setStretchFactor(0, 2)
        compress_splitter.setStretchFactor(1, 3)
        compress_splitter.setMinimumHeight(520)
        layout.addWidget(compress_splitter, 1)

        # MODIFIED: 改为显示完整输出路径
        output_group = QGroupBox("输出文件路径")
        output_layout = QVBoxLayout(output_group)
        self.compress_output_path = QLineEdit()  # MODIFIED: 初始为空，显示完整路径
        self.compress_output_path.setPlaceholderText("同名文件已存在时会自动递增")
        choose_output_btn = QPushButton("选择保存位置")
        choose_output_btn.clicked.connect(self.choose_compress_output)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.compress_output_path)
        h_layout.addWidget(choose_output_btn)
        output_layout.addLayout(h_layout)
        layout.addWidget(output_group)

        quality_group = QGroupBox("压缩质量")
        quality_layout = QVBoxLayout(quality_group)
        self.quality_group = QButtonGroup()
        levels = [
            ("低质量 (文件最小)", "/screen"),
            ("中等质量 (推荐)", "/ebook"),
            ("高质量", "/printer"),
            ("最高质量", "/prepress")
        ]
        self.compression_level = "/ebook"
        for text, value in levels:
            radio = QRadioButton(text)
            radio.setProperty("value", value)
            radio.toggled.connect(self.update_compression_level)
            quality_layout.addWidget(radio)
            self.quality_group.addButton(radio)
            if value == "/ebook":
                radio.setChecked(True)
        layout.addWidget(quality_group)

        size_group = QGroupBox("目标文件大小 (MB, 0表示不限制)")
        size_layout = QVBoxLayout(size_group)
        self.target_size = QLineEdit("10")
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.target_size)
        h_layout.addWidget(QLabel("MB"))
        size_layout.addLayout(h_layout)
        layout.addWidget(size_group)

        self.compress_progress = QProgressBar()
        self.compress_progress.setRange(0, 0)  # Indeterminate
        self.compress_progress.setVisible(False)
        layout.addWidget(self.compress_progress)

        compress_btn = QPushButton("压缩PDF文件")
        compress_btn.setObjectName("primaryButton")
        compress_btn.clicked.connect(self.start_compress)
        layout.addWidget(compress_btn)
        self.compress_btn = compress_btn
        layout.addStretch()

    def setup_convert_tab(self):
        layout = self.create_page_layout(self.convert_tab)
        layout.addWidget(self.create_page_title("文件转换为 PDF", "将图片、文本或已有 PDF 输出到指定目录，并可追加到合并列表。"))

        folder_group = QGroupBox("选择包含文件的文件夹")
        folder_layout = QVBoxLayout(folder_group)
        self.convert_folder_path = QLineEdit()
        self.convert_folder_path.setPlaceholderText("选择包含图片或文本文件的文件夹")
        browse_convert_folder_btn = QPushButton("浏览")
        browse_convert_folder_btn.clicked.connect(self.browse_convert_folder)
        recursive_convert_btn = QPushButton("遍历子文件夹")
        recursive_convert_btn.clicked.connect(self.load_convert_files_recursive)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.convert_folder_path)
        h_layout.addWidget(browse_convert_folder_btn)
        h_layout.addWidget(recursive_convert_btn)
        folder_layout.addLayout(h_layout)
        layout.addWidget(folder_group)

        list_group = QGroupBox("文件列表 (支持图像、文本、PDF等)")
        list_layout = QVBoxLayout(list_group)
        self.convert_list_widget = QListWidget()
        self.convert_list_widget.currentItemChanged.connect(self.update_convert_preview)
        self.convert_list_widget.setSelectionMode(QListWidget.ExtendedSelection)  # 支持多选
        list_layout.addWidget(self.convert_list_widget)

        btn_layout = QHBoxLayout()
        remove_convert_btn = QPushButton("移除选中")
        remove_convert_btn.clicked.connect(self.remove_convert_selected)
        clear_convert_btn = QPushButton("清除列表")
        clear_convert_btn.clicked.connect(self.clear_convert_list)
        btn_layout.addWidget(remove_convert_btn)
        btn_layout.addWidget(clear_convert_btn)
        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        convert_preview_group, self.convert_preview_label = self.create_preview_group(
            "文件内容预览",
            "点击文件列表中的图片、PDF 或文本后显示预览",
        )

        convert_splitter = QSplitter(Qt.Horizontal)
        convert_splitter.addWidget(list_group)
        convert_splitter.addWidget(convert_preview_group)
        convert_splitter.setStretchFactor(0, 3)
        convert_splitter.setStretchFactor(1, 2)
        convert_splitter.setMinimumHeight(520)
        layout.addWidget(convert_splitter, 1)

        output_group = QGroupBox("输出目录")
        output_layout = QVBoxLayout(output_group)
        self.convert_output_path = QLineEdit()
        self.convert_output_path.setPlaceholderText("转换结果输出目录")
        choose_convert_output_btn = QPushButton("选择目录")
        choose_convert_output_btn.clicked.connect(self.choose_convert_output)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.convert_output_path)
        h_layout.addWidget(choose_convert_output_btn)
        output_layout.addLayout(h_layout)
        layout.addWidget(output_group)

        add_to_merge_check = QCheckBox("转换后添加到'PDF合并'界面的'PDF文件列表'中")
        self.add_to_merge = add_to_merge_check
        layout.addWidget(add_to_merge_check)

        self.convert_progress = QProgressBar()
        self.convert_progress.setRange(0, 0)  # Indeterminate
        self.convert_progress.setVisible(False)
        layout.addWidget(self.convert_progress)

        convert_btn = QPushButton("开始转换")
        convert_btn.setObjectName("primaryButton")
        convert_btn.clicked.connect(self.start_convert)
        layout.addWidget(convert_btn)
        self.convert_btn = convert_btn
        layout.addStretch()

    # NEW: 设置拆分Tab
    def setup_split_tab(self):
        layout = self.create_page_layout(self.split_tab)
        layout.addWidget(self.create_page_title("PDF 文件拆分", "按单页或指定页码范围拆分 PDF，并在右侧滚动预览内容。"))

        file_group = QGroupBox("选择要拆分的PDF文件")
        file_layout = QVBoxLayout(file_group)
        self.split_input_path = QLineEdit()
        self.split_input_path.editingFinished.connect(self.update_split_preview)
        self.split_input_path.setPlaceholderText("选择要拆分的 PDF 文件")
        browse_split_input_btn = QPushButton("浏览")
        browse_split_input_btn.clicked.connect(self.browse_split_input)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.split_input_path)
        h_layout.addWidget(browse_split_input_btn)
        file_layout.addLayout(h_layout)

        split_preview_group, self.split_preview_label = self.create_preview_group(
            "PDF内容预览",
            "选择 PDF 文件后显示预览",
        )

        split_splitter = QSplitter(Qt.Horizontal)
        split_splitter.addWidget(file_group)
        split_splitter.addWidget(split_preview_group)
        split_splitter.setStretchFactor(0, 2)
        split_splitter.setStretchFactor(1, 3)
        split_splitter.setMinimumHeight(520)
        layout.addWidget(split_splitter, 1)

        output_group = QGroupBox("输出目录")
        output_layout = QVBoxLayout(output_group)
        self.split_output_path = QLineEdit()
        self.split_output_path.setPlaceholderText("拆分结果输出目录")
        choose_split_output_btn = QPushButton("选择目录")
        choose_split_output_btn.clicked.connect(self.choose_split_output)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.split_output_path)
        h_layout.addWidget(choose_split_output_btn)
        output_layout.addLayout(h_layout)
        layout.addWidget(output_group)

        mode_group = QGroupBox("拆分模式")
        mode_layout = QVBoxLayout(mode_group)
        self.split_mode_group = QButtonGroup()
        self.split_mode = "page_by_page"
        page_by_page_radio = QRadioButton("逐页拆分 (每个页面一个PDF)")
        page_by_page_radio.setProperty("value", "page_by_page")
        page_by_page_radio.toggled.connect(self.update_split_mode)
        ranges_radio = QRadioButton("指定页码范围 (例如: 2-10,12,15-20)")
        ranges_radio.setProperty("value", "ranges")
        ranges_radio.toggled.connect(self.update_split_mode)
        mode_layout.addWidget(page_by_page_radio)
        mode_layout.addWidget(ranges_radio)
        self.split_mode_group.addButton(page_by_page_radio)
        self.split_mode_group.addButton(ranges_radio)
        page_by_page_radio.setChecked(True)
        layout.addWidget(mode_group)

        ranges_group = QGroupBox("页码范围 (仅在指定模式下有效)")
        ranges_layout = QVBoxLayout(ranges_group)
        self.page_ranges = QLineEdit()
        self.page_ranges.setPlaceholderText("例如：2-10,12,15-20")
        ranges_layout.addWidget(self.page_ranges)
        layout.addWidget(ranges_group)

        self.split_progress = QProgressBar()
        self.split_progress.setRange(0, 0)  # Indeterminate
        self.split_progress.setVisible(False)
        layout.addWidget(self.split_progress)

        split_btn = QPushButton("开始拆分")
        split_btn.setObjectName("primaryButton")
        split_btn.clicked.connect(self.start_split)
        layout.addWidget(split_btn)
        self.split_btn = split_btn
        layout.addStretch()

    def setup_duplicate_tab(self):
        layout = self.create_page_layout(self.duplicate_tab)
        self.duplicate_results = []
        self.duplicate_skipped = []

        layout.addWidget(self.create_page_title("重复内容检测", "扫描图片或 PDF 页面，以视觉相似度找出可能重复的内容。"))

        folder_group = QGroupBox("选择检测文件夹")
        folder_layout = QVBoxLayout(folder_group)
        self.duplicate_folder_path = QLineEdit()
        self.duplicate_folder_path.setPlaceholderText("选择包含图片或 PDF 的文件夹")
        browse_duplicate_btn = QPushButton("浏览")
        browse_duplicate_btn.clicked.connect(self.browse_duplicate_folder)
        self.duplicate_recursive_check = QCheckBox("遍历子文件夹")
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.duplicate_folder_path)
        folder_row.addWidget(browse_duplicate_btn)
        folder_row.addWidget(self.duplicate_recursive_check)
        folder_layout.addLayout(folder_row)
        layout.addWidget(folder_group)

        options_group = QGroupBox("检测设置")
        options_layout = QHBoxLayout(options_group)
        self.duplicate_mode_group = QButtonGroup()
        self.duplicate_image_radio = QRadioButton("图片重复")
        self.duplicate_image_radio.setChecked(True)
        self.duplicate_pdf_radio = QRadioButton("PDF重复")
        self.duplicate_mode_group.addButton(self.duplicate_image_radio)
        self.duplicate_mode_group.addButton(self.duplicate_pdf_radio)
        self.duplicate_threshold = QLineEdit("6")
        self.duplicate_threshold.setMaximumWidth(80)
        options_layout.addWidget(self.duplicate_image_radio)
        options_layout.addWidget(self.duplicate_pdf_radio)
        options_layout.addWidget(QLabel("相似阈值"))
        options_layout.addWidget(self.duplicate_threshold)
        options_layout.addStretch()
        layout.addWidget(options_group)

        action_layout = QHBoxLayout()
        self.duplicate_detect_btn = QPushButton("开始检测")
        self.duplicate_detect_btn.setObjectName("primaryButton")
        self.duplicate_detect_btn.clicked.connect(self.start_duplicate_detection)
        clear_duplicate_btn = QPushButton("清空结果")
        clear_duplicate_btn.clicked.connect(self.clear_duplicate_results)
        self.duplicate_compare_btn = QPushButton("对比")
        self.duplicate_compare_btn.clicked.connect(self.open_duplicate_comparison)
        action_layout.addWidget(self.duplicate_detect_btn)
        action_layout.addWidget(clear_duplicate_btn)
        action_layout.addWidget(self.duplicate_compare_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.duplicate_progress = QProgressBar()
        self.duplicate_progress.setRange(0, 0)
        self.duplicate_progress.setVisible(False)
        layout.addWidget(self.duplicate_progress)

        result_group = QGroupBox("重复结果")
        result_layout = QVBoxLayout(result_group)
        self.duplicate_result_table = QTableWidget(0, 7)
        self.duplicate_result_table.setHorizontalHeaderLabels(["类型", "文件A", "页码A", "文件B", "页码B", "距离", "判定"])
        self.duplicate_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.duplicate_result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.duplicate_result_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.duplicate_result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.duplicate_result_table.itemSelectionChanged.connect(self.update_duplicate_preview)
        result_layout.addWidget(self.duplicate_result_table)

        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)
        duplicate_preview_row = QHBoxLayout()
        self.duplicate_preview_a = QLabel("选择一条结果后显示左侧预览")
        self.duplicate_preview_b = QLabel("选择一条结果后显示右侧预览")
        for preview_label in (self.duplicate_preview_a, self.duplicate_preview_b):
            self.setup_inline_preview_label(preview_label)
            preview_scroll = QScrollArea()
            preview_scroll.setObjectName("previewScrollArea")
            preview_scroll.setWidgetResizable(False)
            preview_scroll.setAlignment(Qt.AlignCenter)
            preview_scroll.setWidget(preview_label)
            duplicate_preview_row.addWidget(preview_scroll)
        preview_layout.addLayout(duplicate_preview_row)

        duplicate_splitter = QSplitter(Qt.Horizontal)
        duplicate_splitter.addWidget(result_group)
        duplicate_splitter.addWidget(preview_group)
        duplicate_splitter.setStretchFactor(0, 3)
        duplicate_splitter.setStretchFactor(1, 2)
        duplicate_splitter.setMinimumHeight(520)
        layout.addWidget(duplicate_splitter, 1)
        layout.addStretch()

    def browse_duplicate_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要检测重复内容的文件夹")
        if folder:
            self.duplicate_folder_path.setText(folder)

    def start_duplicate_detection(self):
        folder = self.duplicate_folder_path.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.critical(self, "错误", "请先选择有效的文件夹")
            return

        try:
            threshold = int(self.duplicate_threshold.text().strip())
            if threshold < 0:
                raise ValueError
        except ValueError:
            QMessageBox.critical(self, "错误", "相似阈值必须是大于等于 0 的整数")
            return

        mode = "images" if self.duplicate_image_radio.isChecked() else "pdfs"
        self.clear_duplicate_results(update_status=False)
        self.duplicate_detect_btn.setEnabled(False)
        self.duplicate_progress.setVisible(True)
        self.status_label.setText("正在检测重复内容...")
        self.status_label.setStyleSheet("color: blue;")

        thread = DuplicateDetectionThread(
            folder,
            mode,
            self.duplicate_recursive_check.isChecked(),
            threshold,
        )
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.duplicate_detection_finished)
        thread.start()
        self.duplicate_thread = thread

    def duplicate_detection_finished(self, report):
        self.duplicate_progress.setVisible(False)
        self.duplicate_detect_btn.setEnabled(True)

        if report.error:
            QMessageBox.critical(self, "错误", report.error)
            self.status_label.setText(f"重复检测失败: {report.error}")
            self.status_label.setStyleSheet("color: red;")
            return

        self.duplicate_results = report.results
        self.duplicate_skipped = report.skipped
        self.populate_duplicate_results()

        skipped_text = f"，跳过 {len(report.skipped)} 个文件" if report.skipped else ""
        self.status_label.setText(
            f"检测完成：扫描 {report.scanned_files} 个文件 / {report.scanned_items} 个内容项，发现 {len(report.results)} 条重复结果{skipped_text}"
        )
        self.status_label.setStyleSheet("color: green;" if report.results else "color: blue;")

    def populate_duplicate_results(self):
        self.duplicate_result_table.setRowCount(len(self.duplicate_results))
        for row, result in enumerate(self.duplicate_results):
            values = [
                result.kind,
                result.display_a,
                "" if result.page_a is None else str(result.page_a),
                result.display_b,
                "" if result.page_b is None else str(result.page_b),
                str(result.distance),
                result.verdict,
            ]
            for column, value in enumerate(values):
                self.duplicate_result_table.setItem(row, column, QTableWidgetItem(value))

        if self.duplicate_results:
            self.duplicate_result_table.selectRow(0)

    def clear_duplicate_results(self, update_status=True):
        self.duplicate_results = []
        self.duplicate_skipped = []
        self.duplicate_result_table.setRowCount(0)
        self.duplicate_preview_a.setText("选择一条结果后显示左侧预览")
        self.duplicate_preview_b.setText("选择一条结果后显示右侧预览")
        if update_status:
            self.status_label.setText("重复检测结果已清空")
            self.status_label.setStyleSheet("color: blue;")

    def current_duplicate_result(self):
        selected_rows = self.duplicate_result_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        if row < 0 or row >= len(self.duplicate_results):
            return None
        return self.duplicate_results[row]

    def update_duplicate_preview(self):
        result = self.current_duplicate_result()
        if result is None:
            return
        self.set_duplicate_preview(self.duplicate_preview_a, result.file_a, result.page_a)
        self.set_duplicate_preview(self.duplicate_preview_b, result.file_b, result.page_b)

    def set_duplicate_preview(self, label, path, page_number):
        try:
            image = render_preview_image(path, page_number, max_size=(1000, 1400))
            pixmap = pil_image_to_pixmap(image)
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(pixmap)
            label.resize(max(pixmap.width() + 24, label.minimumWidth()), max(pixmap.height() + 24, label.minimumHeight()))
            label.setToolTip(path)
        except Exception as exc:
            label.setText(f"预览失败: {exc}")

    def open_duplicate_comparison(self):
        result = self.current_duplicate_result()
        if result is None:
            QMessageBox.information(self, "提示", "请先选择一条重复结果")
            return
        dialog = ComparisonDialog(result, self)
        dialog.exec()

    def update_compression_level(self, checked):
        if checked:
            sender = self.sender()
            self.compression_level = sender.property("value")

    # NEW: 更新拆分模式
    def update_split_mode(self, checked):
        if checked:
            sender = self.sender()
            self.split_mode = sender.property("value")

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含PDF文件的文件夹")
        if folder:
            self.folder_path.setText(folder)
            self.output_directory = folder
            default_path = make_unique_path(os.path.join(folder, "merged.pdf"))
            self.output_name.setText(default_path)
            self.load_pdf_files()

    def browse_compress_input(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要压缩的PDF文件", "", "PDF files (*.pdf);;All files (*.*)")
        if file_path:
            self.compress_input_path.setText(file_path)
            directory, filename = os.path.split(file_path)
            name, ext = os.path.splitext(filename)
            # MODIFIED: 设置完整输出路径
            default_output_path = make_unique_path(os.path.join(directory, f"{name}_compressed{ext}"))
            self.compress_output_path.setText(default_output_path)
            self.compress_output_directory = directory
            self.update_compress_preview()

    def choose_save_location(self):
        default_file = self.output_name.text().strip() or make_unique_path(os.path.join(self.output_directory or os.path.expanduser("~"), "merged.pdf"))
        file_path, _ = QFileDialog.getSaveFileName(self, "选择保存位置", default_file, "PDF files (*.pdf);;All files (*.*)")
        if file_path:
            self.output_name.setText(file_path)
            self.output_directory = os.path.dirname(file_path)

    def choose_compress_output(self):
        # MODIFIED: 默认使用当前compress_output_directory或用户目录
        default_file = self.compress_output_path.text() or os.path.join(self.compress_output_directory or os.path.expanduser("~"), "compressed.pdf")
        file_path, _ = QFileDialog.getSaveFileName(self, "选择保存位置", default_file, "PDF files (*.pdf);;All files (*.*)")
        if file_path:
            self.compress_output_path.setText(file_path)
            self.compress_output_directory = os.path.dirname(file_path)

    def load_pdf_files(self, recursive=False):
        self.list_widget.clear()
        self.set_preview_message(self.merge_preview_label, "点击 PDF 文件列表中的文件后显示预览")
        folder = self.folder_path.text()
        if not os.path.isdir(folder):
            return

        pdf_files = collect_relative_files(folder, ('.pdf',), recursive=recursive)

        for pdf in pdf_files:
            self.add_merge_pdf_path(os.path.join(folder, pdf), folder)

        if pdf_files:
            self.list_widget.setCurrentRow(0)
            scope = "当前文件夹及子文件夹" if recursive else "当前文件夹"
            self.status_label.setText(f"{scope}找到 {len(pdf_files)} 个PDF文件")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.set_preview_message(self.merge_preview_label, "点击 PDF 文件列表中的文件后显示预览")
            self.status_label.setText("未找到PDF文件")
            self.status_label.setStyleSheet("color: red;")

    def load_pdf_files_recursive(self):
        if not os.path.isdir(self.folder_path.text()):
            QMessageBox.critical(self, "错误", "请先选择有效的文件夹")
            return
        self.load_pdf_files(recursive=True)

    def browse_convert_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含文件的文件夹")
        if folder:
            self.convert_folder_path.setText(folder)
            self.convert_output_directory = folder
            self.convert_output_path.setText(folder)
            self.load_convert_files()

    def load_convert_files(self, recursive=False):
        self.convert_list_widget.clear()
        self.set_preview_message(self.convert_preview_label, "点击文件列表中的图片、PDF 或文本后显示预览")
        folder = self.convert_folder_path.text()
        if not os.path.isdir(folder):
            return

        supported_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.txt', '.md', '.pdf')
        files = collect_relative_files(folder, supported_ext, recursive=recursive)

        for file in files:
            self.add_file_entry(self.convert_list_widget, FileEntry.from_path(os.path.join(folder, file), folder))

        if files:
            self.convert_list_widget.setCurrentRow(0)
            scope = "当前文件夹及子文件夹" if recursive else "当前文件夹"
            self.status_label.setText(f"{scope}找到 {len(files)} 个支持的文件")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("未找到支持的文件")
            self.status_label.setStyleSheet("color: red;")

    def load_convert_files_recursive(self):
        if not os.path.isdir(self.convert_folder_path.text()):
            QMessageBox.critical(self, "错误", "请先选择有效的文件夹")
            return
        self.load_convert_files(recursive=True)

    def choose_convert_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.convert_output_directory = directory
            self.convert_output_path.setText(directory)

    # NEW: 浏览拆分输入文件
    def browse_split_input(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要拆分的PDF文件", "", "PDF files (*.pdf);;All files (*.*)")
        if file_path:
            self.split_input_path.setText(file_path)
            directory = os.path.dirname(file_path)
            self.split_output_directory = directory
            self.split_output_path.setText(directory)
            self.update_split_preview()

    # NEW: 选择拆分输出目录
    def choose_split_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.split_output_directory = directory
            self.split_output_path.setText(directory)

    def remove_selected(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.list_widget.takeItem(self.list_widget.row(item))
        self.status_label.setText("已移除选中文件")
        self.status_label.setStyleSheet("color: blue;")

    def remove_convert_selected(self):
        selected_items = self.convert_list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.convert_list_widget.takeItem(self.convert_list_widget.row(item))
        self.status_label.setText("已移除选中文件")
        self.status_label.setStyleSheet("color: blue;")

    def clear_list(self):
        self.list_widget.clear()
        self.set_preview_message(self.merge_preview_label, "点击 PDF 文件列表中的文件后显示预览")
        self.status_label.setText("列表已清除")
        self.status_label.setStyleSheet("color: blue;")

    def clear_convert_list(self):
        self.convert_list_widget.clear()
        self.set_preview_message(self.convert_preview_label, "点击文件列表中的图片、PDF 或文本后显示预览")
        self.status_label.setText("转换列表已清除")
        self.status_label.setStyleSheet("color: blue;")

    def move_up(self):
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)

    def move_down(self):
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)

    def start_merge(self):
        if self.list_widget.count() == 0:
            QMessageBox.critical(self, "错误", "没有PDF文件可合并")
            return

        output_path = self.output_name.text().strip()
        if not output_path:
            QMessageBox.critical(self, "错误", "请输入输出文件路径")
            return

        if not output_path.lower().endswith('.pdf'):
            output_path += '.pdf'
            self.output_name.setText(output_path)

        self.output_directory = os.path.dirname(output_path)

        if not os.path.isdir(self.output_directory):
            QMessageBox.critical(self, "错误", "输出目录无效")
            return

        output_path = make_unique_path(output_path)
        self.output_name.setText(output_path)

        self.merge_btn.setEnabled(False)
        self.merge_progress.setVisible(True)
        self.status_label.setText("正在合并PDF文件...")
        self.status_label.setStyleSheet("color: blue;")

        pdf_paths = self.get_merge_pdf_paths()
        thread = MergeThread(output_path, pdf_paths, self.compress_after_merge.isChecked())
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.merge_finished)
        thread.start()
        self.merge_thread = thread

    def start_convert(self):
        if self.convert_list_widget.count() == 0:
            QMessageBox.critical(self, "错误", "没有文件可转换")
            return

        output_dir = self.convert_output_path.text().strip() or self.convert_output_directory or self.convert_folder_path.text()
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.critical(self, "错误", "请先选择有效的输出目录")
            return
        self.convert_output_directory = output_dir
        self.convert_output_path.setText(output_dir)

        self.convert_btn.setEnabled(False)
        self.convert_progress.setVisible(True)
        self.status_label.setText("正在转换文件...")
        self.status_label.setStyleSheet("color: blue;")

        file_list = [
            self.file_entry_from_item(self.convert_list_widget.item(i)).path
            for i in range(self.convert_list_widget.count())
        ]
        thread = ConversionThread(self.convert_folder_path.text(), self.convert_output_directory, file_list)
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.convert_finished)
        thread.start()
        self.convert_thread = thread

    # NEW: 开始拆分
    def start_split(self):
        input_path = self.split_input_path.text()
        if not input_path or not os.path.isfile(input_path):
            QMessageBox.critical(self, "错误", "请选择有效的PDF文件")
            return

        output_dir = self.split_output_path.text().strip() or self.split_output_directory or os.path.dirname(input_path)
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.critical(self, "错误", "请选择有效的输出目录")
            return
        self.split_output_directory = output_dir
        self.split_output_path.setText(output_dir)

        page_ranges = None
        if self.split_mode == 'ranges':
            page_ranges = self.page_ranges.text().strip()
            if not page_ranges:
                QMessageBox.critical(self, "错误", "请指定页码范围")
                return

        self.split_btn.setEnabled(False)
        self.split_progress.setVisible(True)
        self.status_label.setText("正在拆分PDF文件...")
        self.status_label.setStyleSheet("color: blue;")

        thread = SplitThread(input_path, self.split_output_directory, self.split_mode, page_ranges)
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.split_finished)
        thread.start()
        self.split_thread = thread

    def update_status(self, message, color):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color};")

    def merge_finished(self, message):
        self.merge_progress.setVisible(False)
        self.merge_btn.setEnabled(True)
        if "错误" in message or "发生错误" in message:
            QMessageBox.critical(self, "错误", message)
        else:
            QMessageBox.information(self, "成功", message)

    def start_compress(self):
        input_path = self.compress_input_path.text()
        if not input_path or not os.path.isfile(input_path):
            QMessageBox.critical(self, "错误", "请选择有效的PDF文件")
            return

        # MODIFIED: 使用完整路径
        output_path = self.compress_output_path.text().strip()
        if not output_path:
            QMessageBox.critical(self, "错误", "请输入输出文件路径")
            return

        if not output_path.lower().endswith('.pdf'):
            output_path += '.pdf'
            self.compress_output_path.setText(output_path)

        self.compress_output_directory = os.path.dirname(output_path)

        if not os.path.isdir(self.compress_output_directory):
            QMessageBox.critical(self, "错误", "输出目录无效")
            return

        output_path = make_unique_path(output_path)
        self.compress_output_path.setText(output_path)

        try:
            target_size_mb = float(self.target_size.text())
            if target_size_mb < 0:
                raise ValueError("目标大小不能为负数")
        except ValueError:
            QMessageBox.critical(self, "错误", "请输入有效的目标文件大小")
            return

        self.compress_btn.setEnabled(False)
        self.compress_progress.setVisible(True)
        self.status_label.setText("正在压缩PDF文件...")
        self.status_label.setStyleSheet("color: blue;")

        thread = CompressThread(input_path, output_path, self.compression_level, target_size_mb)
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.compress_finished)
        thread.start()
        self.compress_thread = thread

    def compress_finished(self, message):
        self.compress_progress.setVisible(False)
        self.compress_btn.setEnabled(True)
        if "错误" in message or "发生错误" in message:
            QMessageBox.critical(self, "错误", message)
        elif "大于目标大小" in message:
            QMessageBox.warning(self, "警告", message)
        else:
            QMessageBox.information(self, "成功", message)

    def convert_finished(self, message, converted_pdfs):
        self.convert_progress.setVisible(False)
        self.convert_btn.setEnabled(True)
        if "错误" in message or "发生错误" in message:
            QMessageBox.critical(self, "错误", message)
        else:
            QMessageBox.information(self, "成功", message)
            if self.add_to_merge.isChecked() and converted_pdfs:
                for pdf_path in converted_pdfs:
                    self.add_merge_pdf_path(pdf_path, self.convert_output_directory)
                self.status_label.setText("转换文件已添加到合并列表")
                self.status_label.setStyleSheet("color: green;")

    # NEW: 拆分完成处理
    def split_finished(self, message):
        self.split_progress.setVisible(False)
        self.split_btn.setEnabled(True)
        if "错误" in message or "发生错误" in message:
            QMessageBox.critical(self, "错误", message)
        else:
            QMessageBox.information(self, "成功", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PDFMergerApp()
    window.show()
    sys.exit(app.exec())
