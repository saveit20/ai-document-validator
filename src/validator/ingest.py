"""Turn uploaded bytes or text into a Document with per-page text."""

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from pypdf import PdfReader

from validator.normalize import squash

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

PdfText = Literal["plain", "layout"]
_WIDE_GAP = re.compile(r"[ \t]{3,}")
_BLANK_LINES = re.compile(r"\n{3,}")


class DocumentError(Exception):
    status_code = 422
    code = "invalid_document"


class DocumentTooLarge(DocumentError):
    status_code = 413
    code = "document_too_large"


class UnsupportedMediaType(DocumentError):
    status_code = 415
    code = "unsupported_media_type"


class UnreadableDocument(DocumentError):
    status_code = 422
    code = "unreadable_document"


@dataclass(frozen=True)
class Document:
    pages: tuple[str, ...]
    media_type: str
    data: bytes | None = field(default=None, repr=False, compare=False)
    """The original PDF bytes, kept so the LLM can be sent the PDF itself."""

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def page_of(self, snippet: str | None) -> int | None:
        """1-based page containing `snippet` (whitespace- and case-insensitive), if any."""
        if not snippet:
            return None
        needle = squash(snippet)
        for number, page in enumerate(self.pages, start=1):
            if needle in squash(page):
                return number
        return None


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")


def document_from_text(text: str) -> Document:
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLarge(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    if not text.strip():
        raise UnreadableDocument("document text is empty")
    return Document(pages=(_clean(text),), media_type="text/plain")


def document_from_bytes(
    data: bytes, media_type: str | None, filename: str | None = None, pdf_text: PdfText = "plain"
) -> Document:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLarge(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    kind = (media_type or "").split(";")[0].strip().lower()
    if kind == "application/pdf" or data.startswith(b"%PDF-"):
        return _from_pdf(data, pdf_text)
    if kind in ("", "application/octet-stream") or kind.startswith("text/"):
        try:
            return document_from_text(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise UnreadableDocument("text document is not valid UTF-8") from exc
    raise UnsupportedMediaType(f"unsupported media type '{kind}' for '{filename or 'document'}'")


def _page_text(page, pdf_text: PdfText) -> str:
    """Plain text follows the PDF's drawing order, which can separate a label from its value.

    Layout text places each run by its position, so columns printed side by side stay on one line;
    the padding between them is cut to three spaces to save tokens.
    """
    if pdf_text == "plain":
        return page.extract_text() or ""
    lines = (page.extract_text(extraction_mode="layout") or "").splitlines()
    text = "\n".join(_WIDE_GAP.sub("   ", line).rstrip() for line in lines)
    return _BLANK_LINES.sub("\n\n", text).strip("\n")


def _from_pdf(data: bytes, pdf_text: PdfText) -> Document:
    try:
        reader = PdfReader(BytesIO(data))
        pages = tuple(_clean(_page_text(page, pdf_text)) for page in reader.pages)
    except Exception as exc:  # pypdf raises many exception types on malformed input
        raise UnreadableDocument("could not parse the PDF") from exc
    if not any(page.strip() for page in pages):
        raise UnreadableDocument(
            "PDF has no extractable text layer; scanned PDFs need OCR, which is out of scope"
        )
    return Document(pages=pages, media_type="application/pdf", data=data)
