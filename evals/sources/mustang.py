"""Mustang project ZUGFeRD / Factur-X samples (Apache-2.0) -> mst_*.pdf + mst_*.expected.json.

The CII XML embedded in each PDF is the candidate label; every non-null value must also be printed in
the PDF text. Values the PDF does not show (or shows differently) are set to null / overridden and
listed as discrepancies. Verdicts come from the project's rule engine.

  python -m evals.sources.mustang --raw-dir DIR [--out DIR]

DIR holds the PDFs from mustangproject library/src/test/resources.
"""

import argparse
import datetime as dt
import json
import logging
import random
import re
import shutil
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from evals.sources._common import SEED, config_and_reference, default_out, verdict

MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]

KEEP = {
    "EN16931_1_Teilrechnung.pdf": (
        "mst_teilrechnung",
        [
            "zugferd_visualisation",
            "multi_page",
            "multi_vat",
            "prepayment",
            "allowances_charges",
            "german_number_format",
        ],
    ),
    "EXTENDED_Fremdwaehrung_wdis_fx-pdfa4.pdf": (
        "mst_fremdwaehrung",
        [
            "zugferd_visualisation",
            "multi_page",
            "foreign_currency",
            "tax_in_two_currencies",
            "prepayment",
            "german_number_format",
        ],
    ),
    "MustangBeispiel20221026.pdf": (
        "mst_weclapp",
        [
            "erp_layout",
            "two_digit_year",
            "split_net_and_vat_lines",
            "xml_print_mismatch",
            "german_number_format",
        ],
    ),
    "MustangGnuaccountingBeispielRE-20170509_505.pdf": (
        "mst_gnuaccounting_505",
        ["erp_layout", "multi_vat", "sidebar_supplier_block", "german_number_format"],
    ),
    "ZTESTZUGFERD_1_INVDSS_012015738820PDF-1.pdf": (
        "mst_alphabet_leasing",
        ["fixed_width_layout", "scrambled_text_order", "two_dates", "german_number_format"],
    ),
    "zugferd_invoice.pdf": ("mst_kraxi", ["textual_german_date", "german_number_format"]),
}
# The printed value wins over the XML: the system is judged on what the document shows.
PRINT_OVERRIDES = {
    "MustangBeispiel20221026.pdf": {
        "total_amount": (
            "963.11",
            "963.12",
            "PDF prints 'Endsumme 963,12 €'; XML GrandTotal 963.11 (rounding)",
        )
    },
}


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child(el, name):
    return next((c for c in el if local(c.tag) == name), None)


def deep(el, name):
    return [e for e in el.iter() if local(e.tag) == name]


def xml_fields(xml: bytes) -> tuple[dict, dict]:
    """Map the CII XML to the project's ten fields plus diagnostic metadata."""
    root = ET.fromstring(xml)
    doc = next(c for c in root if local(c.tag).endswith("ExchangedDocument"))
    tx = next(c for c in root if local(c.tag).endswith("SupplyChainTradeTransaction"))
    seller, buyer = deep(tx, "SellerTradeParty")[0], deep(tx, "BuyerTradeParty")[0]
    settle = next(
        e
        for e in tx.iter()
        if local(e.tag)
        in ("ApplicableHeaderTradeSettlement", "ApplicableSupplyChainTradeSettlement")
    )
    summ = next(e for e in settle.iter() if local(e.tag).endswith("MonetarySummation"))
    currency = child(settle, "InvoiceCurrencyCode").text.strip()

    def vat(party):
        ids = [
            (i.get("schemeID"), i.text.strip())
            for r in deep(party, "SpecifiedTaxRegistration")
            for i in r
            if local(i.tag) == "ID"
        ]
        return next((v for s, v in ids if s == "VA"), None), ids

    def amount(name):
        els = [e for e in summ if local(e.tag) == name]
        pick = next((e for e in els if e.get("currencyID") == currency), None) or next(
            (e for e in els if e.get("currencyID") is None), els[0] if els else None
        )
        return None if pick is None else str(Decimal(pick.text.strip()).quantize(Decimal("0.01")))

    stamp = deep(doc, "DateTimeString")[0]
    assert stamp.get("format") == "102", stamp.get("format")
    seller_vat, seller_ids = vat(seller)
    buyer_vat, _ = vat(buyer)
    fields = {
        "supplier_name": child(seller, "Name").text.strip(),
        "invoice_number": child(doc, "ID").text.strip(),
        "invoice_date": dt.datetime.strptime(stamp.text.strip(), "%Y%m%d").date().isoformat(),
        "total_amount": amount("GrandTotalAmount"),
        "currency": currency,
        "tax_id": seller_vat,
        "subtotal_amount": amount("TaxBasisTotalAmount"),
        "tax_amount": amount("TaxTotalAmount"),
        "customer_name": child(buyer, "Name").text.strip(),
        "customer_tax_id": buyer_vat,
    }
    meta = {
        "type_code": child(doc, "TypeCode").text.strip(),
        "seller_tax_ids": seller_ids,
        "due_payable": amount("DuePayableAmount"),
        "tax_currency": getattr(child(settle, "TaxCurrencyCode"), "text", None),
        "vat_groups": len([e for e in settle if local(e.tag) == "ApplicableTradeTax"]),
    }
    return fields, meta


def german(value: str) -> str:
    whole, cents = f"{Decimal(value):,.2f}".split(".")
    return whole.replace(",", ".") + "," + cents


def printed(name: str, value: str, text: str, currency_symbols: dict) -> bool:
    """True when the value appears in the PDF text in one of the forms a German invoice prints."""
    flat = re.sub(r"\s+", " ", text)
    if name.endswith("_amount"):
        return any(
            re.search(r"(?<![\d.,])" + re.escape(v) + r"(?![\d])", flat)
            for v in (german(value), value, german(value).replace(".", ""))
        )
    if name == "invoice_date":
        d = dt.date.fromisoformat(value)
        forms = [
            d.strftime("%d.%m.%Y"),
            d.strftime("%d.%m.%y"),
            d.isoformat(),
            f"{d.day}. {MONTHS[d.month - 1]} {d.year}",
        ]
        return any(f in flat for f in forms)
    if name == "currency":
        return value in flat or any(s in flat for s in currency_symbols.get(value, ()))
    if name.endswith("tax_id"):
        return re.sub(r"\W", "", value) in re.sub(r"\W", "", flat)
    return value in flat


def main(raw_dir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.expected.json"):
        old.unlink()
    cases, report = [], []
    for pdf in sorted(raw_dir.glob("*.pdf")):
        reader = PdfReader(pdf)
        xmls = [v[0] for k, v in reader.attachments.items() if k.lower().endswith(".xml")]
        if pdf.name not in KEEP:
            report.append({"file": pdf.name, "kept": False, "has_xml": bool(xmls)})
            continue
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        fields, meta = xml_fields(xmls[0])
        discrepancies = []
        for name, (xml_value, shown, why) in PRINT_OVERRIDES.get(pdf.name, {}).items():
            assert fields[name] == xml_value, (pdf.name, name, fields[name])
            fields[name] = shown
            discrepancies.append({"field": name, "xml": xml_value, "label": shown, "reason": why})
        for name, value in list(fields.items()):
            if value is not None and not printed(name, value, text, {"EUR": ("€", "EUR")}):
                discrepancies.append(
                    {"field": name, "xml": value, "label": None, "reason": "not printed in the PDF"}
                )
                fields[name] = None
        case_id, tags = KEEP[pdf.name]
        cases.append(
            {
                "id": case_id,
                "pdf": pdf.name,
                "fields": fields,
                "meta": meta,
                "tags": tags,
                "discrepancies": discrepancies,
                "pages": len(reader.pages),
            }
        )

    order = sorted(cases, key=lambda c: c["id"])
    random.Random(SEED).shuffle(order)
    for index, case in enumerate(order):
        config, reference, extra = config_and_reference(
            index, case["fields"]["invoice_date"], case["fields"]["currency"]
        )
        result = verdict(case["fields"], config, reference)
        spec = {
            "document": f"{case['id']}.pdf",
            "source": "mustang",
            "reference_date": reference,
            "config": config,
            "difficulty": ["zugferd_sample", *case["tags"], *extra],
            "expected": {**case["fields"], "verdict": result},
            "notes": f"Mustang project test resource {case['pdf']} (Apache-2.0); label from the embedded CII XML, verified against the printed PDF text.",
        }
        (out / f"{case['id']}.expected.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        shutil.copyfile(raw_dir / case["pdf"], out / spec["document"])
        print(
            f"{case['id']:24} {case['pdf']:46} type={case['meta']['type_code']} pages={case['pages']} vat_groups={case['meta']['vat_groups']} "
            f"due={case['meta']['due_payable']} verdict={result} scenario={extra or ['pass']}"
        )
        print("   fields:", json.dumps(case["fields"], ensure_ascii=False))
        print(
            "   seller tax ids:",
            case["meta"]["seller_tax_ids"],
            "tax_currency:",
            case["meta"]["tax_currency"],
        )
        for d in case["discrepancies"]:
            print("   DISCREPANCY:", d)
    for r in report:
        print(f"dropped {r['file']} has_xml={r['has_xml']}")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--raw-dir", type=Path, required=True, help="directory with the Mustang sample PDFs"
    )
    parser.add_argument("--out", type=Path, default=default_out("mustang"), help="output directory")
    args = parser.parse_args()
    main(args.raw_dir, args.out)
