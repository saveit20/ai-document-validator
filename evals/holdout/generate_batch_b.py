"""Generate held-out evaluation batch B: language, format and semantic-trap invoices.

Writes eight supplier-invoice PDFs (hB_01 .. hB_08) and their expected-value
labels into this script's directory. Output is deterministic: fixed creation
date, fixed content, no randomness.

Run:  python generate_batch_b.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

OUT_DIR = Path(__file__).resolve().parent
FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
CREATION_DATE = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
REFERENCE_DATE = "2026-06-30"

NORTHWIND = "Northwind Construction S.L."


@dataclass
class Invoice:
    """Everything needed to render one invoice and its label file."""

    slug: str
    difficulty: list[str]
    title: str
    supplier_lines: list[str]
    meta: list[tuple[str, str]]
    customer_heading: str
    customer_lines: list[str]
    columns: list[tuple[str, float, str]]
    rows: list[list[str]]
    totals: list[tuple[str, str]]
    footer_lines: list[str]
    expected: dict
    notes: str
    intro_lines: list[str] = field(default_factory=list)
    after_totals: list[str] = field(default_factory=list)
    config: dict | None = None


class InvoicePDF(FPDF):
    def __init__(self, footer_lines: list[str]):
        super().__init__(format="A4")
        self._footer_lines = footer_lines
        self.add_font("Arial", fname=FONT_REGULAR)
        self.add_font("Arial", style="B", fname=FONT_BOLD)
        self.set_creation_date(CREATION_DATE)
        self.set_creator("Batch B generator")
        self.set_auto_page_break(auto=True, margin=30)

    def footer(self) -> None:
        self.set_y(-26)
        self.set_draw_color(160, 160, 160)
        self.line(15, self.get_y(), 195, self.get_y())
        self.set_font("Arial", size=7)
        self.set_text_color(90, 90, 90)
        for line in self._footer_lines:
            self.cell(0, 3.6, line, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)


def render(inv: Invoice) -> Path:
    pdf = InvoicePDF(inv.footer_lines)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    pdf.set_font("Arial", "B", 13)
    pdf.cell(110, 7, inv.supplier_lines[0], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Arial", size=8.5)
    for line in inv.supplier_lines[1:]:
        pdf.cell(110, 4.2, line, new_x="LMARGIN", new_y="NEXT")
    supplier_bottom = pdf.get_y()

    pdf.set_xy(125, 15)
    pdf.set_font("Arial", "B", 15)
    pdf.cell(70, 8, inv.title, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Arial", size=8.5)
    for label, value in inv.meta:
        pdf.set_x(115)
        pdf.cell(42, 4.6, label, align="R")
        pdf.set_font("Arial", "B", 8.5)
        pdf.cell(38, 4.6, value, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Arial", size=8.5)
    y = max(supplier_bottom, pdf.get_y()) + 6

    pdf.set_xy(15, y)
    if inv.intro_lines:
        pdf.set_font("Arial", size=8.5)
        for line in inv.intro_lines:
            pdf.multi_cell(180, 4.2, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_fill_color(238, 238, 238)
    pdf.set_font("Arial", "B", 8)
    pdf.cell(90, 5, inv.customer_heading, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Arial", size=9)
    for line in inv.customer_lines:
        pdf.cell(90, 4.4, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("Arial", "B", 8)
    pdf.set_fill_color(40, 60, 90)
    pdf.set_text_color(255, 255, 255)
    for header, width, align in inv.columns:
        pdf.cell(width, 6, header, border=0, align=align, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", size=8.5)
    for i, row in enumerate(inv.rows):
        fill = i % 2 == 1
        pdf.set_fill_color(247, 247, 247)
        for (_, width, align), value in zip(inv.columns, row, strict=False):
            pdf.cell(width, 5.5, value, align=align, fill=fill)
        pdf.ln()
    pdf.ln(4)

    for label, value in inv.totals:
        bold = label.startswith("!")
        text = label.lstrip("!")
        pdf.set_x(105)
        pdf.set_font("Arial", "B" if bold else "", 9.5 if bold else 9)
        pdf.cell(55, 5.6, text, align="R")
        pdf.cell(35, 5.6, value, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("Arial", size=8.5)
    for line in inv.after_totals:
        pdf.multi_cell(180, 4.4, line, new_x="LMARGIN", new_y="NEXT")

    path = OUT_DIR / f"hB_{inv.slug}.pdf"
    pdf.output(str(path))
    return path


def write_label(inv: Invoice) -> Path:
    label = {
        "document": f"hB_{inv.slug}.pdf",
        "reference_date": REFERENCE_DATE,
        "config": inv.config,
        "difficulty": inv.difficulty,
        "expected": inv.expected,
        "notes": inv.notes,
    }
    path = OUT_DIR / f"hB_{inv.slug}.expected.json"
    path.write_text(json.dumps(label, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def expected(**values) -> dict:
    keys = [
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "total_amount",
        "currency",
        "tax_id",
        "subtotal_amount",
        "tax_amount",
        "customer_name",
        "customer_tax_id",
        "verdict",
    ]
    return {key: values.get(key) for key in keys}


DEFAULT_CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "allowed_currencies": ["EUR", "GBP"],
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}


def config_with(**overrides) -> dict:
    return {**DEFAULT_CONFIG, **overrides}


INVOICES = [
    Invoice(
        slug="01_facture_fr",
        difficulty=["language_fr"],
        title="FACTURE",
        supplier_lines=[
            "Durand Équipements SAS",
            "14, rue des Artisans – ZI Les Pradettes",
            "31100 Toulouse – France",
            "Tél. : +33 5 61 40 22 18 – compta@durand-equipements.fr",
            "SIRET 412 345 678 00027 – APE 4674B",
            "N° TVA intracommunautaire : FR 32 412 345 678",
        ],
        meta=[
            ("Facture n° :", "F2026-0512"),
            ("Date de facturation :", "12/05/2026"),
            ("Date de livraison :", "05/05/2026"),
            ("Date d'échéance :", "11/06/2026"),
            ("Réf. commande :", "NW-PO-7781"),
        ],
        customer_heading="FACTURÉ À",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3ª planta",
            "28028 Madrid – Espagne",
            "N° TVA : ESB12345678",
        ],
        columns=[
            ("Réf.", 22, "L"),
            ("Désignation", 83, "L"),
            ("Qté", 15, "R"),
            ("P.U. HT", 30, "R"),
            ("Montant HT", 30, "R"),
        ],
        rows=[
            ["DE-2231", "Disque diamant Ø 230 mm béton armé", "8", "48,60 €", "388,80 €"],
            ["DE-0918", "Perforateur SDS-Max 1 500 W", "1", "412,00 €", "412,00 €"],
            ["DE-7710", "Gants anti-coupure niveau 5 (lot de 12)", "4", "57,00 €", "228,00 €"],
        ],
        totals=[
            ("Total HT", "1 028,80 €"),
            ("TVA 20 %", "205,76 €"),
            ("!Total TTC", "1 234,56 €"),
        ],
        after_totals=[
            "Conditions de paiement : virement à 30 jours fin de mois. Pas d'escompte pour paiement anticipé.",
            "En cas de retard, pénalités au taux de 3 fois le taux d'intérêt légal et indemnité forfaitaire "
            "de 40 € pour frais de recouvrement (art. L441-10 C. com.).",
            "IBAN : FR76 3000 4000 1200 0012 3456 789 – BIC : BNPAFRPPXXX",
        ],
        footer_lines=[
            "Durand Équipements SAS au capital de 150 000 € – RCS Toulouse 412 345 678",
            "Siège social : 14, rue des Artisans, 31100 Toulouse",
        ],
        expected=expected(
            supplier_name="Durand Équipements SAS",
            invoice_number="F2026-0512",
            invoice_date="2026-05-12",
            total_amount="1234.56",
            currency="EUR",
            tax_id="FR32412345678",
            subtotal_amount="1028.80",
            tax_amount="205.76",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        notes="French labels, space thousands separator and decimal comma; three dates (invoice, delivery, due) must not be confused.",
    ),
    Invoice(
        slug="02_rechnung_de",
        difficulty=["language_de"],
        title="RECHNUNG",
        supplier_lines=[
            "Hoffmann Baustoffe GmbH",
            "Industriestraße 48",
            "70565 Stuttgart – Deutschland",
            "Tel. +49 711 7820 450 – rechnung@hoffmann-baustoffe.de",
            "Amtsgericht Stuttgart HRB 734219",
            "USt-IdNr.: DE 287 654 321",
        ],
        meta=[
            ("Rechnungsnummer:", "RE-2026-06-0317"),
            ("Rechnungsdatum:", "15.06.2026"),
            ("Lieferdatum:", "09.06.2026"),
            ("Kundennummer:", "K-40219"),
            ("Ihre Bestellung:", "NW-PO-7902 vom 02.06.2026"),
        ],
        customer_heading="RECHNUNGSEMPFÄNGER",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3ª planta",
            "28028 Madrid – Spanien",
            "USt-IdNr. des Leistungsempfängers: ES B12345678",
        ],
        columns=[
            ("Pos.", 12, "L"),
            ("Bezeichnung", 88, "L"),
            ("Menge", 20, "R"),
            ("Einzelpreis", 30, "R"),
            ("Gesamt", 30, "R"),
        ],
        rows=[
            ["1", "Transportbeton C25/30, m³", "42", "118,50 €", "4.977,00 €"],
            ["2", "Bewehrungsstahl BSt 500 S, t", "1,5", "1.290,00 €", "1.935,00 €"],
            ["3", "Pumpeneinsatz inkl. Anfahrt, Std.", "6", "250,50 €", "1.503,00 €"],
        ],
        totals=[
            ("Nettobetrag", "8.415,00 €"),
            ("MwSt. 19 %", "1.598,85 €"),
            ("!Gesamtbetrag", "10.013,85 €"),
        ],
        after_totals=[
            "Zahlbar innerhalb von 14 Tagen ohne Abzug bis zum 29.06.2026.",
            "Bankverbindung: Baden-Württembergische Bank – IBAN DE89 6005 0101 0002 1154 67 – BIC SOLADEST600",
            "Bitte geben Sie bei Zahlung die Rechnungsnummer an.",
        ],
        footer_lines=[
            "Hoffmann Baustoffe GmbH – Geschäftsführer: Markus Hoffmann, Dr. Ines Kaltenbach",
            "Sitz der Gesellschaft: Stuttgart – Registergericht Amtsgericht Stuttgart HRB 734219",
        ],
        config=config_with(expected_customer_tax_id="ESB12345678"),
        expected=expected(
            supplier_name="Hoffmann Baustoffe GmbH",
            invoice_number="RE-2026-06-0317",
            invoice_date="2026-06-15",
            total_amount="10013.85",
            currency="EUR",
            tax_id="DE287654321",
            subtotal_amount="8415.00",
            tax_amount="1598.85",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        notes="German labels, dotted dates next to an order date and delivery date, dot thousands separator; customer VAT printed as 'ES B12345678' must match the expected ESB12345678.",
    ),
    Invoice(
        slug="03_fattura_it",
        difficulty=["language_it_pt", "date_out_of_window"],
        title="FATTURA",
        supplier_lines=[
            "Edilforniture Lombarde S.r.l.",
            "Via Emilia Est 212",
            "20097 San Donato Milanese (MI) – Italia",
            "Tel. +39 02 5160 7734 – amministrazione@edilforniture.it",
            "Partita IVA: IT 01234567890 – C.F. 01234567890",
            "REA MI-1654321 – Cap. soc. € 100.000,00 i.v.",
        ],
        meta=[
            ("Fattura n.", "118/2026"),
            ("Data:", "18/03/2026"),
            ("DDT n. 402 del:", "12/03/2026"),
            ("Scadenza:", "17/04/2026"),
        ],
        customer_heading="SPETT.LE CLIENTE",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3ª planta",
            "28028 Madrid – Spagna",
            "P.IVA / VAT: ESB12345678",
        ],
        columns=[
            ("Codice", 22, "L"),
            ("Descrizione", 83, "L"),
            ("Q.tà", 15, "R"),
            ("Prezzo unit.", 30, "R"),
            ("Importo", 30, "R"),
        ],
        rows=[
            ["PN-330", "Pannelli isolanti XPS 60 mm (conf.)", "30", "42,50 €", "1.275,00 €"],
            ["MT-114", "Malta tecnica fibrorinforzata 25 kg", "150", "9,80 €", "1.470,00 €"],
            ["AC-901", "Tassello chimico M12 (conf. 50 pz)", "15", "47,00 €", "705,00 €"],
        ],
        totals=[
            ("Imponibile", "3.450,00 €"),
            ("IVA 22%", "759,00 €"),
            ("!Totale documento", "4.209,00 €"),
        ],
        after_totals=[
            "Modalità di pagamento: bonifico bancario 30 gg d.f.",
            "IBAN: IT60 X054 2811 1010 0000 0123 456 – Banca Popolare di Sondrio",
            "Operazione intracomunitaria: il cliente è tenuto all'integrazione dell'imposta ove previsto.",
        ],
        footer_lines=[
            "Edilforniture Lombarde S.r.l. – Sede legale Via Emilia Est 212, San Donato Milanese",
            "Documento emesso in formato elettronico – copia di cortesia",
        ],
        expected=expected(
            supplier_name="Edilforniture Lombarde S.r.l.",
            invoice_number="118/2026",
            invoice_date="2026-03-18",
            total_amount="4209.00",
            currency="EUR",
            tax_id="IT01234567890",
            subtotal_amount="3450.00",
            tax_amount="759.00",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="FAIL",
        ),
        notes="Italian labels ('Imponibile', 'Totale documento'); the issue date 18/03/2026 is before the 90-day window while the due date 17/04/2026 is inside it, so picking the wrong date flips FAIL to PASS.",
    ),
    Invoice(
        slug="04_us_invoice",
        difficulty=["us_date", "currency_not_allowed"],
        title="INVOICE",
        supplier_lines=[
            "Cascade Tool Supply, Inc.",
            "1840 Industrial Way S",
            "Seattle, WA 98134, USA",
            "Phone (206) 555-0182 · billing@cascadetoolsupply.com",
            "Federal Tax ID (EIN): 91-1234567",
        ],
        meta=[
            ("Invoice #:", "CTS-104552"),
            ("Invoice Date:", "06/05/2026"),
            ("Ship Date:", "06/08/2026"),
            ("Due Date:", "07/05/2026"),
            ("Terms:", "Net 30"),
        ],
        customer_heading="BILL TO",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3rd floor",
            "28028 Madrid, Spain",
            "VAT: ESB12345678",
        ],
        columns=[
            ("Item", 24, "L"),
            ("Description", 81, "L"),
            ("Qty", 15, "R"),
            ("Unit Price", 30, "R"),
            ("Amount", 30, "R"),
        ],
        rows=[
            ["LT-5520", "Rotary laser level kit, self-leveling", "3", "$1,089.00", "$3,267.00"],
            ["TR-0044", "Tripod, heavy duty aluminum", "3", "$215.50", "$646.50"],
            ["BT-1180", "Li-ion battery pack 18V 8.0Ah", "5", "$189.80", "$949.00"],
        ],
        totals=[
            ("Subtotal", "$4,862.50"),
            ("Sales Tax (export, 0%)", "$0.00"),
            ("!Total Due (USD)", "$4,862.50"),
        ],
        after_totals=[
            "Dates are shown in MM/DD/YYYY format. Export shipment – sales tax exempt.",
            "Remit by wire: JPMorgan Chase Bank, N.A. – ABA 021000021 – Acct 000123456789 – SWIFT CHASUS33",
            "Thank you for your business!",
        ],
        footer_lines=[
            "Cascade Tool Supply, Inc. · 1840 Industrial Way S · Seattle, WA 98134",
            "Questions about this invoice? Call (206) 555-0182",
        ],
        expected=expected(
            supplier_name="Cascade Tool Supply, Inc.",
            invoice_number="CTS-104552",
            invoice_date="2026-06-05",
            total_amount="4862.50",
            currency="USD",
            tax_id="911234567",
            subtotal_amount="4862.50",
            tax_amount="0.00",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="FAIL",
        ),
        notes="Month-first date 06/05/2026 means June 5 (read day-first it becomes May 6); the invoice is in USD, which is not an allowed currency.",
    ),
    Invoice(
        slug="05_ocr_noise",
        difficulty=["ocr_noise", "customer_tax_id_missing"],
        title="lNV0ICE",
        supplier_lines=[
            "Harlow & Finch Ltd",
            "Unit 7, Riverside lndustrial Estate",
            "Leeds LS1O 1AB – United Kingd om",
            "Te1: +44 113 496 0O72",
            "VAT Reg N0: GB 294 7731 08",
            "C0mpany N0. 08812345",
        ],
        meta=[
            ("lnvoice N0.", "HF-26-00731"),
            ("Dat e:", "22/05/2026"),
            ("Y0ur ref:", "NW-P0-7815"),
            ("Acc0unt:", "N0RTHW-01"),
        ],
        customer_heading="lNV0ICE T0",
        customer_lines=[
            NORTHWIND,
            "Ca1le de Alcalá 221, 3ª p1anta",
            "28O28 Madrid – Spain",
            "Attn: Accounts Payab le",
        ],
        columns=[
            ("C0de", 22, "L"),
            ("Descripti0n", 83, "L"),
            ("Qty", 15, "R"),
            ("Unit", 30, "R"),
            ("Net", 30, "R"),
        ],
        rows=[
            ["HF-12O", "Safety harness, ful1 body EN361", "6", "£64.50", "£387.00"],
            ["HF-3O4", "Energy abs0rbing lanyard 1.8 m", "6", "£38.25", "£229.50"],
            ["HF-O77", "Hard hat, vented, white", "20", "£11.90", "£238.00"],
        ],
        totals=[
            ("Sub t0tal", "£854.50"),
            ("VAT @ 20%", "£170.90"),
            ("!T0TAL", "£1,025.40"),
        ],
        after_totals=[
            "Pay ment ter ms: 3O d ays fr0m invoice date. Please qu0te invoice number with pay",
            "ment.",
            "Bank: Barc1ays – S0rt c0de 20-32-O6 – Acc 73O1 4455 – IBAN GB29 BARC 2032 0673 0144 55",
        ],
        footer_lines=[
            "Harlow & Finch Ltd – Registered in England & Wa1es N0. 08812345",
            "Registered 0ffice: Unit 7, Riverside lndustrial Estate, Leeds",
        ],
        config=config_with(expected_customer_tax_id="B12345678"),
        expected=expected(
            supplier_name="Harlow & Finch Ltd",
            invoice_number="HF-26-00731",
            invoice_date="2026-05-22",
            total_amount="1025.40",
            currency="GBP",
            tax_id="GB294773108",
            subtotal_amount="854.50",
            tax_amount="170.90",
            customer_name=NORTHWIND,
            customer_tax_id=None,
            verdict="REVIEW",
        ),
        notes="OCR-style text layer ('lnvoice N0.', 'T0TAL', 'Dat e:', O/0 and l/1 swaps in labels, a broken line) while key values stay clean; the config expects a customer tax id that is not printed, so the correct verdict is REVIEW.",
    ),
    Invoice(
        slug="06_credit_note",
        difficulty=["credit_note_refs", "negative_total"],
        title="FACTURA RECTIFICATIVA",
        supplier_lines=[
            "Iberia Cerámica Técnica S.A.",
            "Polígono Industrial El Colador, parcela 12",
            "12200 Onda (Castellón) – España",
            "Tel. 964 77 21 30 – administracion@iberiaceramica.es",
            "CIF: A-28123456",
        ],
        meta=[
            ("Nº rectificativa:", "R-2026-0042"),
            ("Fecha de emisión:", "10/06/2026"),
            ("Factura rectificada:", "F-2026-0318"),
            ("Fecha factura original:", "20/05/2026"),
        ],
        customer_heading="CLIENTE",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3ª planta",
            "28028 Madrid",
            "CIF: B12345678",
        ],
        intro_lines=[
            "Motivo de la rectificación: devolución de mercancía defectuosa (art. 15 RD 1619/2012). "
            "Esta factura rectificativa anula parcialmente la factura F-2026-0318 de fecha 20/05/2026, "
            "cuyo importe total fue de 1.815,00 €.",
        ],
        columns=[
            ("Ref.", 22, "L"),
            ("Concepto", 83, "L"),
            ("Cant.", 15, "R"),
            ("Precio", 30, "R"),
            ("Importe", 30, "R"),
        ],
        rows=[
            [
                "PC-6060",
                "Porcelánico técnico 60x60 gris (m²) – devolución",
                "-10",
                "20,00 €",
                "-200,00 €",
            ],
        ],
        totals=[
            ("Base imponible", "-200,00 €"),
            ("IVA 21%", "-42,00 €"),
            ("!Total factura", "-242,00 €"),
        ],
        after_totals=[
            "El importe se compensará en la próxima liquidación o se abonará mediante transferencia a la cuenta del cliente.",
            "IBAN emisor: ES91 2100 0418 4502 0005 1332",
        ],
        footer_lines=[
            "Iberia Cerámica Técnica S.A. – Inscrita en el Registro Mercantil de Castellón, Tomo 1422, Folio 88, Hoja CS-31207",
        ],
        expected=expected(
            supplier_name="Iberia Cerámica Técnica S.A.",
            invoice_number="R-2026-0042",
            invoice_date="2026-06-10",
            total_amount="-242.00",
            currency="EUR",
            tax_id="A28123456",
            subtotal_amount="-200.00",
            tax_amount="-42.00",
            customer_name=NORTHWIND,
            customer_tax_id="B12345678",
            verdict="FAIL",
        ),
        notes="Credit note that cites the original invoice number, date and original total (1.815,00 €) next to its own; the true total is negative, so it fails the total > 0 rule.",
    ),
    Invoice(
        slug="07_prepayment",
        difficulty=["prepayment", "balance_due_zero"],
        title="INVOICE",
        supplier_lines=[
            "Baltic Scaffold Systems OÜ",
            "Peterburi tee 71",
            "11415 Tallinn – Estonia",
            "+372 600 4471 · invoices@balticscaffold.ee",
            "Reg. code 14512345 · VAT No. EE101234567",
        ],
        meta=[
            ("Invoice No.:", "BSS/2026/0088"),
            ("Issue date:", "03 June 2026"),
            ("Supply date:", "01 June 2026"),
            ("Due date:", "Paid"),
        ],
        customer_heading="CUSTOMER",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3rd floor",
            "28028 Madrid, Spain",
            "VAT: ESB12345678",
        ],
        columns=[
            ("Code", 22, "L"),
            ("Description", 83, "L"),
            ("Qty", 15, "R"),
            ("Unit price", 30, "R"),
            ("Net", 30, "R"),
        ],
        rows=[
            ["SC-LB20", "Ledger beam 2.07 m, galvanised", "40", "14.50", "580.00"],
            ["SC-BP01", "Base plate with spindle 0.6 m", "16", "15.00", "240.00"],
        ],
        totals=[
            ("Net total", "820.00 EUR"),
            ("VAT 24%", "196.80 EUR"),
            ("!Invoice total", "1,016.80 EUR"),
            ("Paid in advance (proforma PF-0071, 20 May 2026)", "-1,016.80 EUR"),
            ("!Balance due", "0.00 EUR"),
        ],
        after_totals=[
            "This invoice has been settled in full by advance payment. No further payment is required.",
            "Bank: LHV Pank · IBAN EE38 2200 2210 2014 5685 · BIC LHVBEE22",
        ],
        footer_lines=[
            "Baltic Scaffold Systems OÜ · Peterburi tee 71, 11415 Tallinn · Reg. code 14512345",
        ],
        expected=expected(
            supplier_name="Baltic Scaffold Systems OÜ",
            invoice_number="BSS/2026/0088",
            invoice_date="2026-06-03",
            total_amount="1016.80",
            currency="EUR",
            tax_id="EE101234567",
            subtotal_amount="820.00",
            tax_amount="196.80",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        notes="Fully prepaid invoice: the last and most prominent figure is 'Balance due 0.00 EUR', and taking it as the total would wrongly fail the total > 0 rule.",
    ),
    Invoice(
        slug="08_currency_far",
        difficulty=["currency_far", "swiss_number_format"],
        title="RECHNUNG / INVOICE",
        supplier_lines=[
            "Alpen Hebetechnik AG",
            "Industriestrasse 9",
            "6300 Zug – Schweiz",
            "+41 41 710 55 20 · buchhaltung@alpen-hebetechnik.ch",
            "UID: CHE-123.456.789",
        ],
        meta=[
            ("Rechnung Nr.:", "AH-26-1147"),
            ("Datum:", "28.04.2026"),
            ("Leistungszeitraum:", "01.04.–25.04.2026"),
            ("Zahlbar bis:", "28.05.2026"),
        ],
        intro_lines=[
            "Sehr geehrte Damen und Herren, wir erlauben uns, Ihnen die folgenden Leistungen in Rechnung zu stellen. "
            "All amounts are in Swiss francs (CHF). Rental period and rates according to framework agreement RV-2025-031.",
        ],
        customer_heading="RECHNUNGSADRESSE",
        customer_lines=[
            NORTHWIND,
            "Calle de Alcalá 221, 3ª planta",
            "28028 Madrid – Spanien",
            "UID/VAT: ESB12345678",
        ],
        columns=[
            ("Pos.", 12, "L"),
            ("Leistung / Service", 93, "L"),
            ("Menge", 15, "R"),
            ("Ansatz", 30, "R"),
            ("Betrag", 30, "R"),
        ],
        rows=[
            ["1", "Mobilkran 60 t inkl. Kranführer, Tage", "3", "1'350.00", "4'050.00"],
            ["2", "Transport An-/Abfahrt Baustelle Baar", "1", "650.00", "650.00"],
            ["3", "Anschlagmittel und Hebeplanung", "1", "500.00", "500.00"],
        ],
        totals=[
            ("Total netto", "5'200.00"),
            ("MWST 8.1 %", "421.20"),
            ("!Rechnungstotal", "5'621.20"),
        ],
        after_totals=[
            "Zahlbar innert 30 Tagen netto. Bitte verwenden Sie den beigelegten QR-Einzahlungsschein.",
            "IBAN CH93 0076 2011 6238 5295 7 · Zuger Kantonalbank",
        ],
        footer_lines=[
            "Alpen Hebetechnik AG · Industriestrasse 9 · 6300 Zug · MWST-Nr. CHE-123.456.789 MWST",
        ],
        config=config_with(allowed_currencies=["EUR", "GBP", "CHF"]),
        expected=expected(
            supplier_name="Alpen Hebetechnik AG",
            invoice_number="AH-26-1147",
            invoice_date="2026-04-28",
            total_amount="5621.20",
            currency="CHF",
            tax_id="CHE123456789",
            subtotal_amount="5200.00",
            tax_amount="421.20",
            customer_name=NORTHWIND,
            customer_tax_id="ESB12345678",
            verdict="PASS",
        ),
        notes="Currency appears only once, in a sentence in the opening paragraph; totals carry no code or symbol and use the Swiss apostrophe thousands separator (5'621.20). CHF is allowed by this case's config, so missing it downgrades a PASS to REVIEW.",
    ),
]


def main() -> None:
    for inv in INVOICES:
        render(inv)
        write_label(inv)
        print(f"hB_{inv.slug}.pdf")


if __name__ == "__main__":
    main()
