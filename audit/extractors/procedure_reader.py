"""
Read a procedure document from disk and return extracted plain text.

Supported:
- PDF
- DOCX
- TXT / MD

PDF flow:
1. Try normal text extraction using PyMuPDF.
2. If very little text is extracted, assume scanned PDF.
3. Fall back to OCR using pdf2image + Tesseract.
"""

from __future__ import annotations

from pathlib import Path
import os

from dotenv import load_dotenv

from audit.schemas.procedure_schema import ProcedureDocument


load_dotenv()


OCR_THRESHOLD = 100


def _read_pdf(file_path: Path) -> tuple[str, list[str], str]:
    warnings: list[str] = []

    try:
        import fitz
    except ImportError:
        return (
            "",
            ["PyMuPDF is not installed. Install it before testing PDF extraction."],
            "pdf_text",
        )

    document = fitz.open(file_path)

    text = "\n".join(
        page.get_text("text")
        for page in document
    ).strip()

    if len(text) >= OCR_THRESHOLD:
        return text, warnings, "pdf_text"

    warnings.append(
        "Very little text extracted. Assuming scanned PDF and running OCR."
    )

    try:
        from pdf2image import convert_from_path
        import pytesseract

        poppler_path = os.getenv("POPPLER_PATH")

        images = convert_from_path(
            str(file_path),
            poppler_path=poppler_path
        )

        ocr_text = []

        for image in images:
            ocr_text.append(
                pytesseract.image_to_string(image)
            )

        text = "\n".join(ocr_text).strip()

        warnings.append(
            "Scanned PDF detected. OCR used."
        )

        return text, warnings, "ocr"

    except ImportError:
        warnings.append(
            "OCR dependencies missing. Install pdf2image and pytesseract."
        )

        return text, warnings, "pdf_text"

    except Exception as e:
        warnings.append(
            f"OCR failed: {e}"
        )

        return text, warnings, "pdf_text"


def _read_docx(file_path: Path) -> tuple[str, list[str]]:
    try:
        from docx import Document

    except ImportError:
        return "", [
            "python-docx is not installed."
        ]

    document = Document(str(file_path))

    text = "\n".join(
        paragraph.text
        for paragraph in document.paragraphs
    ).strip()


    return text, []


def _read_text(file_path: Path) -> tuple[str, list[str]]:
    for encoding in (
        "utf-8",
        "latin-1",
        "utf-16"
    ):
        try:
            return (
                file_path.read_text(
                    encoding=encoding
                ).strip(),
                []
            )

        except UnicodeDecodeError:
            continue

    return "", [
        "Could not decode the text file."
    ]


def read_procedure_file(file_path: str) -> ProcedureDocument:
    path = Path(file_path)

    suffix = path.suffix.lower()

    source = "pdf_text"

    if suffix == ".pdf":
        text, warnings, source = _read_pdf(path)

    elif suffix == ".docx":
        text, warnings = _read_docx(path)

    elif suffix in {".txt", ".md"}:
        text, warnings = _read_text(path)

    else:
        text, warnings = "", [
            f"Unsupported procedure format: {suffix or 'unknown'}"
        ]

    return ProcedureDocument(
        file_path=str(path),
        file_type=suffix.lstrip("."),
        text=text,
        warnings=warnings,
        source=source,
    )