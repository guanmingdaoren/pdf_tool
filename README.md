# PDF 文件处理工具

一个使用 PySide6 构建的本地桌面 PDF 工具。程序提供 PDF 合并、压缩、文件转 PDF、PDF 拆分和重复内容检测，并支持在各功能页中直接预览 PDF、图片和文本内容。

## 更新记录

更新记录按日期倒序维护。每次发布功能改进或修复时，应在本节顶部补充日期和用户可感知的变化。

### 2026-06-29：界面布局与预览体验优化

- 主界面改为 Finder 风格的浅色工作台，左侧导航和右侧内容区之间支持拖动调整宽度。
- 各功能页使用统一的左右工作区和纵向滚动外壳，窗口缩小时底部输出目录、选项和操作按钮仍可滚动访问。
- PDF、图片和文本预览区支持独立滚动，PDF 页面会按当前预览宽度适配，避免内容显示不全。
- 调整分组标题、输入框、按钮和预览卡片间距，改善中文标题被挤压的问题。
- 修复“转换后添加到 PDF 合并界面”会改坏原合并列表路径的问题；现在会保留原列表并追加转换结果。

### 2026-06-28：重复内容检测与本地打包

- 新增“重复检测”页签，支持图片重复和 PDF 页面级重复检测。
- 图片和 PDF 重复检测使用视觉相似度，默认阈值为 `6`，阈值越大越宽松。
- 重复检测结果以表格展示，支持选中结果后左右预览，并可打开对比窗口。
- 新增 `run.bat`，可一键启动程序。
- 新增 `build.bat`，可通过 PyInstaller 生成 Windows 本地 EXE 文件夹版。

### 2026-06-27：基础 PDF 工具能力

- 提供 PDF 合并、压缩、文件转换和 PDF 拆分入口。
- 支持加载当前目录或递归加载子目录中的文件。
- 输出文件遇到同名文件时会自动递增命名，降低覆盖风险。

## 核心能力

- PDF 合并：选择一个或多个 PDF，调整顺序后合并为一个文件。
- 合并后压缩：合并完成后可继续调用压缩流程生成压缩版 PDF。
- PDF 压缩：支持低质量、中等质量、高质量和最高质量选项，并可填写目标文件大小。
- 文件转换：支持将图片、文本、Markdown 和已有 PDF 输出为 PDF。
- 转换后追加：转换结果可追加到“PDF 合并”列表，且支持不同目录的 PDF 混合合并。
- PDF 拆分：支持逐页拆分，也支持指定页码范围拆分，例如 `2-10,12,15-20`。
- 重复检测：支持图片 vs 图片、PDF vs PDF 的视觉重复检测。
- 页面级结果：PDF 重复检测会展示具体页码，并标记“整份重复”或“部分重复”。
- 内容预览：合并、压缩、转换、拆分和重复检测页面均支持内容预览。
- 对比窗口：重复检测结果可打开左右对比窗口，直观看到重复内容。
- 安全输出：合并、压缩、转换、拆分生成文件时会尽量使用自动递增文件名，避免直接覆盖已有文件。
- 非破坏性重复检测：重复检测只展示结果，不会自动删除、移动或重命名文件。

## 运行

需要 Python 3.11 或更高版本。

首次运行前安装依赖：

```powershell
python -m pip install -r requirements.txt
```

然后双击 `run.bat`，或在 PowerShell 中运行：

```powershell
.\run.bat
```

也可以直接运行：

```powershell
python merge_compress_pdf.py
```

## 日常使用

1. 在左侧导航选择需要的功能：PDF 合并、PDF 压缩、文件转换、重复检测或 PDF 拆分。
2. 点击“浏览”选择输入文件或文件夹；需要包含子目录时点击“遍历子文件夹”。
3. 在文件列表中点击文件，右侧会显示 PDF、图片或文本预览。
4. 如果预览 PDF 较长，可在预览区内用鼠标滚轮上下查看。
5. 左侧导航栏和右侧内容区之间的分隔线可以左右拖动，用于调整工作区宽度。
6. 合并 PDF 时，可拖动列表项或使用“上移”“下移”调整顺序。
7. 文件转换完成后，如勾选“转换后添加到 PDF 合并界面”，转换出的 PDF 会追加到合并列表。
8. 重复检测完成后，选择结果行可查看左右预览，点击“对比”可打开更大的对比窗口。
9. 拆分 PDF 时，默认逐页拆分；如选择指定范围，请按 `2-10,12,15-20` 这样的格式输入页码。

## 依赖与外部工具

项目依赖保存在 `requirements.txt`：

- `PySide6`：桌面 GUI。
- `PyPDF2`：PDF 合并、读取和拆分。
- `Pillow`：图片读取和转换。
- `reportlab`：文本转 PDF。
- `PyMuPDF`：PDF 页面渲染和预览。
- `ImageHash`：图片与 PDF 页面视觉相似度检测。

压缩功能依赖 Ghostscript 命令行工具。程序会尝试查找 `gs`、`gswin64c` 或 `gswin32c`。如果压缩时报 Ghostscript 相关错误，请先安装 Ghostscript，并确保命令可在系统环境变量中找到。

PyMuPDF 需要注意其 AGPL/商业授权约束；如果将本工具用于商业分发，请先确认授权合规。

## 重复检测说明

- 图片模式会扫描常见图片格式，并使用感知哈希判断视觉相似度。
- PDF 模式会将每个 PDF 页面渲染为图片后再计算视觉指纹。
- 默认相似阈值为 `6`；阈值越小越严格，阈值越大越宽松。
- PDF 检测只比较不同 PDF 文件之间的页面，不检测同一个 PDF 内部重复页。
- 当前版本不做图片和 PDF 的交叉重复检测。
- 打不开的图片、加密 PDF、空 PDF 或损坏文件会被跳过，不会让程序崩溃。

## 项目结构

- `merge_compress_pdf.py`：主程序入口和 PySide6 界面。
- `duplicate_detector.py`：重复内容检测、PDF 渲染和视觉哈希逻辑。
- `pdf_file_utils.py`：文件收集、唯一输出路径和 Ghostscript 命令解析工具。
- `run.bat`：本地启动脚本。
- `build.bat`：Windows EXE 文件夹版打包脚本。
- `requirements.txt`：运行依赖。
- `test_*.py`：单元测试和 UI 结构回归测试。

## 测试

标准库测试无需额外安装测试框架。建议在 PowerShell 中运行：

```powershell
$env:QT_QPA_PLATFORM="offscreen"
$env:TEMP=(Resolve-Path .).Path
$env:TMP=(Resolve-Path .).Path
python -m unittest discover -v
```

也可以只运行某个测试文件：

```powershell
python -m unittest test_ui_layout.py -v
python -m unittest test_duplicate_detector.py -v
python -m unittest test_pdf_file_utils.py -v
```

## 打包 Windows 文件夹版

打包前安装运行依赖和 PyInstaller：

```powershell
python -m pip install -r requirements.txt pyinstaller
```

然后双击 `build.bat`，或在 PowerShell 中运行：

```powershell
.\build.bat
```

打包完成后程序位于：

```powershell
.\dist\PDFTool\PDFTool.exe
```

发布时请复制整个 `dist\PDFTool\` 文件夹，不要只复制单独的 EXE。`_internal` 等依赖目录是程序运行所需内容。

## 注意事项

- 本工具是本地桌面程序，不会上传或联网处理文件。
- 对重要 PDF 执行合并、压缩、转换或拆分前，建议保留原始文件备份。
- 重复检测结果只是视觉相似判断，阈值过大时可能出现误报。
- 如果 PDF 加密、损坏或内容非常复杂，预览和重复检测可能失败或耗时较长。
- 如果只需要运行程序，优先使用 `run.bat`；如果需要分发给没有 Python 环境的电脑，再使用 `build.bat` 打包。
