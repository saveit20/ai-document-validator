"""invopop/gobl.html examples (Apache-2.0) -> gobl_*.pdf + gobl_*.expected.json.

PDFs: the committed example HTML (gobl.html/examples/out/<name>.html) printed with Microsoft Edge
headless. Labels: the GOBL JSON input of that HTML (gobl.html/examples/<name>.json), checked against the
pypdf text of the PDF. The printed form wins; values not printed (or only garbled) become null and are
listed as discrepancies. Verdicts come from the project's rule engine.

  python -m evals.sources.gobl --raw-dir DIR [--out DIR] [--work DIR] [--edge PATH]
  python -m evals.sources.gobl --raw-dir DIR --skip-render --pdf-dir evals/external/gobl [--out DIR]

DIR holds clones of github.com/invopop/gobl and github.com/invopop/gobl.html (as gobl/ and gobl.html/).
Edge output is not byte-stable, so --skip-render relabels existing gobl_<case>.pdf files instead.
"""

import argparse
import json
import logging
import random
import re
import shutil
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from evals.sources._common import SEED, config_and_reference, default_out, verdict

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# gobl example name -> (case id, label language, extra tags)
KEEP = {
    "es-verifactu-credit-note.adjustment.es": (
        "gobl_es_verifactu_cn",
        "es",
        ["credit_note", "negative_amounts", "wrapped_invoice_number", "real_company_invopop"],
    ),
    "es-ticketbai-credit-note.adjustment.es": (
        "gobl_es_ticketbai_cn",
        "es",
        ["credit_note", "negative_amounts", "multi_vat"],
    ),
    "es-verifactu-invoice-usd": (
        "gobl_es_usd",
        "en",
        ["foreign_currency", "exchange_rate_distractor", "us_number_format"],
    ),
    "es-verifactu-invoice-simplified": ("gobl_es_simplified", "en", ["simplified", "no_customer"]),
    "invoice-es-reverse-charge": ("gobl_es_reverse_charge", "en", ["reverse_charge", "zero_tax"]),
    "fr-invoice-units.fr": ("gobl_fr_units", "fr", []),
    "fr-ctc-credit-note": ("gobl_fr_ctc_cn", "en", ["credit_note", "positive_amounts"]),
    "fr-ctc-invoice-b2bint": ("gobl_fr_b2b_intra", "en", ["intra_eu_exempt", "zero_tax"]),
    "pl-ksef-credit-note.adjustment.pl": (
        "gobl_pl_ksef_cn",
        "pl",
        ["credit_note", "negative_amounts", "corrective"],
    ),
    "pl-ksef-invoice": ("gobl_pl_ksef", "en", ["space_grouping", "multi_vat"]),
    "de-invoice": ("gobl_de", "en", ["multi_vat"]),
    "it-sdi-invoice-hotel-b2c": (
        "gobl_it_hotel",
        "en",
        ["prices_include_tax", "fiscal_code_as_customer_id"],
    ),
    "it-ticket-corrective-invoice": (
        "gobl_it_ticket_corrective",
        "en",
        ["corrective", "prices_include_tax", "no_customer"],
    ),
    "pt-at-invoice-cash-vat": (
        "gobl_pt_cash_vat",
        "en",
        ["space_in_invoice_number", "currency_symbol_after"],
    ),
    "pt-at-invoice-multipage": (
        "gobl_pt_multipage",
        "en",
        ["space_in_invoice_number", "multi_vat", "currency_symbol_after"],
    ),
    "gr-mydata-invoice": ("gobl_gr", "en", ["greek_script"]),
    "mx-sat-invoice": ("gobl_mx", "en", ["withholding", "payable_differs", "prepaid"]),
    "mx-sat-invoice-ieps": ("gobl_mx_ieps", "en", ["excise_tax"]),
    "co-dian-invoice": ("gobl_co", "en", ["tech_provider_header", "large_amounts"]),
    "co-dian-credit-note": (
        "gobl_co_cn",
        "en",
        ["credit_note", "prices_include_tax", "prepaid", "tech_provider_header"],
    ),
    "ar-arca-invoice-b": (
        "gobl_ar_b",
        "en",
        ["prices_include_tax", "charges", "consumer_customer"],
    ),
    "sa-invoice-simplified": (
        "gobl_sa_simplified",
        "en",
        ["simplified", "arabic_script", "no_customer"],
    ),
    "sg-invoice": ("gobl_sg", "en", ["gst"]),
    "sg-invoice-not-registered": ("gobl_sg_unregistered", "en", ["no_tax"]),
    "us-invoice": ("gobl_us", "en", ["no_tax"]),
    "zw-invoice-usd": ("gobl_zw", "en", ["foreign_currency"]),
}
DROP = {
    "es-verifactu-invoice-freelance": "supplier is a sole trader printed with a full personal name, a checksum-valid DNI and an IBAN: looks like a real private person",
    "ar-arca-t-invoice-included": "printed 'Total to pay $247,93' (after tourist VAT refund) contradicts GOBL payable/total_with_tax 300.00; no single defensible total label",
}
# Printed value that is not the GOBL tax_id.code.
EXTRA_LABELS = {
    "it-sdi-invoice-hotel-b2c": {
        "customer_tax_id": (
            "RSSGNN60R30H501U",
            "GOBL tax_id has no code; printed 'Codice fiscale' from customer.identities[it-fiscal-code]",
        )
    },
}
FLAGS = {
    "es-verifactu-credit-note.adjustment.es": "supplier Invopop S.L. is a real company (GOBL maintainer)",
    "us-invoice": "supplier Invopop Inc. is a real company (GOBL maintainer)",
    "co-dian-invoice": "header prints real software provider 'EMPRESA DE DIVULGACIONES Y ASESORIAS ECA SAS'; contact 'Diego Lopez' is a placeholder",
    "co-dian-credit-note": "header prints real software provider 'EMPRESA DE DIVULGACIONES Y ASESORIAS ECA SAS'",
    "gr-mydata-invoice": "footer prints real e-invoicing provider 'ΙΛΥΔΑ ΠΛΗΡΟΦΟΡΙΚΗ Α.Ε.'",
    "ar-arca-invoice-b": "customer 'Juana Pérez, Calle Falsa 123' is an obvious placeholder person",
    "it-sdi-invoice-hotel-b2c": "customer fiscal code RSSGNN60R30H501U is the textbook 'Rossi Giovanni' example",
}


def render(name: str, raw_dir: Path, work: Path, edge: str) -> Path:
    """Print gobl.html/examples/out/<name>.html to <work>/<name>.pdf with Edge headless."""
    work.mkdir(parents=True, exist_ok=True)
    for d in ("styles", "scripts"):
        shutil.copytree(raw_dir / "gobl.html" / "assets" / d, work / d, dirs_exist_ok=True)
    html = work / f"{name}.html"
    shutil.copy(raw_dir / "gobl.html" / "examples" / "out" / f"{name}.html", html)
    pdf = work / f"{name}.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run(
        [
            edge,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf}",
            "file:///" + str(html).replace("\\", "/"),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert pdf.exists(), f"Edge did not produce {pdf}"
    return pdf


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s))


def nospace(s: str) -> str:
    return re.sub(r"\s+", "", norm(s))


def amount_forms(value: str) -> set[str]:
    sign, body = ("-", value[1:]) if value.startswith("-") else ("", value)
    whole, cents = body.split(".")
    grouped = f"{int(whole):,}"
    return {
        sign + grouped.replace(",", th) + dec + cents
        for th in (",", ".", " ", "")
        for dec in (".", ",")
        if th != dec
    }


def printed(field: str, value: str, text: str) -> bool:
    flat = norm(text)
    if field.endswith("_amount"):
        pre = r"(?<![\d.,\-])" if not value.startswith("-") else r"(?<![\d.,])"
        return any(re.search(pre + re.escape(v) + r"(?![\d])", flat) for v in amount_forms(value))
    if field.endswith("tax_id"):
        return re.sub(r"\W", "", value) in re.sub(r"\W", "", flat)
    if field in ("invoice_number", "supplier_name", "customer_name"):
        return nospace(value) in nospace(text)
    return value in flat


def printed_tax_id(party: dict, text: str) -> str | None:
    """The party's tax id, with the country prefix only when it is printed as part of the id."""
    tid = party.get("tax_id") or {}
    code, country = tid.get("code"), tid.get("country", "")
    if not code:
        return None
    compact = re.sub(r"\W", "", norm(text))
    return (
        country + code if (country + code) in compact and f"({country})" not in norm(text) else code
    )


def labels(name: str, doc: dict, text: str) -> tuple[dict, list[dict], dict]:
    """Map a GOBL document to the project's fields and verify each value against the PDF text."""
    t, sup, cus = doc["totals"], doc["supplier"], doc.get("customer") or {}
    included = bool((doc.get("tax") or {}).get("prices_include"))
    fields = {
        "supplier_name": sup["name"],
        "invoice_number": (doc["series"] + "-" if doc.get("series") else "") + doc["code"],
        "invoice_date": doc["issue_date"],
        "total_amount": t["total_with_tax"],
        "currency": doc["currency"],
        "tax_id": printed_tax_id(sup, text),
        # subtotal is the net before tax; GOBL totals.sum is gross when prices include tax.
        "subtotal_amount": t["total"] if included else t["sum"],
        "tax_amount": t.get("tax", "0.00"),
        "customer_name": cus.get("name"),
        "customer_tax_id": printed_tax_id(cus, text) if cus else None,
    }
    disc = []
    if included:
        disc.append(
            {
                "field": "subtotal_amount",
                "gobl": t["sum"],
                "label": t["total"],
                "reason": "prices include tax: net totals.total used (totals.sum is gross)",
            }
        )
    elif t["sum"] != t["total"]:
        disc.append(
            {
                "field": "subtotal_amount",
                "gobl": t["sum"],
                "label": t["sum"],
                "reason": f"note: totals.total={t['total']} differs",
            }
        )
    for f, (value, why) in EXTRA_LABELS.get(name, {}).items():
        disc.append({"field": f, "gobl": fields[f], "label": value, "reason": why})
        fields[f] = value
    # Credit notes are booked negative, whatever sign is printed.
    credit_note = doc.get("type") == "credit-note"
    if credit_note:
        for f in ("total_amount", "subtotal_amount", "tax_amount"):
            if fields[f] is not None and Decimal(fields[f]) > 0:
                disc.append(
                    {
                        "field": f,
                        "gobl": fields[f],
                        "label": "-" + fields[f],
                        "reason": "printed negative on the credit note"
                        if printed(f, "-" + fields[f], text)
                        else "credit note printed positive: booked negative",
                    }
                )
                fields[f] = "-" + fields[f]
    for f, value in list(fields.items()):
        shown = value.lstrip("-") if credit_note and value else value
        if value is not None and not (printed(f, value, text) or printed(f, shown, text)):
            disc.append(
                {
                    "field": f,
                    "gobl": value,
                    "label": None,
                    "reason": "not printed (or only garbled) in the PDF text",
                }
            )
            fields[f] = None
    meta = {
        "type": doc.get("type", "standard"),
        "payable": t.get("payable"),
        "twt": t["total_with_tax"],
        "key": (sup["name"], t["sum"], t.get("tax"), t["total_with_tax"]),
    }
    return fields, disc, meta


def git_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def write_license(raw_dir: Path, out: Path) -> None:
    notice = (raw_dir / "gobl" / "NOTICE").read_text(encoding="utf-8").strip()
    html_notice = raw_dir / "gobl.html" / "NOTICE"
    parts = [
        "GOBL-derived evaluation cases (gobl_*.pdf, gobl_*.expected.json)",
        "",
        "Sources:",
        f"  https://github.com/invopop/gobl       commit {git_sha(raw_dir / 'gobl')}",
        f"  https://github.com/invopop/gobl.html  commit {git_sha(raw_dir / 'gobl.html')}",
        "Both repositories are licensed under the Apache License, Version 2.0",
        "(https://www.apache.org/licenses/LICENSE-2.0).",
        "",
        "The PDFs were rendered by this project from the example HTML committed in",
        "gobl.html/examples/out/ (with gobl.html/assets/styles and assets/scripts next to them), printed with",
        "Microsoft Edge headless (--print-to-pdf, no header/footer). Web fonts were not downloaded; the browser",
        "used local fallback fonts. The HTML content was not modified.",
        "",
        "Labels (expected fields) were taken from the GOBL JSON inputs in gobl.html/examples/<name>.json and",
        "checked against the text layer of the rendered PDF (pypdf); where the printed form differs, the printed",
        "form was used, and values not printed were set to null. config/reference_date/verdict are synthetic",
        "evaluation scenarios added by this project. Builder: evals/sources/gobl.py.",
        "",
        "NOTICE (invopop/gobl):",
        notice,
    ]
    if html_notice.exists():
        parts += [
            "",
            "NOTICE (invopop/gobl.html):",
            html_notice.read_text(encoding="utf-8").strip(),
        ]
    else:
        parts += ["", "invopop/gobl.html ships no NOTICE file."]
    (out / "LICENSE-DATA.txt").write_text("\n".join(parts) + "\n", encoding="utf-8")


def main(raw_dir: Path, out: Path, work: Path, edge: str, skip_render: bool, pdf_dir: Path) -> None:
    src = raw_dir / "gobl.html" / "examples"
    out.mkdir(parents=True, exist_ok=True)
    stale = list(out.glob("gobl_*.expected.json"))
    if not skip_render:
        stale += list(out.glob("gobl_*.pdf"))
    for old in stale:
        old.unlink()
    cases, seen = [], {}
    for name, (case_id, lang, extra) in KEEP.items():
        pdf = pdf_dir / f"{case_id}.pdf" if skip_render else render(name, raw_dir, work, edge)
        reader = PdfReader(pdf)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        assert len(norm(text)) > 200, f"{name}: no usable text layer"
        doc = json.loads((src / f"{name}.json").read_text(encoding="utf-8"))["doc"]
        fields, disc, meta = labels(name, doc, text)
        layout = (lang, doc.get("regime") or doc["supplier"].get("tax_id", {}).get("country"))
        dup = seen.get((meta["key"], layout))
        assert dup is None, f"near-duplicate {name} ~ {dup}: add it to DROP"
        seen[(meta["key"], layout)] = name
        pages = len(reader.pages)
        country = (doc["supplier"].get("tax_id") or {}).get("country") or (
            doc["supplier"].get("addresses") or [{}]
        )[0].get("country")
        tags = [
            f"country_{country.lower()}",
            f"lang_{lang}",
            f"currency_{doc['currency'].lower()}",
            *extra,
        ]
        if pages > 1:
            tags.append("multi_page")
        if meta["payable"] != meta["twt"] and "payable_differs" not in tags:
            tags.append("payable_differs")
        target = out / f"{case_id}.pdf"
        if pdf.resolve() != target.resolve():
            shutil.copy(pdf, target)
        cases.append(
            {
                "id": case_id,
                "name": name,
                "fields": fields,
                "disc": disc,
                "tags": tags,
                "pages": pages,
                "meta": meta,
            }
        )

    order = sorted(cases, key=lambda c: c["id"])
    random.Random(SEED).shuffle(order)
    for index, case in enumerate(order):
        config, reference, scen = config_and_reference(
            index, case["fields"]["invoice_date"], case["fields"]["currency"]
        )
        result = verdict(case["fields"], config, reference)
        spec = {
            "document": f"{case['id']}.pdf",
            "source": "gobl",
            "reference_date": reference,
            "config": config,
            "difficulty": ["gobl_sample", *case["tags"], *scen],
            "expected": {**case["fields"], "verdict": result},
            "notes": f"invopop/gobl.html example {case['name']} (Apache-2.0), printed to PDF with Edge headless; "
            "label from the GOBL JSON input, verified against the printed PDF text."
            + (f" Flag: {FLAGS[case['name']]}." if case["name"] in FLAGS else "")
            + (
                " Credit note printed with positive amounts; labelled negative (finance books "
                "credit notes negative)."
                if any(
                    d["reason"] == "credit note printed positive: booked negative"
                    for d in case["disc"]
                )
                else ""
            ),
        }
        (out / f"{case['id']}.expected.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"{case['id']:28} {case['name']:40} pages={case['pages']} verdict={result:5} scen={scen or ['pass']}"
        )
        print("   ", json.dumps(case["fields"], ensure_ascii=False))
        for d in case["disc"]:
            print("    DISCREPANCY:", d)
    for name, why in DROP.items():
        print(f"dropped {name}: {why}")
    write_license(raw_dir, out)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--raw-dir", type=Path, required=True, help="directory holding gobl/ and gobl.html/ clones"
    )
    parser.add_argument("--out", type=Path, default=default_out("gobl"), help="output directory")
    parser.add_argument(
        "--work",
        type=Path,
        default=default_out("gobl-render"),
        help="scratch directory for the Edge render",
    )
    parser.add_argument("--edge", default=EDGE, help="path to msedge.exe")
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="relabel existing gobl_<case>.pdf files from --pdf-dir instead of printing new ones",
    )
    parser.add_argument(
        "--pdf-dir", type=Path, help="where --skip-render reads the PDFs (default: --out)"
    )
    args = parser.parse_args()
    main(args.raw_dir, args.out, args.work, args.edge, args.skip_render, args.pdf_dir or args.out)
