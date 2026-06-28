import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QCheckBox, QScrollArea, QSplitter
except ImportError:  # pragma: no cover
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed")
class MainWindowLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_uses_sidebar_navigation(self):
        from merge_compress_pdf import PDFMergerApp

        window = PDFMergerApp()

        self.assertTrue(hasattr(window, "nav_list"))
        self.assertFalse(window.tab_widget.tabBar().isVisible())
        self.assertEqual(window.nav_list.count(), window.tab_widget.count())

        window.nav_list.setCurrentRow(2)
        self.assertEqual(window.tab_widget.currentIndex(), 2)

    def test_sidebar_can_be_resized_with_splitter(self):
        from merge_compress_pdf import PDFMergerApp

        window = PDFMergerApp()

        self.assertTrue(hasattr(window, "shell_splitter"))
        self.assertIsInstance(window.shell_splitter, QSplitter)
        self.assertEqual(window.shell_splitter.widget(0), window.sidebar)
        self.assertEqual(window.shell_splitter.widget(1), window.tab_widget)
        self.assertGreater(window.sidebar.maximumWidth(), window.sidebar.minimumWidth())
        self.assertGreaterEqual(window.shell_splitter.handleWidth(), 6)

    def test_preview_enable_checkboxes_are_removed(self):
        from merge_compress_pdf import PDFMergerApp

        window = PDFMergerApp()
        preview_checkboxes = [
            checkbox.text()
            for checkbox in window.findChildren(QCheckBox)
            if "内容预览" in checkbox.text()
        ]

        self.assertEqual(preview_checkboxes, [])

    def test_merge_list_items_store_absolute_paths(self):
        from merge_compress_pdf import FileEntry, MergeThread, PDFMergerApp

        window = PDFMergerApp()
        first_path = os.path.abspath(os.path.join("fixtures", "first", "same.pdf"))
        second_path = os.path.abspath(os.path.join("fixtures", "second", "same.pdf"))

        window.add_merge_file(FileEntry.from_path(first_path))
        window.add_merge_file(FileEntry.from_path(second_path))

        self.assertEqual(window.list_widget.item(0).text(), "same.pdf")
        self.assertEqual(window.list_widget.item(1).text(), "same.pdf")
        self.assertEqual(window.get_merge_pdf_paths(), [first_path, second_path])
        self.assertEqual(window.list_widget.item(0).toolTip(), first_path)
        self.assertEqual(window.list_widget.item(1).toolTip(), second_path)

        thread = MergeThread(os.path.abspath("merged.pdf"), [first_path, second_path], False)
        self.assertEqual(thread.pdf_paths, [first_path, second_path])

    def test_convert_finished_appends_without_rebasing_existing_merge_files(self):
        from merge_compress_pdf import FileEntry, PDFMergerApp

        window = PDFMergerApp()
        original_path = os.path.abspath(os.path.join("fixtures", "original", "old.pdf"))
        converted_path = os.path.abspath(os.path.join("fixtures", "converted", "new.pdf"))
        window.add_merge_file(FileEntry.from_path(original_path))
        window.folder_path.setText(os.path.dirname(original_path))
        window.convert_output_directory = os.path.dirname(converted_path)
        window.add_to_merge.setChecked(True)

        with patch("merge_compress_pdf.QMessageBox.information"):
            window.convert_finished("转换完成，共处理 1 个文件", [converted_path])

        self.assertEqual(window.get_merge_pdf_paths(), [original_path, converted_path])
        self.assertEqual(window.folder_path.text(), os.path.dirname(original_path))

    def test_each_workspace_page_has_vertical_scroll_shell(self):
        from merge_compress_pdf import PDFMergerApp

        window = PDFMergerApp()

        for index in range(window.tab_widget.count()):
            page = window.tab_widget.widget(index)
            page_scrolls = [
                scroll
                for scroll in page.findChildren(QScrollArea)
                if scroll.objectName() == "pageScrollArea"
            ]

            self.assertEqual(len(page_scrolls), 1)
            self.assertTrue(page_scrolls[0].widgetResizable())

    def test_preview_panel_sizes_pages_to_viewport_width(self):
        from merge_compress_pdf import FilePreviewPanel

        panel = FilePreviewPanel("预览")
        panel.resize(640, 480)
        self.app.processEvents()

        max_width, max_height = panel.preview_image_max_size()

        self.assertLessEqual(max_width, panel.viewport().width() - 56)
        self.assertGreaterEqual(max_width, 360)
        self.assertGreater(max_height, max_width)

    def test_group_box_titles_have_breathing_room(self):
        from merge_compress_pdf import PDFMergerApp

        window = PDFMergerApp()
        style = window.styleSheet()

        self.assertIn("margin-top: 20px", style)
        self.assertIn("padding: 22px 16px 16px 16px", style)
        self.assertIn("subcontrol-origin: margin", style)
        self.assertIn("top: 2px", style)


if __name__ == "__main__":
    unittest.main()
