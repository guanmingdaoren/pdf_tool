import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_file_utils import collect_relative_files, make_unique_path, resolve_ghostscript_command


class PdfFileUtilsTest(unittest.TestCase):
    def test_make_unique_path_adds_incrementing_suffix_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "merged.pdf").write_text("old", encoding="utf-8")
            (folder / "merged(1).pdf").write_text("old", encoding="utf-8")

            result = make_unique_path(str(folder / "merged.pdf"))

            self.assertEqual(result, str(folder / "merged(2).pdf"))

    def test_collect_relative_files_can_scan_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "a.pdf").write_text("pdf", encoding="utf-8")
            (folder / "sub").mkdir()
            (folder / "sub" / "b.PDF").write_text("pdf", encoding="utf-8")
            (folder / "sub" / "note.txt").write_text("txt", encoding="utf-8")

            result = collect_relative_files(str(folder), (".pdf",), recursive=True)

            self.assertEqual(result, ["a.pdf", str(Path("sub") / "b.PDF")])

    @patch("pdf_file_utils.shutil.which")
    def test_resolve_ghostscript_command_uses_windows_executable_when_gs_is_missing(self, which):
        def fake_which(command):
            if command == "gswin64c":
                return r"C:\Program Files\gs\bin\gswin64c.exe"
            return None

        which.side_effect = fake_which

        self.assertEqual(resolve_ghostscript_command(), r"C:\Program Files\gs\bin\gswin64c.exe")


if __name__ == "__main__":
    unittest.main()
