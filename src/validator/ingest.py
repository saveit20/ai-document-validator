"""Turn uploaded bytes or text into a Document with per-page text."""

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from validator.normalize import squash

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


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
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")


def document_from_text(text: str) -> Document:
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLarge(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    if not text.strip():
        raise UnreadableDocument("document text is empty")
    return Document(pages=(_clean(text),), media_type="text/plain")


def document_from_bytes(
    data: bytes, media_type: str | None, filename: str | None = None
) -> Document:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLarge(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    kind = (media_type or "").split(";")[0].strip().lower()
    if kind == "application/pdf" or data.startswith(b"%PDF-"):
        return _from_pdf(data)
    if kind in ("", "application/octet-stream") or kind.startswith("text/"):
        try:
            return document_from_text(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise UnreadableDocument("text document is not valid UTF-8") from exc
    raise UnsupportedMediaType(f"unsupported media type '{kind}' for '{filename or 'document'}'")


def _from_pdf(data: bytes) -> Document:
    try:
        reader = PdfReader(BytesIO(data))
        pages = tuple(_clean(page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many exception types on malformed input
        raise UnreadableDocument("could not parse the PDF") from exc
    if not any(page.strip() for page in pages):
        raise UnreadableDocument(
            "PDF has no extractable text layer; scanned PDFs need OCR, which is out of scope"
        )
    return Document(pages=pages, media_type="application/pdf")
