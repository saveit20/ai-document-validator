"""IDSEM, Spanish electricity bills (CC BY 4.0, Zenodo 6373179) -> idsem_t<T>_<N>.pdf + .expected.json.

The archive is 30.9 GB, a non-zip64 zip whose 32-bit local-header offsets wrap past 4 GB, so it is
read with HTTP range requests instead of being downloaded. Three steps:

  python -m evals.sources.idsem index --cd cdfull.bin --index index.json
  python -m evals.sources.idsem fetch --index index.json --raw-dir RAW       (network)
  python -m evals.sources.idsem label --raw-dir RAW [--out DIR]

`index` parses the archive's central directory bytes and unwraps the offsets modulo 2**32. `fetch`
draws 5 labelled bills per training template with a fixed seed and extracts each PDF + JSON.
`label` maps the IDSEM JSON to the project's fields; every non-null value must also be printed in the
PDF text layer, otherwise it becomes null and is listed as a discrepancy.

Field mapping (IDSEM key -> our field):
  C1 supplier_name, C2 tax_id, F1 invoice_number, F3 invoice_date (issue date),
  J5 total_amount (TOTAL IMPORTE FACTURA, amount payable),
  J4 subtotal_amount (pre-VAT "Importe total": energy + electricity tax + meter rental = sum of VAT bases),
  N5 + N8 tax_amount (VAT/IGIC only, two rate lines; electricity tax N2 is NOT VAT),
  A1 customer_name, A2 customer_tax_id, currency "EUR" iff the PDF prints EUR or the euro sign.
"""

import argparse
import datetime as dt
import json
import logging
import random
import re
import shutil
import struct
import time
import urllib.error
import urllib.request
import zlib
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from evals.sources._common import SEED, config_and_reference, default_out, verdict

RECORD_API = "https://zenodo.org/api/records/6373179"
PER_TEMPLATE = 5
BUDGET = 45 * 1024 * 1024
MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
_transferred = 0


def parse_central_directory(buf: bytes) -> tuple[dict, int, bytes, int]:
    """Return ({name: [offset, csize, usize, method]}, parsed length, trailing bytes, wrap count)."""
    out, pos, wraps, last = {}, 0, 0, -1
    while pos + 46 <= len(buf) and buf[pos : pos + 4] == b"PK\x01\x02":
        (_, _, _, _, method, _, _, _, csize, usize, nlen, xlen, clen, _, _, _, off) = struct.unpack(
            "<4sHHHHHHIIIHHHHHII", buf[pos : pos + 46]
        )
        name = buf[pos + 46 : pos + 46 + nlen].decode("utf-8", "replace")
        if off < last:
            wraps += 1
        last = off
        out[name] = [off + wraps * 2**32, csize, usize, method]
        pos += 46 + nlen + xlen + clen
    tail = buf[pos : pos + 4]
    return out, pos, tail, wraps


def build_index(cd: Path, index: Path) -> None:
    buf = cd.read_bytes()
    idx, pos, tail, wraps = parse_central_directory(buf)
    print(f"cd bytes={len(buf)} parsed_to={pos} tail={tail!r} entries={len(idx)} wraps={wraps}")
    index.write_text(json.dumps(idx))


def file_url(raw_dir: Path) -> str:
    cache = raw_dir / "url.txt"
    if cache.exists():
        return cache.read_text().strip()
    for attempt in range(6):
        try:
            with urllib.request.urlopen(RECORD_API, timeout=120) as r:
                url = json.load(r)["files"][0]["links"]["self"]
            cache.write_text(url)
            return url
        except urllib.error.HTTPError as exc:
            if attempt == 5 or exc.code < 500:
                raise
            time.sleep(5 * 2**attempt)


def read_range(url: str, start: int, length: int) -> bytes:
    """Fetch bytes [start, start+length) with retries on transient errors, within BUDGET overall."""
    global _transferred
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                assert r.status == 206, r.status
                data = r.read()
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 5 or (isinstance(exc, urllib.error.HTTPError) and exc.code < 500):
                raise
            time.sleep(5 * 2**attempt)
    _transferred += len(data)
    assert _transferred < BUDGET, _transferred
    assert len(data) == length, (len(data), length)
    return data


def extract(url: str, off: int, csize: int, usize: int, method: int) -> bytes:
    head = read_range(url, off, 30)
    sig, *_, nlen, xlen = struct.unpack("<4sHHHHHIIIHH", head)
    assert sig == b"PK\x03\x04", sig
    data = read_range(url, off + 30 + nlen + xlen, csize)
    out = zlib.decompress(data, -15) if method == 8 else data
    assert len(out) == usize, (len(out), usize)
    return out


def fetch(index: Path, raw_dir: Path) -> None:
    idx = json.loads(index.read_text())
    raw_dir.mkdir(parents=True, exist_ok=True)
    url = file_url(raw_dir)
    rand = random.Random(SEED)
    for t in range(1, 7):
        pat = re.compile(rf"(?:^|/)training/template{t}/Invoice(\d+)\.json$")
        nums = sorted(m.group(1) for k in idx if (m := pat.search(k)) and k.startswith("idsem/"))
        pdfs = {k for k in idx if re.search(rf"training/template{t}/Invoice\d+\.pdf$", k)}
        nums = [n for n in nums if any(p.endswith(f"/Invoice{n}.pdf") for p in pdfs)]
        chosen = sorted(rand.sample(nums, PER_TEMPLATE))
        print(f"template{t}: {len(nums)} labelled bills, chosen {chosen}")
        out = raw_dir / f"template{t}"
        out.mkdir(parents=True, exist_ok=True)
        for n in chosen:
            for ext in ("pdf", "json"):
                key = next(k for k in idx if k.endswith(f"training/template{t}/Invoice{n}.{ext}"))
                target = out / f"Invoice{n}.{ext}"
                if not target.exists():
                    target.write_bytes(extract(url, *idx[key]))
    print(f"bytes transferred: {_transferred}")


def dec(es: str) -> Decimal:
    return Decimal(es.replace(".", "").replace(",", "."))


def spanish(value: str) -> str:
    whole, cents = f"{Decimal(value):,.2f}".split(".")
    return whole.replace(",", ".") + "," + cents


def map_fields(js: dict) -> tuple[dict, dict]:
    months = {m: i + 1 for i, m in enumerate(MESES)}
    day, _, month, _, year = js["F3"].split()
    vat = dec(js["N5"]) + dec(js["N8"])
    fields = {
        "supplier_name": js["C1"].strip(),
        "invoice_number": js["F1"].strip(),
        "invoice_date": dt.date(int(year), months[month.lower()], int(day)).isoformat(),
        "total_amount": str(dec(js["J5"])),
        "currency": "EUR",
        "tax_id": js["C2"].strip(),
        "subtotal_amount": str(dec(js["J4"])),
        "tax_amount": str(vat),
        "customer_name": js["A1"].strip(),
        "customer_tax_id": js["A2"].strip(),
    }
    checks = {
        "subtotal+vat==total": dec(js["J4"]) + vat == dec(js["J5"]),
        "vat_lines": (js["N5"], js["N8"]),
        "elec_tax": js["N2"],
    }
    return fields, checks


def printed(name: str, value: str, flat: str) -> bool:
    """True when the value appears in the whitespace-collapsed PDF text in a Spanish printed form."""
    if name.endswith("_amount"):
        forms = (spanish(value), spanish(value).replace(".", ""), value)
        return any(re.search(r"(?<![\d.,])" + re.escape(v) + r"(?![\d])", flat) for v in forms)
    if name == "invoice_date":
        d = dt.date.fromisoformat(value)
        forms = [
            d.strftime("%d/%m/%Y"),
            d.strftime("%d.%m.%Y"),
            d.isoformat(),
            f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}",
            f"{d.day} de {MESES[d.month - 1]} de {d.year}",
        ]
        return any(f.lower() in flat.lower() for f in forms)
    if name == "currency":
        return "€" in flat or "EUR" in flat
    if name.endswith("tax_id"):
        return re.sub(r"\W", "", value) in re.sub(r"\W", "", flat)
    return re.sub(r"\s+", " ", value) in flat


def tags_for(template: int, pages: int, flat: str, js: dict) -> list[str]:
    tags = [
        f"idsem_template{template}",
        "utility_bill",
        "spanish",
        "synthetic_data",
        "spanish_number_format",
    ]
    if pages > 1:
        tags.append("multi_page")
    if re.search(r"\d{1,2} de [a-z]+ de \d{4}", js["F3"]) and js["F3"].lower() in flat.lower():
        tags.append("textual_spanish_date")
    tags += ["multi_vat", "electricity_tax"]
    tags.append("igic_not_iva" if "IGIC" in flat else "iva")
    if re.search(r"X,XX|XX,XX", flat):
        tags.append("placeholder_amounts")
    return tags


def label(raw_dir: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cases = []
    for jpath in sorted(raw_dir.glob("template*/Invoice*.json")):
        template, number = int(jpath.parent.name[8:]), jpath.stem[7:]
        js = json.loads(jpath.read_text(encoding="utf-8"))
        reader = PdfReader(jpath.with_suffix(".pdf"))
        texts = [p.extract_text() or "" for p in reader.pages]
        flat = re.sub(r"\s+", " ", "\n".join(texts))
        fields, checks = map_fields(js)
        discrepancies = []
        for name, value in list(fields.items()):
            if name == "tax_amount":
                # The bills print one line per VAT/IGIC rate and no total: the label is their sum,
                # valid only if every non-zero rate line is printed.
                lines = [str(dec(v)) for v in checks["vat_lines"] if dec(v) != 0]
                if not all(printed(name, line, flat) for line in lines):
                    discrepancies.append(
                        {"field": name, "label": value, "reason": "a VAT line is not printed"}
                    )
                    fields[name] = None
                continue
            if value is not None and not printed(name, value, flat):
                discrepancies.append(
                    {"field": name, "label": value, "reason": "not printed in the PDF text"}
                )
                fields[name] = None
        cases.append(
            {
                "id": f"idsem_t{template}_{number}",
                "src": jpath.with_suffix(".pdf"),
                "template": template,
                "fields": fields,
                "checks": checks,
                "discrepancies": discrepancies,
                "pages": len(reader.pages),
                "chars": [len(t.strip()) for t in texts],
                "tags": tags_for(template, len(reader.pages), flat, js),
            }
        )

    order = sorted(cases, key=lambda c: c["id"])
    random.Random(SEED).shuffle(order)
    for index, case in enumerate(order):
        config, reference, extra = config_and_reference(
            index, case["fields"]["invoice_date"], case["fields"]["currency"] or "EUR"
        )
        result = verdict(case["fields"], config, reference)
        spec = {
            "document": f"{case['id']}.pdf",
            "source": "idsem",
            "reference_date": reference,
            "config": config,
            "difficulty": [*case["tags"], *extra],
            "expected": {**case["fields"], "verdict": result},
            "notes": (
                f"IDSEM (Zenodo 6373179, CC BY 4.0) training/template{case['template']}/{case['src'].name}; synthetic Spanish "
                "electricity bill. Label mapped from the IDSEM JSON (C1,F1,F3,J5,C2,J4,A1,A2; tax_amount=N5+N8), verified against "
                "the printed PDF text; tax_amount is the sum of the printed VAT/IGIC rate lines (no total line is printed)."
            ),
        }
        (out / f"{case['id']}.expected.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        shutil.copyfile(case["src"], out / f"{case['id']}.pdf")
        print(
            f"{case['id']:18} pages={case['pages']} chars={case['chars']} verdict={result} scenario={extra or ['pass']} checks={case['checks']}"
        )
        print("   fields:", json.dumps(case["fields"], ensure_ascii=False))
        for d in case["discrepancies"]:
            print("   DISCREPANCY:", d)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    steps = parser.add_subparsers(dest="step", required=True)
    p_index = steps.add_parser("index", help="parse the central directory into index.json")
    p_index.add_argument(
        "--cd", type=Path, required=True, help="raw central directory bytes of idsem.zip"
    )
    p_index.add_argument("--index", type=Path, required=True, help="index.json to write")
    p_fetch = steps.add_parser("fetch", help="range-read the sampled bills (network)")
    p_fetch.add_argument("--index", type=Path, required=True, help="index.json from `index`")
    p_fetch.add_argument(
        "--raw-dir", type=Path, required=True, help="where template<T>/Invoice<N>.* go"
    )
    p_label = steps.add_parser("label", help="build the evaluation cases (offline)")
    p_label.add_argument(
        "--raw-dir", type=Path, required=True, help="directory with template<T>/Invoice<N>.*"
    )
    p_label.add_argument(
        "--out",
        type=Path,
        default=default_out("idsem"),
        help="output directory (deleted and recreated)",
    )
    args = parser.parse_args()
    if args.step == "index":
        build_index(args.cd, args.index)
    elif args.step == "fetch":
        fetch(args.index, args.raw_dir)
    else:
        label(args.raw_dir, args.out)
