import os
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QListWidget, QFileDialog, QMessageBox,
    QProgressBar, QCheckBox, QRadioButton, QButtonGroup, QTabWidget, QGroupBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import subprocess

# NEW: 添加用于文件转换的库
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

class MergeThread(QThread):
    status_update = Signal(str, str)  # message, color
    finished = Signal(str)

    def __init__(self, output_path, folder, pdf_list, compress_after_merge):
        super().__init__()
        self.output_path = output_path
        self.folder = folder
        self.pdf_list = pdf_list
        self.compress_after_merge = compress_after_merge

    def run(self):
        try:
            merger = PdfMerger()
            for pdf_file in self.pdf_list:
                pdf_path = os.path.join(self.folder, pdf_file)
                try:
                    with open(pdf_path, 'rb') as f:
                        reader = PdfReader(f)
                        if len(reader.pages) > 0:
                            merger.append(pdf_path)
                        else:
                            print(f"警告: {pdf_file} 没有页面，已跳过")
                except Exception as e:
                    print(f"错误: 无法读取 {pdf_file}: {str(e)}")

            with open(self.output_path, 'wb') as out_file:
                merger.write(out_file)
            merger.close()

            if self.compress_after_merge:
                self.status_update.emit("合并完成，开始压缩...", "blue")
                compressed_path = os.path.splitext(self.output_path)[0] + "_compressed.pdf"
                self.compress_pdf(self.output_path, compressed_path)
                self.output_path = compressed_path

            self.status_update.emit(f"处理完成: {self.output_path}", "green")
            self.finished.emit(f"PDF文件已成功处理到 {self.output_path}")

        except Exception as e:
            error_msg = f"处理过程中发生错误: {str(e)}"
            self.status_update.emit(error_msg, "red")
            self.finished.emit(error_msg)

    def compress_pdf(self, input_pdf, output_pdf):
        try:
            gs_command = [
                "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
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
                "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
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

    def __init__(self, folder, output_dir, file_list, add_to_merge_list):
        super().__init__()
        self.folder = folder
        self.output_dir = output_dir
        self.file_list = file_list
        self.add_to_merge_list = add_to_merge_list

    def run(self):
        converted_pdfs = []
        try:
            for file_name in self.file_list:
                input_path = os.path.join(self.folder, file_name)
                output_pdf = os.path.join(self.output_dir, os.path.splitext(file_name)[0] + ".pdf")
                
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
                
                converted_pdfs.append(os.path.basename(output_pdf))
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
                        output_pdf = os.path.join(self.output_dir, f"{base_name}_page{page_num}.pdf")
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
                    output_pdf = os.path.join(self.output_dir, f"{base_name}_split.pdf")
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

class PDFMergerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 文件处理工具")
        self.setGeometry(900, 400, 900, 700)
        self.setMinimumSize(800, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

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
        self.tab_widget.addTab(self.split_tab, "PDF拆分")

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: green;")
        main_layout.addWidget(self.status_label)

        self.output_directory = None
        self.compress_output_directory = None
        self.convert_output_directory = None
        self.split_output_directory = None  # NEW

    def setup_merge_tab(self):
        layout = QVBoxLayout(self.merge_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        title_label = QLabel("PDF 文件合并")
        title_label.setStyleSheet("font: bold 16px;")
        layout.addWidget(title_label)

        folder_group = QGroupBox("选择包含PDF的文件夹")
        folder_layout = QVBoxLayout(folder_group)
        self.folder_path = QLineEdit()
        browse_folder_btn = QPushButton("浏览")
        browse_folder_btn.clicked.connect(self.browse_folder)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.folder_path)
        h_layout.addWidget(browse_folder_btn)
        folder_layout.addLayout(h_layout)
        layout.addWidget(folder_group)

        list_group = QGroupBox("PDF文件列表 (拖动可以调整顺序)")
        list_layout = QVBoxLayout(list_group)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
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
        list_layout.addLayout(btn_layout)
        layout.addWidget(list_group)

        output_group = QGroupBox("输出文件路径")
        output_layout = QVBoxLayout(output_group)
        self.output_name = QLineEdit()
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
        layout.addWidget(self.merge_progress)

        merge_btn = QPushButton("合并PDF文件")
        merge_btn.clicked.connect(self.start_merge)
        layout.addWidget(merge_btn)
        self.merge_btn = merge_btn

    def setup_compress_tab(self):
        layout = QVBoxLayout(self.compress_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        title_label = QLabel("PDF 文件压缩")
        title_label.setStyleSheet("font: bold 16px;")
        layout.addWidget(title_label)

        file_group = QGroupBox("选择要压缩的PDF文件")
        file_layout = QVBoxLayout(file_group)
        self.compress_input_path = QLineEdit()
        browse_input_btn = QPushButton("浏览")
        browse_input_btn.clicked.connect(self.browse_compress_input)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.compress_input_path)
        h_layout.addWidget(browse_input_btn)
        file_layout.addLayout(h_layout)
        layout.addWidget(file_group)

        # MODIFIED: 改为显示完整输出路径
        output_group = QGroupBox("输出文件路径")
        output_layout = QVBoxLayout(output_group)
        self.compress_output_path = QLineEdit()  # MODIFIED: 初始为空，显示完整路径
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
        layout.addWidget(self.compress_progress)

        compress_btn = QPushButton("压缩PDF文件")
        compress_btn.clicked.connect(self.start_compress)
        layout.addWidget(compress_btn)
        self.compress_btn = compress_btn

    def setup_convert_tab(self):
        layout = QVBoxLayout(self.convert_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        title_label = QLabel("文件夹文件转换为PDF")
        title_label.setStyleSheet("font: bold 16px;")
        layout.addWidget(title_label)

        folder_group = QGroupBox("选择包含文件的文件夹")
        folder_layout = QVBoxLayout(folder_group)
        self.convert_folder_path = QLineEdit()
        browse_convert_folder_btn = QPushButton("浏览")
        browse_convert_folder_btn.clicked.connect(self.browse_convert_folder)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.convert_folder_path)
        h_layout.addWidget(browse_convert_folder_btn)
        folder_layout.addLayout(h_layout)
        layout.addWidget(folder_group)

        list_group = QGroupBox("文件列表 (支持图像、文本、PDF等)")
        list_layout = QVBoxLayout(list_group)
        self.convert_list_widget = QListWidget()
        self.convert_list_widget.setSelectionMode(QListWidget.ExtendedSelection)  # 支持多选
        list_layout.addWidget(self.convert_list_widget)

        btn_layout = QHBoxLayout()
        remove_convert_btn = QPushButton("移除选中")
        remove_convert_btn.clicked.connect(self.remove_convert_selected)
        clear_convert_btn = QPushButton("清除列表")
        clear_convert_btn.clicked.connect(self.clear_convert_list)
        btn_layout.addWidget(remove_convert_btn)
        btn_layout.addWidget(clear_convert_btn)
        list_layout.addLayout(btn_layout)
        layout.addWidget(list_group)

        output_group = QGroupBox("输出目录")
        output_layout = QVBoxLayout(output_group)
        self.convert_output_path = QLineEdit()
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
        layout.addWidget(self.convert_progress)

        convert_btn = QPushButton("开始转换")
        convert_btn.clicked.connect(self.start_convert)
        layout.addWidget(convert_btn)
        self.convert_btn = convert_btn

    # NEW: 设置拆分Tab
    def setup_split_tab(self):
        layout = QVBoxLayout(self.split_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        title_label = QLabel("PDF 文件拆分")
        title_label.setStyleSheet("font: bold 16px;")
        layout.addWidget(title_label)

        file_group = QGroupBox("选择要拆分的PDF文件")
        file_layout = QVBoxLayout(file_group)
        self.split_input_path = QLineEdit()
        browse_split_input_btn = QPushButton("浏览")
        browse_split_input_btn.clicked.connect(self.browse_split_input)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.split_input_path)
        h_layout.addWidget(browse_split_input_btn)
        file_layout.addLayout(h_layout)
        layout.addWidget(file_group)

        output_group = QGroupBox("输出目录")
        output_layout = QVBoxLayout(output_group)
        self.split_output_path = QLineEdit()
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
        ranges_layout.addWidget(self.page_ranges)
        layout.addWidget(ranges_group)

        self.split_progress = QProgressBar()
        self.split_progress.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.split_progress)

        split_btn = QPushButton("开始拆分")
        split_btn.clicked.connect(self.start_split)
        layout.addWidget(split_btn)
        self.split_btn = split_btn

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
            default_path = os.path.join(folder, "merged.pdf")
            self.output_name.setText(default_path)
            self.load_pdf_files()

    def browse_compress_input(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要压缩的PDF文件", "", "PDF files (*.pdf);;All files (*.*)")
        if file_path:
            self.compress_input_path.setText(file_path)
            directory, filename = os.path.split(file_path)
            name, ext = os.path.splitext(filename)
            # MODIFIED: 设置完整输出路径
            default_output_path = os.path.join(directory, f"{name}_compressed{ext}")
            self.compress_output_path.setText(default_output_path)
            self.compress_output_directory = directory

    def choose_save_location(self):
        default_file = os.path.join(self.output_directory or os.path.expanduser("~"), "merged.pdf")
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

    def load_pdf_files(self):
        self.list_widget.clear()
        folder = self.folder_path.text()
        if not os.path.isdir(folder):
            return

        pdf_files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
        pdf_files.sort()

        for pdf in pdf_files:
            self.list_widget.addItem(pdf)

        if pdf_files:
            self.status_label.setText(f"找到 {len(pdf_files)} 个PDF文件")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("未找到PDF文件")
            self.status_label.setStyleSheet("color: red;")

    def browse_convert_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含文件的文件夹")
        if folder:
            self.convert_folder_path.setText(folder)
            self.convert_output_directory = folder
            self.convert_output_path.setText(folder)
            self.load_convert_files()

    def load_convert_files(self):
        self.convert_list_widget.clear()
        folder = self.convert_folder_path.text()
        if not os.path.isdir(folder):
            return

        supported_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.txt', '.md')
        files = [f for f in os.listdir(folder) if f.lower().endswith(supported_ext)]
        files.sort()

        for file in files:
            self.convert_list_widget.addItem(file)

        if files:
            self.status_label.setText(f"找到 {len(files)} 个支持的文件")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("未找到支持的文件")
            self.status_label.setStyleSheet("color: red;")

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
        self.status_label.setText("列表已清除")
        self.status_label.setStyleSheet("color: blue;")

    def clear_convert_list(self):
        self.convert_list_widget.clear()
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

        if os.path.exists(output_path):
            reply = QMessageBox.question(self, "确认", "输出文件已存在，是否覆盖？", QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.merge_btn.setEnabled(False)
        self.merge_progress.setVisible(True)
        self.status_label.setText("正在合并PDF文件...")
        self.status_label.setStyleSheet("color: blue;")

        pdf_list = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        thread = MergeThread(output_path, self.folder_path.text(), pdf_list, self.compress_after_merge.isChecked())
        thread.status_update.connect(self.update_status)
        thread.finished.connect(self.merge_finished)
        thread.start()
        self.merge_thread = thread

    def start_convert(self):
        if self.convert_list_widget.count() == 0:
            QMessageBox.critical(self, "错误", "没有文件可转换")
            return

        if self.convert_output_directory is None:
            self.convert_output_directory = self.convert_folder_path.text()
            if not self.convert_output_directory:
                QMessageBox.critical(self, "错误", "请先选择文件夹或指定输出目录")
                return

        self.convert_btn.setEnabled(False)
        self.convert_progress.setVisible(True)
        self.status_label.setText("正在转换文件...")
        self.status_label.setStyleSheet("color: blue;")

        file_list = [self.convert_list_widget.item(i).text() for i in range(self.convert_list_widget.count())]
        thread = ConversionThread(self.convert_folder_path.text(), self.convert_output_directory, file_list, self.add_to_merge.isChecked())
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

        if self.split_output_directory is None:
            self.split_output_directory = os.path.dirname(input_path)
            if not self.split_output_directory:
                QMessageBox.critical(self, "错误", "无法确定输出目录")
                return

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

        if os.path.exists(output_path):
            reply = QMessageBox.question(self, "确认", "输出文件已存在，是否覆盖？", QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

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
                self.folder_path.setText(self.convert_output_directory)
                for pdf in converted_pdfs:
                    self.list_widget.addItem(pdf)
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