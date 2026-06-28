import hashlib
import os
from dataclasses import dataclass, field
from io import BytesIO
from itertools import combinations
from typing import Optional

from PIL import Image

from pdf_file_utils import collect_relative_files

try:
    import fitz
except ImportError:  # pragma: no cover - exercised through dependency checks
    fitz = None

try:
    import imagehash
except ImportError:  # pragma: no cover - exercised through dependency checks
    imagehash = None


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)


class MissingDependencyError(RuntimeError):
    pass


@dataclass
class DuplicateResult:
    kind: str
    file_a: str
    file_b: str
    display_a: str
    display_b: str
    page_a: Optional[int]
    page_b: Optional[int]
    distance: int
    verdict: str
    exact_match: bool = False


@dataclass
class DetectionReport:
    results: list[DuplicateResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    scanned_files: int = 0
    scanned_items: int = 0
    error: str = ""


@dataclass
class _ImageItem:
    path: str
    display: str
    file_hash: str
    perceptual_hash: object


@dataclass
class _PdfPageItem:
    path: str
    display: str
    file_hash: str
    page_number: int
    page_count: int
    perceptual_hash: object


def _require_imagehash():
    if imagehash is None:
        raise MissingDependencyError("缺少 ImageHash，请先运行: python -m pip install ImageHash")


def _require_fitz():
    if fitz is None:
        raise MissingDependencyError("缺少 PyMuPDF，请先运行: python -m pip install PyMuPDF")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_phash(path):
    _require_imagehash()
    with Image.open(path) as image:
        return imagehash.phash(image.convert("RGB"))


def _pdf_page_phash(page):
    _require_imagehash()
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    return imagehash.phash(image)


def find_duplicate_images(folder, recursive=False, threshold=6):
    _require_imagehash()
    threshold = int(threshold)
    report = DetectionReport()
    relative_files = collect_relative_files(folder, IMAGE_EXTENSIONS, recursive=recursive)
    report.scanned_files = len(relative_files)

    items = []
    for relative_path in relative_files:
        path = os.path.join(folder, relative_path)
        try:
            items.append(
                _ImageItem(
                    path=path,
                    display=relative_path,
                    file_hash=sha256_file(path),
                    perceptual_hash=_image_phash(path),
                )
            )
        except Exception as exc:
            report.skipped.append(f"{relative_path}: {exc}")

    report.scanned_items = len(items)
    seen_pairs = set()

    for item_a, item_b in combinations(items, 2):
        pair_key = tuple(sorted((item_a.path, item_b.path)))
        if pair_key in seen_pairs:
            continue

        exact_match = item_a.file_hash == item_b.file_hash
        distance = 0 if exact_match else item_a.perceptual_hash - item_b.perceptual_hash
        if exact_match or distance <= threshold:
            seen_pairs.add(pair_key)
            report.results.append(
                DuplicateResult(
                    kind="图片重复",
                    file_a=item_a.path,
                    file_b=item_b.path,
                    display_a=item_a.display,
                    display_b=item_b.display,
                    page_a=None,
                    page_b=None,
                    distance=int(distance),
                    verdict="文件完全相同" if exact_match else "视觉重复",
                    exact_match=exact_match,
                )
            )

    return report


def find_duplicate_pdfs(folder, recursive=False, threshold=6):
    _require_fitz()
    _require_imagehash()
    threshold = int(threshold)
    report = DetectionReport()
    relative_files = collect_relative_files(folder, PDF_EXTENSIONS, recursive=recursive)
    report.scanned_files = len(relative_files)

    pages_by_file = {}
    for relative_path in relative_files:
        path = os.path.join(folder, relative_path)
        try:
            file_hash = sha256_file(path)
            page_items = []
            with fitz.open(path) as document:
                if document.needs_pass:
                    raise ValueError("加密 PDF，无法读取")
                if document.page_count == 0:
                    raise ValueError("空 PDF")
                for page_index in range(document.page_count):
                    page_items.append(
                        _PdfPageItem(
                            path=path,
                            display=relative_path,
                            file_hash=file_hash,
                            page_number=page_index + 1,
                            page_count=document.page_count,
                            perceptual_hash=_pdf_page_phash(document.load_page(page_index)),
                        )
                    )
            pages_by_file[path] = page_items
        except Exception as exc:
            report.skipped.append(f"{relative_path}: {exc}")

    report.scanned_items = sum(len(pages) for pages in pages_by_file.values())

    for path_a, path_b in combinations(sorted(pages_by_file), 2):
        pages_a = pages_by_file[path_a]
        pages_b = pages_by_file[path_b]
        pair_results = []

        for page_a in pages_a:
            for page_b in pages_b:
                exact_file_match = page_a.file_hash == page_b.file_hash
                distance = 0 if exact_file_match and page_a.page_number == page_b.page_number else page_a.perceptual_hash - page_b.perceptual_hash
                if distance <= threshold:
                    pair_results.append(
                        DuplicateResult(
                            kind="PDF重复",
                            file_a=page_a.path,
                            file_b=page_b.path,
                            display_a=page_a.display,
                            display_b=page_b.display,
                            page_a=page_a.page_number,
                            page_b=page_b.page_number,
                            distance=int(distance),
                            verdict="部分重复",
                            exact_match=exact_file_match,
                        )
                    )

        if not pair_results:
            continue

        same_order_matches = {
            (result.page_a, result.page_b)
            for result in pair_results
            if result.page_a == result.page_b
        }
        full_document_match = (
            len(pages_a) == len(pages_b)
            and all((page.page_number, page.page_number) in same_order_matches for page in pages_a)
        )

        for result in pair_results:
            result.verdict = "整份重复" if full_document_match else "部分重复"
        report.results.extend(pair_results)

    return report


def render_preview_image(path, page_number=None, max_size=(900, 900)):
    if page_number is None:
        with Image.open(path) as image:
            preview = image.convert("RGB")
            preview.thumbnail(max_size)
            return preview.copy()

    _require_fitz()
    with fitz.open(path) as document:
        page_index = int(page_number) - 1
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError(f"PDF 页码超出范围: {page_number}")
        pixmap = document.load_page(page_index).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        preview = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
        preview.thumbnail(max_size)
        return preview.copy()


def render_pdf_preview_strip(path, max_size=(900, 1200), page_gap=24, background=(244, 247, 251)):
    _require_fitz()
    rendered_pages = []

    with fitz.open(path) as document:
        if document.needs_pass:
            raise ValueError("加密 PDF，无法预览")
        if document.page_count == 0:
            raise ValueError("空 PDF，无法预览")

        for page_index in range(document.page_count):
            pixmap = document.load_page(page_index).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            page_image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
            page_image.thumbnail(max_size)
            rendered_pages.append(page_image.copy())

    width = max(page.width for page in rendered_pages)
    height = sum(page.height for page in rendered_pages) + page_gap * (len(rendered_pages) + 1)
    strip = Image.new("RGB", (width + page_gap * 2, height), background)

    y = page_gap
    for page in rendered_pages:
        x = (strip.width - page.width) // 2
        strip.paste(page, (x, y))
        y += page.height + page_gap

    return strip
