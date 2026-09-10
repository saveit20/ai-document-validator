"""Generate held-out evaluation batch A (layout and structure) of supplier invoices.

Writes eight ``hA_XX_<slug>.pdf`` files plus their ``.expected.json`` labels into
the directory containing this script, then verifies that every non-null label
value can be found (in its printed form) in the pypdf text layer.

Run:  python generate_batch_a.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfReader

OUT_DIR = Path(__file__).resolve().parent
FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
CREATION_DATE = datetime(2026, 6, 30, 9, 0, 0, tzinfo=UTC)
REFERENCE_DATE = "2026-06-30"

log = logging.getLogger("generate_batch_a")

CENT = Decimal("0.01")


def q(value: Decimal | str | int) -> Decimal:
    """Round to cents, half up."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _group(value: Decimal, thousands: str, decimal: str) -> str:
    sign = "-" if value < 0 else ""
    integer, frac = f"{abs(q(value)):.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}{thousands.join(groups)}{decimal}{frac}"


def eu(value: Decimal) -> str:
    """1.234,56"""
    return _group(value, ".", ",")


def en(value: Decimal) -> str:
    """1,234.56"""
    return _group(value, ",", ".")


def fr(value: Decimal) -> str:
    """1 234,56"""
    return _group(value, " ", ",")


class Invoice(FPDF):
    """FPDF with a Unicode font, fixed metadata and optional repeating header/footer."""

    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self.add_font("Arial", fname=FONT_REGULAR)
        self.add_font("Arial", style="B", fname=FONT_BOLD)
        self.set_creation_date(CREATION_DATE)
        self.set_title(title)
        self.set_author("holdout batch A")
        self.set_auto_page_break(False)
        self.set_margins(15, 15, 15)
        self.header_fn = None
        self.footer_fn = None

    def header(self) -> None:
        if self.header_fn:
            self.header_fn(self)

    def footer(self) -> None:
        if self.footer_fn:
            self.footer_fn(self)

    def font(self, size: float, bold: bool = False) -> None:
        self.set_font("Arial", "B" if bold else "", size)

    def text_at(
        self,
        x: float,
        y: float,
        text: str,
        size: float = 9,
        bold: bool = False,
        w: float = 0,
        align: str = "L",
    ) -> None:
        self.font(size, bold)
        self.set_xy(x, y)
        self.cell(w, 4.5, text, align=align)

    def table(
        self,
        x: float,
        y: float,
        widths: list[float],
        header: list[str],
        rows: list[list[str]],
        aligns: str,
        row_h: float = 6.0,
        size: float = 8.5,
    ) -> float:
        """Draw a bordered table and return the y coordinate below it."""
        self.set_xy(x, y)
        self.font(size, True)
        self.set_fill_color(230, 233, 238)
        for w, h in zip(widths, header, strict=False):
            self.cell(w, row_h, h, border=1, fill=True, align="C")
        y += row_h
        self.font(size)
        for row in rows:
            self.set_xy(x, y)
            for w, text, a in zip(widths, row, aligns, strict=False):
                self.cell(w, row_h, text, border=1, align=a)
            y += row_h
        return y


@dataclass
class Case:
    slug: str
    tags: list[str]
    notes: str
    expected: dict
    printed: dict[str, str]
    pdf: Invoice
    config: dict | None = None
    extra_checks: list[str] = field(default_factory=list)


def line_rows(items: list[tuple[str, str, Decimal, Decimal]], fmt, suffix: str = ""):
    """Return (table rows, net sum) for (code, description, qty, unit price) items."""
    rows, total = [], Decimal(0)
    for code, desc, qty, price in items:
        amount = q(qty * price)
        total += amount
        qty_txt = f"{qty.normalize():f}"
        rows.append([code, desc, qty_txt, fmt(price) + suffix, fmt(amount) + suffix])
    return rows, q(total)


NORTHWIND_ES = [
    "Northwind Construction S.L.",
    "Calle de Alcalá 214, 3º B",
    "28028 Madrid",
    "España",
]


def case_01() -> Case:
    """Seller and buyer blocks printed side by side, row by row."""
    pdf = Invoice("Factura FV-2026/0417")
    pdf.add_page()
    pdf.text_at(15, 14, "FACTURA", 20, True)
    pdf.text_at(130, 16, "Nº Factura: FV-2026/0417", 10, True)
    pdf.text_at(130, 21, "Fecha de emisión: 12/05/2026", 9)
    pdf.text_at(130, 26, "Fecha de entrega: 08/05/2026", 9)
    pdf.set_draw_color(40, 70, 120)
    pdf.line(15, 34, 195, 34)

    left = [
        "EMISOR",
        "Hormigones y Áridos del Sur S.L.",
        "CIF: B-41234567",
        "Polígono Industrial La Isla, Parcela 17",
        "41703 Dos Hermanas (Sevilla)",
        "Tel. 954 123 456 · admin@haridosur.es",
    ]
    right = [
        "CLIENTE",
        "Northwind Construction S.L.",
        "NIF: ESB12345678",
        "Calle de Alcalá 214, 3º B",
        "28028 Madrid",
        "Obra: Residencial Los Olivos, Getafe",
    ]
    y = 38
    for i, (l_txt, r_txt) in enumerate(zip(left, right, strict=False)):
        bold = i in (0, 1)
        pdf.text_at(15, y, l_txt, 9 if i else 7.5, bold)
        pdf.text_at(110, y, r_txt, 9 if i else 7.5, bold)
        y += 5

    items = [
        ("HA-25", "Hormigón HA-25/B/20/IIa (m³)", Decimal("42"), Decimal("78.50")),
        ("AR-04", "Arena lavada 0/4 (t)", Decimal("18.5"), Decimal("16.20")),
        ("GR-12", "Grava 6/12 (t)", Decimal("22"), Decimal("17.80")),
        ("BOM-1", "Servicio de bombeo, jornada", Decimal("2"), Decimal("310.00")),
        ("TRP", "Transporte camión hormigonera", Decimal("6"), Decimal("45.00")),
    ]
    rows, base = line_rows(items, eu)
    y = pdf.table(
        15,
        74,
        [22, 88, 20, 25, 25],
        ["Código", "Descripción", "Cant.", "Precio", "Importe"],
        rows,
        "LLRRR",
    )
    vat = q(base * Decimal("0.21"))
    total = base + vat
    y += 6
    for label, value, bold in [
        ("Base imponible", eu(base) + " €", False),
        ("IVA 21%", eu(vat) + " €", False),
        ("TOTAL FACTURA", eu(total) + " €", True),
    ]:
        pdf.text_at(120, y, label, 9.5, bold)
        pdf.text_at(160, y, value, 9.5, bold, w=35, align="R")
        y += 6
    y += 6
    pdf.text_at(15, y, "Forma de pago: transferencia bancaria a 30 días fecha factura.", 8.5)
    pdf.text_at(15, y + 5, "IBAN: ES91 2100 0418 4502 0005 1332 · BIC: CAIXESBBXXX", 8.5)
    pdf.text_at(
        15,
        282,
        "Hormigones y Áridos del Sur S.L. · Inscrita en el Registro Mercantil de Sevilla, "
        "Tomo 5120, Folio 88, Hoja SE-81234",
        6.5,
    )
    return Case(
        slug="two_column_header",
        tags=["two_column_header"],
        notes="Seller and buyer blocks share the same rows, so the text layer interleaves both "
        "legal names and both tax ids on the same lines.",
        expected=dict(
            supplier_name="Hormigones y Áridos del Sur S.L.",
            invoice_number="FV-2026/0417",
            invoice_date="2026-05-12",
            total_amount=f"{total:.2f}",
            currency="EUR",
            tax_id="B41234567",
            subtotal_amount=f"{base:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        printed=dict(
            supplier_name="Hormigones y Áridos del Sur S.L.",
            invoice_number="FV-2026/0417",
            invoice_date="12/05/2026",
            total_amount=eu(total),
            currency="€",
            tax_id="B-41234567",
            subtotal_amount=eu(base),
            tax_amount=eu(vat),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
        ),
        pdf=pdf,
    )


def case_02() -> Case:
    """Brand name in the header; legal entity only in the footer."""
    pdf = Invoice("Brightline invoice INV-58213")
    pdf.add_page()
    pdf.set_fill_color(255, 196, 0)
    pdf.rect(0, 0, 210, 30, style="F")
    pdf.text_at(15, 9, "BRIGHTLINE", 24, True)
    pdf.text_at(15, 19, "Scaffolding · Access · Edge Protection", 9)
    pdf.text_at(135, 9, "Unit 4, Riverside Trade Park", 8)
    pdf.text_at(135, 13, "Barking, London IG11 0DS", 8)
    pdf.text_at(135, 17, "accounts@brightline-access.co.uk", 8)
    pdf.text_at(135, 21, "+44 20 3987 1122", 8)

    pdf.text_at(15, 40, "TAX INVOICE", 14, True)
    pdf.text_at(15, 50, "Invoice to:", 8, True)
    for i, line in enumerate(
        [
            "Northwind Construction S.L. (UK Branch)",
            "Site office, 22 Wharf Road",
            "London N1 7GR",
            "Customer VAT: ESB12345678",
        ]
    ):
        pdf.text_at(15, 55 + i * 4.5, line, 9, i == 0)
    meta = [
        ("Invoice No.", "INV-58213"),
        ("Invoice date", "14 June 2026"),
        ("Account", "NWC-UK-003"),
        ("PO reference", "PO-7781/LDN"),
        ("Hire period", "01/06/2026 - 28/06/2026"),
        ("Payment due", "14 July 2026"),
    ]
    for i, (k, v) in enumerate(meta):
        pdf.text_at(120, 50 + i * 5, k, 8.5, True)
        pdf.text_at(155, 50 + i * 5, v, 8.5)

    items = [
        ("SC-TUB", "Tube & fitting scaffold hire, 4 weeks (m²)", Decimal("210"), Decimal("6.40")),
        ("SC-ERE", "Erection and dismantle labour", Decimal("1"), Decimal("1850.00")),
        ("EP-BAR", "Edge protection barrier panels, weekly", Decimal("4"), Decimal("95.00")),
        ("INS-01", "Scaffold inspection & handover certificate", Decimal("4"), Decimal("65.00")),
    ]
    rows, net = line_rows(items, en)
    y = pdf.table(
        15,
        88,
        [22, 93, 18, 24, 23],
        ["Code", "Description", "Qty", "Rate £", "Net £"],
        rows,
        "LLRRR",
    )
    vat = q(net * Decimal("0.20"))
    total = net + vat
    y += 6
    for label, value, bold in [
        ("Net amount", "£" + en(net), False),
        ("VAT @ 20%", "£" + en(vat), False),
        ("Amount due", "£" + en(total), True),
    ]:
        pdf.text_at(125, y, label, 9.5, bold)
        pdf.text_at(160, y, value, 9.5, bold, w=35, align="R")
        y += 6
    y += 8
    pdf.text_at(15, y, "Please pay by BACS quoting the invoice number.", 8.5)
    pdf.text_at(
        15, y + 5, "Sort code 20-45-77 · Account 43218765 · IBAN GB33 BARC 2045 7743 2187 65", 8.5
    )
    pdf.text_at(
        15,
        y + 10,
        "Late payments may attract interest under the Late Payment of Commercial "
        "Debts (Interest) Act 1998.",
        8,
    )

    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, 278, 195, 278)
    pdf.text_at(
        15,
        280,
        "Brightline is a trading name of Brightline Access Solutions Ltd. Registered in "
        "England & Wales, company no. 08812345.",
        6.5,
    )
    pdf.text_at(
        15,
        284,
        "Registered office: 3rd Floor, 12 Eastcheap, London EC3M 1AE. VAT Reg. No. GB 284 5512 90.",
        6.5,
    )
    return Case(
        slug="supplier_in_footer",
        tags=["supplier_in_footer"],
        notes="The prominent header only says BRIGHTLINE; the legal name and VAT number live in a "
        "6.5pt footer next to a company number that looks like a tax id.",
        expected=dict(
            supplier_name="Brightline Access Solutions Ltd",
            invoice_number="INV-58213",
            invoice_date="2026-06-14",
            total_amount=f"{total:.2f}",
            currency="GBP",
            tax_id="GB284551290",
            subtotal_amount=f"{net:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        printed=dict(
            supplier_name="Brightline Access Solutions Ltd",
            invoice_number="INV-58213",
            invoice_date="14 June 2026",
            total_amount=en(total),
            currency="£",
            tax_id="GB 284 5512 90",
            subtotal_amount=en(net),
            tax_amount=en(vat),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
        ),
        pdf=pdf,
    )


def case_03() -> Case:
    """Two pages; items on page 1 with a carried-forward line, totals on page 2."""
    pdf = Invoice("Rechnung RE-2026-00318")

    def header(p: Invoice) -> None:
        p.text_at(15, 12, "Stahlbau Keller GmbH", 13, True)
        p.text_at(15, 18, "Industriestraße 41 · 70565 Stuttgart · Deutschland", 8)
        p.text_at(130, 12, "Rechnung / Invoice", 11, True)
        p.text_at(130, 18, "Rechnungs-Nr.: RE-2026-00318", 8.5)
        p.set_draw_color(120, 120, 120)
        p.line(15, 25, 195, 25)

    def footer(p: Invoice) -> None:
        p.text_at(
            15,
            281,
            "Stahlbau Keller GmbH · Amtsgericht Stuttgart HRB 734512 · "
            "USt-IdNr.: DE 812 345 678 · Geschäftsführer: M. Keller",
            6.5,
        )
        p.text_at(170, 285, f"Seite {p.page_no()} von 2", 7, w=25, align="R")

    pdf.header_fn, pdf.footer_fn = header, footer
    pdf.add_page()
    pdf.text_at(15, 29, "Northwind Construction S.L.", 9, True)
    pdf.text_at(15, 33.5, "Calle de Alcalá 214, 3º B, 28028 Madrid, Spanien", 8.5)
    pdf.text_at(15, 38, "USt-IdNr. Kunde / Customer VAT: ESB12345678", 8.5)
    pdf.text_at(130, 29, "Rechnungsdatum: 15.03.2026", 8.5)
    pdf.text_at(130, 33.5, "Lieferdatum: 10.03.2026", 8.5)
    pdf.text_at(130, 38, "Kunden-Nr.: 40017", 8.5)

    profiles = [
        "HEA 200",
        "HEA 240",
        "HEB 160",
        "IPE 220",
        "IPE 300",
        "UPN 140",
        "RHS 120x80x5",
        "SHS 100x100x6",
        "L 80x8",
        "Flachstahl 60x10",
    ]
    items = []
    for i in range(34):
        prof = profiles[i % len(profiles)]
        length = [6, 8, 10, 12][i % 4]
        qty = Decimal(2 + (i * 7) % 11)
        price = q(Decimal(38) + Decimal(i * 13 % 97) + Decimal("0.25") * (i % 4))
        items.append(
            (f"{1000 + i * 10}", f"{prof}, S355JR, L={length} m, feuerverzinkt", qty, price)
        )
    rows, net = line_rows(items, eu)
    y = pdf.table(
        15,
        45,
        [16, 96, 14, 27, 27],
        ["Pos.", "Bezeichnung / Description", "Menge", "EP EUR", "GP EUR"],
        rows,
        "LLRRR",
        row_h=6.3,
        size=8,
    )
    pdf.text_at(110, y + 2, "Übertrag / Carried forward:", 8.5, True)
    pdf.text_at(160, y + 2, eu(net), 8.5, True, w=35, align="R")

    pdf.add_page()
    pdf.text_at(15, 32, "Fortsetzung Rechnung RE-2026-00318 vom 15.03.2026", 9)
    pdf.text_at(110, 42, "Übertrag", 9)
    pdf.text_at(160, 42, eu(net), 9, w=35, align="R")
    freight = Decimal("480.00")
    pdf.text_at(110, 48, "Fracht / Freight Stuttgart - Madrid", 9)
    pdf.text_at(160, 48, eu(freight), 9, w=35, align="R")
    net_total = net + freight
    vat = q(net_total * Decimal("0.19"))
    total = net_total + vat
    pdf.line(110, 55, 195, 55)
    lines = [
        ("Nettobetrag / Net total", eu(net_total) + " EUR", False),
        ("zzgl. 19 % MwSt. / VAT", eu(vat) + " EUR", False),
        ("Rechnungsbetrag / Total", eu(total) + " EUR", True),
    ]
    for i, (label, value, bold) in enumerate(lines):
        pdf.text_at(110, 58 + i * 6, label, 9.5, bold)
        pdf.text_at(160, 58 + i * 6, value, 9.5, bold, w=35, align="R")
    pdf.text_at(15, 90, "Zahlbar innerhalb von 30 Tagen ohne Abzug bis 14.04.2026.", 8.5)
    pdf.text_at(
        15,
        95,
        "Bankverbindung: Landesbank Baden-Württemberg · IBAN DE89 6005 0101 0002 1345 67 · "
        "BIC SOLADEST600",
        8.5,
    )
    return Case(
        slug="multi_page",
        tags=["multi_page"],
        notes="Totals sit on page 2 behind a carried-forward figure on page 1 and a freight line; "
        "the issue date (15.03.2026) is older than the 90-day window.",
        expected=dict(
            supplier_name="Stahlbau Keller GmbH",
            invoice_number="RE-2026-00318",
            invoice_date="2026-03-15",
            total_amount=f"{total:.2f}",
            currency="EUR",
            tax_id="DE812345678",
            subtotal_amount=f"{net_total:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
            verdict="FAIL",
        ),
        printed=dict(
            supplier_name="Stahlbau Keller GmbH",
            invoice_number="RE-2026-00318",
            invoice_date="15.03.2026",
            total_amount=eu(total),
            currency="EUR",
            tax_id="DE 812 345 678",
            subtotal_amount=eu(net_total),
            tax_amount=eu(vat),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
        ),
        pdf=pdf,
    )


def case_04() -> Case:
    """Totals block as a two-column table drawn column by column."""
    pdf = Invoice("Invoice 2026-NL-0912")
    pdf.add_page()
    pdf.text_at(15, 14, "Van der Berg Bouwmaterialen B.V.", 15, True)
    pdf.text_at(15, 21, "Havenstraat 88, 3024 AB Rotterdam, Nederland", 8.5)
    pdf.text_at(15, 25.5, "KvK 24123456 · BTW NL812345678B01", 8.5)
    pdf.text_at(150, 14, "INVOICE", 16, True, w=45, align="R")

    pdf.text_at(15, 38, "Bill to", 8, True)
    for i, line in enumerate(
        [
            "Northwind Construction S.L.",
            "Calle de Alcalá 214, 3º B",
            "28028 Madrid, Spain",
            "VAT ES B12345678",
        ]
    ):
        pdf.text_at(15, 43 + i * 4.5, line, 9, i == 0)
    for i, (k, v) in enumerate(
        [
            ("Invoice number", "2026-NL-0912"),
            ("Date", "03-06-2026"),
            ("Order", "SO-55410"),
            ("Terms", "Net 45 days"),
            ("Currency", "USD"),
        ]
    ):
        pdf.text_at(120, 38 + i * 5, k, 8.5, True)
        pdf.text_at(155, 38 + i * 5, v, 8.5)

    items = [
        ("GK-125", "Gypsum board 12.5 mm, 1200x2600", Decimal("320"), Decimal("7.85")),
        ("MW-100", "Mineral wool insulation 100 mm (m²)", Decimal("450"), Decimal("4.60")),
        ("CW-75", "Metal stud CW 75, 3000 mm", Decimal("600"), Decimal("2.35")),
        ("UW-75", "Metal track UW 75, 4000 mm", Decimal("180"), Decimal("2.90")),
        ("SCR-25", "Drywall screws 3.5x25, box 1000", Decimal("24"), Decimal("11.40")),
    ]
    rows, subtotal = line_rows(items, en)
    y = pdf.table(
        15,
        70,
        [22, 90, 18, 25, 25],
        ["Item", "Description", "Qty", "Unit $", "Amount $"],
        rows,
        "LLRRR",
    )
    vat = Decimal("0.00")
    total = subtotal + vat
    labels = ["Subtotal", "VAT 0% (intra-EU reverse charge)", "Freight", "Total amount due (USD)"]
    amounts = ["$ " + en(subtotal), "$ " + en(vat), "included", "$ " + en(total)]
    x_label, x_amount, top = 105, 165, y + 8
    pdf.set_draw_color(0, 0, 0)
    for i, label in enumerate(labels):
        pdf.font(9, i == len(labels) - 1)
        pdf.set_xy(x_label, top + i * 7)
        pdf.cell(60, 7, label, border=1)
    for i, amount in enumerate(amounts):
        pdf.font(9, i == len(amounts) - 1)
        pdf.set_xy(x_amount, top + i * 7)
        pdf.cell(30, 7, amount, border=1, align="R")
    y = top + 7 * len(labels) + 10
    pdf.text_at(
        15,
        y,
        "Reverse charge: VAT to be accounted for by the recipient (art. 196 Directive "
        "2006/112/EC).",
        8,
    )
    pdf.text_at(15, y + 5, "Payment: ING Bank N.V. · IBAN NL91 INGB 0001 2345 67 · BIC INGBNL2A", 8)
    return Case(
        slug="table_totals",
        tags=["table_totals"],
        notes="The totals table is drawn label column first and amount column second, so labels "
        "and amounts come out as separate runs; invoiced in USD, which is not allowed.",
        expected=dict(
            supplier_name="Van der Berg Bouwmaterialen B.V.",
            invoice_number="2026-NL-0912",
            invoice_date="2026-06-03",
            total_amount=f"{total:.2f}",
            currency="USD",
            tax_id="NL812345678B01",
            subtotal_amount=f"{subtotal:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
            verdict="FAIL",
        ),
        printed=dict(
            supplier_name="Van der Berg Bouwmaterialen B.V.",
            invoice_number="2026-NL-0912",
            invoice_date="03-06-2026",
            total_amount=en(total),
            currency="USD",
            tax_id="NL812345678B01",
            subtotal_amount=en(subtotal),
            tax_amount="$ " + en(vat),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ES B12345678",
        ),
        pdf=pdf,
    )


def case_05() -> Case:
    """Key fields as label-above-value boxes; no currency printed anywhere."""
    pdf = Invoice("Facture F-2026-1142")
    pdf.add_page()
    pdf.text_at(15, 14, "Menuiserie Dubois SARL", 15, True)
    pdf.text_at(15, 21, "12 rue des Artisans, 69007 Lyon, France", 8.5)
    pdf.text_at(15, 25.5, "SIRET 123 456 789 00021 · contact@menuiserie-dubois.fr", 8.5)
    pdf.text_at(140, 14, "FACTURE / INVOICE", 12, True, w=55, align="R")

    grid = [
        [
            ("N° facture / Invoice number", "F-2026-1142"),
            ("Date de facture / Invoice date", "22/04/2026"),
            ("Échéance / Due date", "22/05/2026"),
        ],
        [
            ("Client / Customer", "Northwind Construction S.L."),
            ("TVA client / Customer VAT", "ESB12345678"),
            ("Réf. chantier / Site", "Hotel Arenal, Palma"),
        ],
        [
            ("TVA fournisseur / Supplier VAT", "FR 45 123456789"),
            ("Bon de commande / PO", "NW-PO-2231"),
            ("Conditions / Terms", "30 jours fin de mois"),
        ],
    ]
    box_w, box_h, x0, y0 = 60, 14, 15, 36
    for r, row in enumerate(grid):
        y = y0 + r * box_h
        for c, (label, _) in enumerate(row):
            pdf.rect(x0 + c * box_w, y, box_w, box_h)
            pdf.text_at(x0 + c * box_w + 2, y + 1.5, label, 6.5)
        for c, (_, value) in enumerate(row):
            pdf.text_at(x0 + c * box_w + 2, y + 7, value, 9.5, True)

    items = [
        ("PF-90", "Bloc-porte coupe-feu EI30 90x204", Decimal("12"), Decimal("285.00")),
        ("PL-01", "Placard coulissant sur mesure", Decimal("6"), Decimal("410.00")),
        ("PS-22", "Plinthe chêne massif 22x90 (ml)", Decimal("140"), Decimal("6.50")),
        ("POSE", "Pose et ajustage, forfait", Decimal("1"), Decimal("1350.00")),
    ]
    rows, ht = line_rows(items, fr)
    y = pdf.table(
        15,
        82,
        [20, 95, 15, 25, 25],
        ["Réf.", "Désignation", "Qté", "P.U. HT", "Montant HT"],
        rows,
        "LLRRR",
    )
    tva = q(ht * Decimal("0.20"))
    ttc = ht + tva
    y += 6
    for label, value, bold in [
        ("Total HT", fr(ht), False),
        ("TVA 20 %", fr(tva), False),
        ("Total TTC", fr(ttc), True),
    ]:
        pdf.text_at(125, y, label, 9.5, bold)
        pdf.text_at(160, y, value, 9.5, bold, w=35, align="R")
        y += 6
    pdf.text_at(
        15,
        y + 8,
        "Règlement par virement : IBAN FR76 3000 6000 0112 3456 7890 189 · BIC AGRIFRPP",
        8,
    )
    pdf.text_at(
        15,
        y + 13,
        "Pénalités de retard : 3 fois le taux d'intérêt légal. Indemnité forfaitaire "
        "pour frais de recouvrement : 40.",
        7.5,
    )
    pdf.text_at(
        15,
        282,
        "Menuiserie Dubois SARL au capital de 20 000 · RCS Lyon 123 456 789 · TVA FR 45 123456789",
        6.5,
    )
    return Case(
        slug="label_value_split",
        tags=["label_value_split"],
        notes="Labels of three boxes are extracted on one line and their values on the next, so "
        "each value must be matched to a label by position; no currency symbol or code is printed.",
        expected=dict(
            supplier_name="Menuiserie Dubois SARL",
            invoice_number="F-2026-1142",
            invoice_date="2026-04-22",
            total_amount=f"{ttc:.2f}",
            currency=None,
            tax_id="FR45123456789",
            subtotal_amount=f"{ht:.2f}",
            tax_amount=f"{tva:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
            verdict="REVIEW",
        ),
        printed=dict(
            supplier_name="Menuiserie Dubois SARL",
            invoice_number="F-2026-1142",
            invoice_date="22/04/2026",
            total_amount=fr(ttc),
            tax_id="FR 45 123456789",
            subtotal_amount=fr(ht),
            tax_amount=fr(tva),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="ESB12345678",
        ),
        pdf=pdf,
        extra_checks=["€", "EUR"],
    )


def case_06() -> Case:
    """Several 'Total ...' lines before the real grand total."""
    pdf = Invoice("Invoice FT-0588/26")
    pdf.add_page()
    pdf.text_at(15, 14, "Ferramenta Lombarda S.r.l.", 15, True)
    pdf.text_at(15, 21, "Via dell'Industria 9, 20090 Segrate (MI), Italia", 8.5)
    pdf.text_at(15, 25.5, "P.IVA / VAT IT 01234567890 · REA MI-1650321", 8.5)
    pdf.text_at(130, 14, "INVOICE No. FT-0588/26", 11, True)
    pdf.text_at(130, 20, "Invoice date: 09/06/2026", 8.5)
    pdf.text_at(130, 24.5, "DDT / Delivery note: 412 of 05/06/2026", 8.5)

    pdf.text_at(15, 36, "Customer:", 8, True)
    for i, line in enumerate(NORTHWIND_ES[:3] + ["CIF: B12345678"]):
        pdf.text_at(15, 41 + i * 4.5, line, 9, i == 0)
    pdf.text_at(120, 36, "Ship to:", 8, True)
    for i, line in enumerate(
        [
            "Northwind Construction S.L. - Obra Delta",
            "Av. de la Riera 5",
            "08960 Sant Just Desvern (Barcelona)",
        ]
    ):
        pdf.text_at(120, 41 + i * 4.5, line, 9)

    items = [  # code, desc, qty, unit price, unit weight kg
        (
            "TRP-18",
            "Cordless rotary hammer 18V SDS-plus",
            Decimal("2"),
            Decimal("289.00"),
            Decimal("12"),
        ),
        ("MOL-230", "Angle grinder 230 mm 2400W", Decimal("3"), Decimal("149.00"), Decimal("14")),
        (
            "CAV-M16",
            "Chemical anchor kit M16, box of 50",
            Decimal("4"),
            Decimal("118.50"),
            Decimal("22"),
        ),
        ("SCA-3", "Aluminium ladder 3x9 rungs", Decimal("2"), Decimal("186.00"), Decimal("36")),
        ("GEN-3K", "Site generator 3 kVA", Decimal("1"), Decimal("423.00"), Decimal("80")),
        ("FAR-LED", "LED floodlight 50W with tripod", Decimal("2"), Decimal("41.00"), Decimal("7")),
    ]
    rows, taxable = line_rows([i[:4] for i in items], eu)
    for row, item in zip(rows, items, strict=False):
        row.insert(3, f"{item[2] * item[4]:f}")
    y = pdf.table(
        15,
        64,
        [22, 78, 14, 20, 23, 23],
        ["Code", "Description", "Qty", "Weight kg", "Unit €", "Amount €"],
        rows,
        "LLRRRR",
    )
    n_items = sum(i[2] for i in items)
    weight = sum(i[2] * i[4] for i in items)
    vat = q(taxable * Decimal("0.22"))
    total = taxable + vat
    y += 6
    pdf.text_at(15, y, f"Total items: {n_items}", 9)
    pdf.text_at(15, y + 5, f"Total weight: {weight} kg", 9)
    pdf.text_at(15, y + 10, "Packages: 5 · Carrier: BRT S.p.A. · Incoterm DAP", 9)
    for i, (label, value, bold) in enumerate(
        [
            ("Total excl. VAT", eu(taxable) + " €", False),
            ("VAT 22%", eu(vat) + " €", False),
            ("Total incl. VAT", eu(total) + " €", True),
        ]
    ):
        pdf.text_at(120, y + i * 6, label, 9.5, bold)
        pdf.text_at(160, y + i * 6, value, 9.5, bold, w=35, align="R")
    y += 26
    pdf.text_at(
        15,
        y,
        "Payment: bank transfer 60 days end of month · IBAN IT60 X054 2811 1010 0000 0123 456",
        8,
    )
    pdf.text_at(
        15,
        282,
        "Ferramenta Lombarda S.r.l. · Capitale sociale € 50.000 i.v. · "
        "Registro Imprese di Milano 01234567890",
        6.5,
    )
    return Case(
        slug="total_distractors",
        tags=["total_distractors"],
        notes="Four lines start with 'Total' (items, weight, excl. VAT, incl. VAT) and the footer "
        "prints share capital in euros; only 'Total incl. VAT' is the invoice total.",
        expected=dict(
            supplier_name="Ferramenta Lombarda S.r.l.",
            invoice_number="FT-0588/26",
            invoice_date="2026-06-09",
            total_amount=f"{total:.2f}",
            currency="EUR",
            tax_id="IT01234567890",
            subtotal_amount=f"{taxable:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="B12345678",
            verdict="PASS",
        ),
        printed=dict(
            supplier_name="Ferramenta Lombarda S.r.l.",
            invoice_number="FT-0588/26",
            invoice_date="09/06/2026",
            total_amount=eu(total),
            currency="€",
            tax_id="IT 01234567890",
            subtotal_amount=eu(taxable),
            tax_amount=eu(vat),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="B12345678",
        ),
        pdf=pdf,
        extra_checks=["Total items: 14", "Total weight: 320 kg"],
    )


def case_07() -> Case:
    """Two VAT rates, each with its own base and tax line; no total-tax line."""
    pdf = Invoice("Factura A-26/1093")
    pdf.add_page()
    pdf.text_at(15, 14, "Suministros y Obras Levante S.A.", 15, True)
    pdf.text_at(15, 21, "Avda. del Puerto 301, 46023 Valencia · CIF A46123456", 8.5)
    pdf.text_at(140, 14, "FACTURA", 14, True, w=55, align="R")
    pdf.text_at(140, 21, "Serie A · Número A-26/1093", 8.5, w=55, align="R")
    pdf.text_at(140, 25.5, "Fecha: 28/05/2026", 8.5, w=55, align="R")

    pdf.rect(15, 33, 90, 26)
    for i, line in enumerate(
        [
            "Cliente",
            "Northwind Construction S.L.",
            "CIF B12345678",
            "Calle de Alcalá 214, 3º B, 28028 Madrid",
        ]
    ):
        pdf.text_at(17, 35 + i * 5, line, 7.5 if i == 0 else 9, i == 1)
    pdf.text_at(115, 35, "Obra: Rehabilitación viviendas C/ Sueca 14", 8.5)
    pdf.text_at(115, 40, "Albarán(es): 26-3391, 26-3402", 8.5)
    pdf.text_at(115, 45, "Vencimiento: 27/06/2026", 8.5)

    items = [  # code, desc, qty, price, vat rate
        (
            "CER-3060",
            "Azulejo cerámico 30x60 (m²) - rehabilitación vivienda",
            Decimal("160"),
            Decimal("11.25"),
            10,
        ),
        ("MOR-C2", "Adhesivo cementoso C2TE, saco 25 kg", Decimal("48"), Decimal("9.50"), 10),
        ("MO-ALB", "Mano de obra alicatado (m²)", Decimal("160"), Decimal("12.00"), 10),
        ("SAN-01", "Plato de ducha resina 80x120", Decimal("6"), Decimal("210.00"), 21),
        ("GRI-TE", "Grifería termostática ducha", Decimal("6"), Decimal("135.00"), 21),
        ("ALQ-AND", "Alquiler andamio (semanas)", Decimal("4"), Decimal("80.00"), 21),
    ]
    rows, bases = [], {10: Decimal(0), 21: Decimal(0)}
    for code, desc, qty, price, rate in items:
        amount = q(qty * price)
        bases[rate] += amount
        rows.append([code, desc, f"{qty}", eu(price), f"{rate}%", eu(amount)])
    y = pdf.table(
        15,
        66,
        [20, 92, 14, 18, 14, 22],
        ["Código", "Concepto", "Cant.", "Precio", "IVA", "Importe"],
        rows,
        "LLRRRR",
        size=8,
    )
    taxes = {r: q(b * Decimal(r) / 100) for r, b in bases.items()}
    base_total = bases[10] + bases[21]
    tax_total = taxes[10] + taxes[21]
    total = base_total + tax_total
    y = pdf.table(
        15,
        y + 8,
        [40, 30, 30, 30],
        ["Tipo IVA", "Base imponible", "Cuota IVA", "Total"],
        [[f"IVA {r}%", eu(bases[r]), eu(taxes[r]), eu(bases[r] + taxes[r])] for r in (10, 21)],
        "LRRR",
    )
    pdf.text_at(
        15,
        y + 3,
        "IVA reducido 10% aplicado a obras de renovación de vivienda (art. 91.Uno.2.10º LIVA).",
        7.5,
    )
    pdf.text_at(120, y + 10, "Suma bases imponibles", 9.5)
    pdf.text_at(160, y + 10, eu(base_total) + " €", 9.5, w=35, align="R")
    pdf.text_at(120, y + 16, "TOTAL FACTURA", 10.5, True)
    pdf.text_at(160, y + 16, eu(total) + " €", 10.5, True, w=35, align="R")
    pdf.text_at(
        15, y + 28, "Pago: recibo domiciliado a 30 días · IBAN ES76 0081 0216 7100 0123 4567", 8
    )
    pdf.text_at(
        15,
        282,
        "Suministros y Obras Levante S.A. · R.M. Valencia, Tomo 8812, Libro 6101, "
        "Folio 45, Hoja V-120334",
        6.5,
    )
    return Case(
        slug="multi_vat",
        tags=["multi_vat"],
        notes="Two VAT rates with per-rate base, tax and total columns; there is no single total-tax "
        "line, so tax_amount must be summed and per-rate totals look like candidate totals.",
        expected=dict(
            supplier_name="Suministros y Obras Levante S.A.",
            invoice_number="A-26/1093",
            invoice_date="2026-05-28",
            total_amount=f"{total:.2f}",
            currency="EUR",
            tax_id="A46123456",
            subtotal_amount=f"{base_total:.2f}",
            tax_amount=f"{tax_total:.2f}",
            customer_name="Northwind Construction S.L.",
            customer_tax_id="B12345678",
            verdict="PASS",
        ),
        printed=dict(
            supplier_name="Suministros y Obras Levante S.A.",
            invoice_number="A-26/1093",
            invoice_date="28/05/2026",
            total_amount=eu(total),
            currency="€",
            tax_id="A46123456",
            subtotal_amount=eu(base_total),
            tax_10=eu(taxes[10]),
            tax_21=eu(taxes[21]),
            customer_name="Northwind Construction S.L.",
            customer_tax_id="B12345678",
        ),
        pdf=pdf,
    )


def case_08() -> Case:
    """Gross, discount, taxable base, VAT, total; billed to a different group company."""
    pdf = Invoice("Rechnung 2026-4471")
    pdf.add_page()
    pdf.text_at(15, 14, "Kabel & Leitung Wien GmbH", 15, True)
    pdf.text_at(15, 21, "Laxenburger Straße 180, 1100 Wien, Österreich", 8.5)
    pdf.text_at(15, 25.5, "UID-Nr. ATU63456789 · FN 245678 k · Handelsgericht Wien", 8.5)
    pdf.text_at(140, 14, "RECHNUNG / INVOICE", 12, True, w=55, align="R")

    pdf.text_at(15, 36, "Rechnungsempfänger / Bill to", 7.5, True)
    for i, line in enumerate(
        [
            "Northwind Logistics S.L.",
            "Carrer de la Marina 19",
            "08005 Barcelona, Spanien",
            "UID Empfänger: ESB87654321",
        ]
    ):
        pdf.text_at(15, 41 + i * 4.5, line, 9, i == 0)
    for i, (k, v) in enumerate(
        [
            ("Rechnungsnummer", "2026-4471"),
            ("Rechnungsdatum", "17.06.2026"),
            ("Leistungszeitraum", "Mai 2026"),
            ("Ihre Bestellung", "NWL-3310"),
            ("Zahlungsziel", "14 Tage netto"),
        ]
    ):
        pdf.text_at(120, 36 + i * 5, k, 8.5, True)
        pdf.text_at(158, 36 + i * 5, v, 8.5)

    items = [
        ("NYY-5x16", "Kabel NYY-J 5x16 mm² (m)", Decimal("400"), Decimal("7.20")),
        ("H07-3x2.5", "Leitung H07RN-F 3G2,5 (m)", Decimal("500"), Decimal("1.85")),
        ("VT-24", "Verteilerschrank IP65, 24 TE", Decimal("4"), Decimal("186.00")),
        ("KR-50", "Kabelrinne 50x100, verzinkt (m)", Decimal("120"), Decimal("5.60")),
    ]
    rows, gross = line_rows(items, eu)
    y = pdf.table(
        15,
        68,
        [24, 86, 18, 26, 26],
        ["Art.-Nr.", "Bezeichnung", "Menge", "EP €", "GP €"],
        rows,
        "LLRRR",
    )
    discount = q(gross * Decimal("0.12"))
    base = gross - discount
    vat = q(base * Decimal("0.20"))
    total = base + vat
    y += 6
    lines = [
        ("Warenwert brutto / Gross amount", eu(gross), False),
        ("abzgl. 12 % Projektrabatt / Discount", "-" + eu(discount), False),
        ("Netto / Taxable base", eu(base), True),
        ("USt. 20 % / VAT", eu(vat), False),
        ("Gesamtbetrag / Total EUR", eu(total), True),
    ]
    for label, value, bold in lines:
        pdf.text_at(105, y, label, 9.5, bold)
        pdf.text_at(165, y, value, 9.5, bold, w=30, align="R")
        y += 6
    pdf.text_at(15, y + 6, "Skonto: 2 % bei Zahlung innerhalb von 7 Tagen.", 8.5)
    pdf.text_at(15, y + 11, "Erste Bank · IBAN AT61 2011 1822 2121 9800 · BIC GIBAATWWXXX", 8.5)
    config = {
        "document_type": "SUPPLIER_INVOICE",
        "max_age_days": 90,
        "allowed_currencies": ["EUR", "GBP"],
        "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
        "expected_customer_tax_id": "ESB12345678",
    }
    return Case(
        slug="discount",
        tags=["discount"],
        notes="Gross, discount and taxable base are three net-looking figures (the discount is "
        "negative and a 2% early-payment Skonto is mentioned), and the invoice is addressed to a "
        "sister company whose tax id differs from the expected customer.",
        expected=dict(
            supplier_name="Kabel & Leitung Wien GmbH",
            invoice_number="2026-4471",
            invoice_date="2026-06-17",
            total_amount=f"{total:.2f}",
            currency="EUR",
            tax_id="ATU63456789",
            subtotal_amount=f"{base:.2f}",
            tax_amount=f"{vat:.2f}",
            customer_name="Northwind Logistics S.L.",
            customer_tax_id="ESB87654321",
            verdict="FAIL",
        ),
        printed=dict(
            supplier_name="Kabel & Leitung Wien GmbH",
            invoice_number="2026-4471",
            invoice_date="17.06.2026",
            total_amount=eu(total),
            currency="EUR",
            tax_id="ATU63456789",
            subtotal_amount=eu(base),
            tax_amount=eu(vat),
            customer_name="Northwind Logistics S.L.",
            customer_tax_id="ESB87654321",
        ),
        pdf=pdf,
        config=config,
    )


CASES = [case_01, case_02, case_03, case_04, case_05, case_06, case_07, case_08]


def extracted_text(path: Path) -> str:
    """Concatenate pypdf text of all pages, with whitespace collapsed."""
    text = "\n".join(page.extract_text() for page in PdfReader(path).pages)
    return re.sub(r"\s+", " ", text)


def verify(path: Path, case: Case) -> list[str]:
    """Return a list of problems: printed values missing from the text layer."""
    text = extracted_text(path)
    problems = [
        f"{k}: {v!r} not found"
        for k, v in case.printed.items()
        if re.sub(r"\s+", " ", v) not in text
    ]
    if case.expected["currency"] is None:
        problems += [f"unexpected currency marker {m!r}" for m in case.extra_checks if m in text]
    else:
        problems += [f"{m!r} not found" for m in case.extra_checks if m not in text]
    exp = case.expected
    if (
        exp["subtotal_amount"]
        and exp["tax_amount"]
        and Decimal(exp["subtotal_amount"]) + Decimal(exp["tax_amount"])
        != Decimal(exp["total_amount"])
    ):
        problems.append("subtotal + tax != total")
    return problems


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    log.setLevel(logging.INFO)
    failures = 0
    for number, build in enumerate(CASES, start=1):
        case = build()
        stem = f"hA_{number:02d}_{case.slug}"
        pdf_path = OUT_DIR / f"{stem}.pdf"
        case.pdf.output(str(pdf_path))
        label = {
            "document": pdf_path.name,
            "reference_date": REFERENCE_DATE,
            "config": case.config,
            "difficulty": case.tags,
            "expected": case.expected,
            "notes": case.notes,
        }
        (OUT_DIR / f"{stem}.expected.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        problems = verify(pdf_path, case)
        failures += bool(problems)
        log.info("%s  %s  %s", stem, case.expected["verdict"], problems if problems else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
