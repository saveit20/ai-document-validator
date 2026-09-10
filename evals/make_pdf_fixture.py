"""Regenerate tests/fixtures/inv_10_pdf.pdf from inv_01's text. Development-only (needs fpdf2)."""

from pathlib import Path

from fpdf import FPDF

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    text = (FIXTURES_DIR / "inv_01_clean_en.txt").read_text(encoding="utf-8")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=9)
    for line in text.splitlines():
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    (FIXTURES_DIR / "inv_10_pdf.pdf").write_bytes(bytes(pdf.output()))


if __name__ == "__main__":
    main()
