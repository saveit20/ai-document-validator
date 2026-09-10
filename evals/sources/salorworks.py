"""SalorWorks Synthetic Shopify Invoice Test Pack (CC BY 4.0) -> slw_*.pdf + slw_*.expected.json.

Each fixture's expected.json is the candidate label; every non-null value must also be printed in the
pypdf text layer, otherwise it becomes null and is listed as a discrepancy. PDFs without a text layer
go to <out>/scanned/ (the system rejects them at ingest: 422 unreadable_document).

  python -m evals.sources.salorworks --raw-dir REPO [--out DIR]

REPO is a clone of github.com/SalorWorks/shopify-invoice-test-pack at COMMIT.
"""

import argparse
import datetime as dt
import json
import logging
import random
import re
import shutil
import sys
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from evals.sources._common import BASE_CONFIG, SEED, config_and_reference, default_out, verdict

COMMIT = "bb2e531cfa504e6f7200243620121c523f9f7622"
THREE_DECIMALS = {"KWD", "BHD", "OMR", "JOD", "TND", "IQD", "LYD"}
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

SHORT = {
    "01-simple-english": ("simple_english", []),
    "02-multipage": ("multipage", ["multi_page", "repeated_header"]),
    "03-arabic": ("arabic", ["language_arabic", "rtl"]),
    "04-bilingual": ("bilingual", ["language_bilingual", "mixed_direction"]),
    "05-uae-vat": ("uae_vat", ["trn_tax_id"]),
    "06-saudi-sar": ("saudi_sar", ["language_bilingual", "mixed_direction", "trn_tax_id"]),
    "07-kuwait-kwd": ("kuwait_kwd", ["three_decimals", "no_tax_line"]),
    "08-usd-for-aed": (
        "usd_for_aed",
        ["foreign_currency", "freight", "no_tax_line", "amounts_not_additive"],
    ),
    "09-line-discount": ("line_discount", ["discount", "line_discount", "trn_tax_id"]),
    "10-invoice-discount": (
        "invoice_discount",
        ["discount", "invoice_discount", "trn_tax_id", "amounts_not_additive"],
    ),
    "11-freight-duty": ("freight_duty", ["freight", "duty", "amounts_not_additive"]),
    "12-case-pack": ("case_pack", ["case_pack", "trn_tax_id"]),
    "13-free-of-charge": ("free_of_charge", ["free_of_charge", "trn_tax_id"]),
    "14-poor-scan": ("poor_scan", ["poor_scan", "rotated"]),
    "15-multicolumn": (
        "multicolumn",
        ["language_bilingual", "dense_table", "discount", "trn_tax_id"],
    ),
}


def money(value, currency: str) -> str:
    places = Decimal("0.001") if currency in THREE_DECIMALS else Decimal("0.01")
    return str(Decimal(str(value)).quantize(places))


def customer(bill_to: str) -> str:
    return bill_to.split(",")[0].split(" / ")[0].strip()


def candidate(j: dict) -> dict:
    """Map a fixture's expected.json to the project's ten fields."""
    cur = j["currency"]
    return {
        "supplier_name": j["supplier"]["name"],
        "invoice_number": j["invoiceNumber"],
        "invoice_date": j["invoiceDate"],
        "total_amount": money(j["total"], cur),
        "currency": cur,
        "tax_id": j["supplier"]["taxRegistration"],
        "subtotal_amount": money(j["subtotal"], cur),
        "tax_amount": money(j["tax"], cur),
        "customer_name": customer(j["billTo"]),
        "customer_tax_id": None,
    }


def printed(name: str, value: str, text: str) -> bool:
    flat = re.sub(r"\s+", " ", text.translate(ARABIC_DIGITS))
    if name.endswith("_amount"):
        return re.search(r"(?<![\d.,])" + re.escape(value) + r"(?![\d])", flat) is not None
    if name.endswith("tax_id"):
        return re.sub(r"\W", "", value) in re.sub(r"\W", "", flat)
    return value in flat


def line_problems(j: dict, text: str) -> list[str]:
    """Cross-check expected.json line totals and the tax/total arithmetic against the print."""
    cur, out = j["currency"], []
    for ln in j.get("lines", []):
        if not printed("x_amount", money(ln["lineTotal"], cur), text):
            out.append(f"line {ln['supplierSku']} total {ln['lineTotal']} not printed")
    base = Decimal(str(j["subtotal"])) - (
        Decimal(str(j["discount"])) if j["fixtureId"] != "09-line-discount" else 0
    )
    calc = base + Decimal(str(j["tax"])) + Decimal(str(j["freight"])) + Decimal(str(j["duty"]))
    if abs(calc - Decimal(str(j["total"]))) > Decimal("0.01"):
        out.append(f"arithmetic: {calc} != total {j['total']}")
    return out


def notes(fixture: str, extra: str) -> str:
    return (
        f"SalorWorks Synthetic Shopify Invoice Test Pack v1.0.0, fixture {fixture} (CC BY 4.0, (c) 2026 Salorworks, "
        f"github.com/SalorWorks/shopify-invoice-test-pack @ {COMMIT[:7]}); fictional supplier and amounts. {extra}"
    )


def main(raw_dir: Path, out: Path) -> None:
    fixtures = raw_dir / "fixtures"
    if out.exists():
        shutil.rmtree(out)
    (out / "scanned").mkdir(parents=True)
    text_cases, scanned = [], []
    for d in sorted(fixtures.iterdir()):
        j = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        reader = PdfReader(d / "invoice.pdf")
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        short, tags = SHORT[d.name]
        tags = [*tags, j["currency"].lower()] + (
            ["multi_page"] if len(reader.pages) > 1 and "multi_page" not in tags else []
        )
        case = {
            "id": f"slw_{short}",
            "fixture": d.name,
            "json": j,
            "tags": tags,
            "pages": len(reader.pages),
        }
        if not text.strip():
            scanned.append(case)
            continue
        fields, disc = candidate(j), []
        for name, value in list(fields.items()):
            if value is not None and not printed(name, value, text):
                disc.append(
                    {
                        "field": name,
                        "label_json": value,
                        "label": None,
                        "reason": "not printed in the PDF",
                    }
                )
                fields[name] = None
        case.update(fields=fields, discrepancies=disc, checks=line_problems(j, text))
        text_cases.append(case)

    order = sorted(text_cases, key=lambda c: c["id"])
    random.Random(SEED).shuffle(order)
    for index, case in enumerate(order):
        config, reference, extra = config_and_reference(
            index, case["fields"]["invoice_date"], case["fields"]["currency"]
        )
        result = verdict(case["fields"], config, reference)
        dropped = ", ".join(
            f"{x['field']} ({x['label_json']} in expected.json)" for x in case["discrepancies"]
        )
        spec = {
            "document": f"{case['id']}.pdf",
            "source": "salorworks",
            "reference_date": reference,
            "config": config,
            "difficulty": ["synthetic_gulf_invoice", *case["tags"], *extra],
            "expected": {**case["fields"], "verdict": result},
            "notes": notes(
                case["fixture"],
                "Label from the fixture's expected.json, verified against the pypdf text layer"
                + (f"; set to null because not printed: {dropped}." if dropped else "."),
            ),
        }
        shutil.copy(fixtures / case["fixture"] / "invoice.pdf", out / spec["document"])
        (out / f"{case['id']}.expected.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"{case['id']:22} {case['fixture']:20} pages={case['pages']} verdict={result} scenario={extra or ['pass']}"
        )
        print("   fields:", json.dumps(case["fields"], ensure_ascii=False))
        for x in case["discrepancies"]:
            print("   DISCREPANCY:", x)
        for x in case["checks"]:
            print("   CHECK:", x)

    for case in scanned:
        fields = dict.fromkeys(candidate(case["json"]), None)
        date = dt.date.fromisoformat(case["json"]["invoiceDate"])
        config = {**BASE_CONFIG, "allowed_currencies": [case["json"]["currency"]]}
        reference = (date + dt.timedelta(days=30)).isoformat()
        result = verdict(fields, config, reference)
        spec = {
            "document": f"{case['id']}.pdf",
            "source": "salorworks",
            "reference_date": reference,
            "config": config,
            "difficulty": [
                "synthetic_gulf_invoice",
                "scanned",
                "no_text_layer",
                "expected_unreadable_document",
                *case["tags"],
            ],
            "expected": {**fields, "verdict": result},
            "notes": notes(
                case["fixture"],
                "The PDF is a single raster image with no fonts and no text layer; the system does no OCR, "
                "so ingest must reject it (HTTP 422 unreadable_document). Fields are null; the verdict is what the rule "
                "engine gives an all-null extraction. The fixture's printed values are not scored.",
            ),
        }
        shutil.copy(fixtures / case["fixture"] / "invoice.pdf", out / "scanned" / spec["document"])
        (out / "scanned" / f"{case['id']}.expected.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"SCANNED {case['id']:22} {case['fixture']:20} verdict={result}")

    lic = (raw_dir / "LICENSE").read_text(encoding="utf-8")
    (out / "LICENSE-DATA.txt").write_text(
        f"Source: https://github.com/SalorWorks/shopify-invoice-test-pack (commit {COMMIT})\n"
        "Synthetic Shopify Invoice Test Pack v1.0.0 by Salorworks. PDFs copied unchanged and renamed slw_*.pdf;\n"
        "expected.json labels re-mapped to this project's schema.\n\n" + lic,
        encoding="utf-8",
    )


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--raw-dir", type=Path, required=True, help="clone of shopify-invoice-test-pack"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=default_out("salorworks"),
        help="output directory (deleted and recreated)",
    )
    args = parser.parse_args()
    main(args.raw_dir, args.out)
