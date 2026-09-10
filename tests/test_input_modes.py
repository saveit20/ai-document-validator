"""How the document reaches the model: plain text, layout text, or the PDF itself plus our text."""

import base64
from types import SimpleNamespace

import pytest
from fpdf import FPDF
from helpers import FakeTransport, llm_reply

from validator.config import ConfigError, load_settings
from validator.ingest import document_from_bytes, document_from_text
from validator.llm import LLMExtractor
from validator.prompts import OUTPUT_SCHEMA, PROMPT_VERSION
from validator.transport import AnthropicTransport, LLMRequest


def _two_column_pdf() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for y, left, right in [(20, "SELLER", "CLIENT"), (27, "Acme Tools Ltd", "Northwind Ltd")]:
        pdf.text(15, y, left)
        pdf.text(120, y, right)
    pdf.text(15, 40, "Total")
    pdf.text(150, 40, "1,200.00 EUR")
    return bytes(pdf.output())


class _Capture(FakeTransport):
    def complete(self, request: LLMRequest):
        self.request = request
        return super().complete(request)


def test_layout_text_keeps_a_label_and_its_value_on_one_line() -> None:
    document = document_from_bytes(_two_column_pdf(), "application/pdf", pdf_text="layout")
    assert any("Total" in line and "1,200.00" in line for line in document.text.splitlines())
    assert "    " not in document.text


def test_pdf_document_keeps_its_original_bytes() -> None:
    data = _two_column_pdf()
    assert document_from_bytes(data, "application/pdf").data == data
    assert document_from_text("Invoice").data is None


def test_pdf_input_sends_the_pdf_and_our_text() -> None:
    data = _two_column_pdf()
    transport = _Capture(llm_reply())
    LLMExtractor(transport, "claude-haiku-4-5-20251001", input_mode="pdf").extract(
        document_from_bytes(data, "application/pdf")
    )
    assert transport.request.pdf == data
    assert "<document>" in transport.request.user
    assert "PDF" in transport.request.user


@pytest.mark.parametrize(
    ("input_mode", "document"),
    [
        ("text", document_from_bytes(_two_column_pdf(), "application/pdf")),
        ("pdf", document_from_text("Invoice INV-1")),
    ],
)
def test_no_pdf_is_sent_in_text_mode_or_for_text_documents(input_mode, document) -> None:
    transport = _Capture(llm_reply())
    LLMExtractor(transport, "claude-haiku-4-5-20251001", input_mode=input_mode).extract(document)
    assert transport.request.pdf is None
    assert "PDF" not in transport.request.user


def _request(pdf: bytes | None = None) -> LLMRequest:
    return LLMRequest(
        model="m",
        system="s",
        user="u",
        schema=OUTPUT_SCHEMA,
        prompt_version=PROMPT_VERSION,
        pdf=pdf,
    )


def test_an_attached_pdf_changes_the_recording_key() -> None:
    assert _request().cache_key() != _request(b"%PDF-1.4").cache_key()
    assert _request(b"%PDF-1.4").cache_key() != _request(b"%PDF-1.5").cache_key()


def test_transport_sends_the_pdf_as_a_document_block_before_the_text() -> None:
    class Messages:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                stop_reason="end_turn",
                model="m",
                content=[SimpleNamespace(type="text", text="{}")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    messages = Messages()
    AnthropicTransport(api_key="unused", client=SimpleNamespace(messages=messages)).complete(
        _request(b"%PDF-1.4 x")
    )
    document, text = messages.kwargs["messages"][0]["content"]
    assert document["type"] == "document"
    assert document["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": base64.b64encode(b"%PDF-1.4 x").decode("ascii"),
    }
    assert text == {"type": "text", "text": "u"}


def test_default_input_sends_the_pdf_with_plain_text() -> None:
    settings = load_settings({})
    assert (settings.pdf_text, settings.llm_input) == ("plain", "pdf")


def test_settings_read_the_input_modes() -> None:
    settings = load_settings({"PDF_TEXT": "layout", "LLM_INPUT": "pdf"})
    assert (settings.pdf_text, settings.llm_input) == ("layout", "pdf")
    with pytest.raises(ConfigError):
        load_settings({"LLM_INPUT": "image"})
    with pytest.raises(ConfigError):
        load_settings({"PDF_TEXT": "ocr"})
