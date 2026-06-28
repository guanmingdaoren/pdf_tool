import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import duplicate_detector
from duplicate_detector import find_duplicate_images, find_duplicate_pdfs, render_pdf_preview_strip


def _make_temp_dir():
    parent = Path(__file__).resolve().parent / "tmp"
    parent.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=parent)


def _pattern_image(path, variant="base", size=(160, 160)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    if variant == "base":
        draw.rectangle((20, 20, 120, 80), fill="navy")
        draw.ellipse((65, 65, 145, 145), fill="gold")
        draw.line((0, 159, 159, 0), fill="crimson", width=5)
    else:
        draw.rectangle((15, 95, 145, 145), fill="forestgreen")
        draw.ellipse((15, 15, 80, 80), fill="purple")
        draw.line((0, 0, 159, 159), fill="black", width=5)
    image.save(path)


@unittest.skipUnless(duplicate_detector.imagehash is not None, "ImageHash is not installed")
class DuplicateImageTest(unittest.TestCase):
    def test_identical_images_are_detected(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            image_a = folder / "a.png"
            image_b = folder / "b.png"
            _pattern_image(image_a)
            image_b.write_bytes(image_a.read_bytes())

            report = find_duplicate_images(str(folder), threshold=6)

            self.assertEqual(len(report.results), 1)
            self.assertEqual(report.results[0].distance, 0)
            self.assertEqual(report.results[0].verdict, "文件完全相同")

    def test_resized_or_compressed_images_are_detected(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            image_a = folder / "source.png"
            image_b = folder / "compressed.jpg"
            _pattern_image(image_a)
            with Image.open(image_a) as image:
                image.resize((120, 120)).save(image_b, quality=55)

            report = find_duplicate_images(str(folder), threshold=8)

            self.assertEqual(len(report.results), 1)
            self.assertEqual(report.results[0].verdict, "视觉重复")

    def test_different_images_are_not_detected(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            _pattern_image(folder / "a.png", variant="base")
            _pattern_image(folder / "b.png", variant="other")

            report = find_duplicate_images(str(folder), threshold=6)

            self.assertEqual(report.results, [])


@unittest.skipUnless(
    duplicate_detector.imagehash is not None and duplicate_detector.fitz is not None,
    "ImageHash or PyMuPDF is not installed",
)
class DuplicatePdfTest(unittest.TestCase):
    def test_duplicate_pdf_pages_are_detected(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            image_path = folder / "page.png"
            _pattern_image(image_path)
            with Image.open(image_path) as image:
                image.save(folder / "a.pdf", "PDF")
                image.save(folder / "b.pdf", "PDF")

            report = find_duplicate_pdfs(str(folder), threshold=6)

            self.assertEqual(len(report.results), 1)
            self.assertEqual(report.results[0].page_a, 1)
            self.assertEqual(report.results[0].page_b, 1)
            self.assertEqual(report.results[0].verdict, "整份重复")

    def test_different_pdf_pages_are_not_detected(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            image_a = folder / "a.png"
            image_b = folder / "b.png"
            _pattern_image(image_a, variant="base")
            _pattern_image(image_b, variant="other")
            with Image.open(image_a) as image:
                image.save(folder / "a.pdf", "PDF")
            with Image.open(image_b) as image:
                image.save(folder / "b.pdf", "PDF")

            report = find_duplicate_pdfs(str(folder), threshold=6)

            self.assertEqual(report.results, [])

    def test_pdf_preview_strip_contains_multiple_pages(self):
        with _make_temp_dir() as tmp_dir:
            folder = Path(tmp_dir)
            image_a = folder / "page_a.png"
            image_b = folder / "page_b.png"
            pdf_path = folder / "multi_page.pdf"
            _pattern_image(image_a, variant="base")
            _pattern_image(image_b, variant="other")
            with Image.open(image_a) as first_page, Image.open(image_b) as second_page:
                first_page.save(pdf_path, "PDF", save_all=True, append_images=[second_page])

            preview = render_pdf_preview_strip(str(pdf_path), max_size=(220, 220))

            self.assertGreater(preview.height, preview.width)


if __name__ == "__main__":
    os.environ.setdefault("TEMP", str(Path(__file__).resolve().parent / "tmp"))
    os.environ.setdefault("TMP", str(Path(__file__).resolve().parent / "tmp"))
    unittest.main()
