"""Label-pattern extractor: deterministic, free, and the offline baseline for the evaluation."""

import re
from collections import Counter

from validator import normalize
from validator.extraction import Candidate, ExtractorOutput
from validator.ingest import Document

_BILL_TO = re.compile(
    r"^\s*(bill(?:ed)?\s*to|ship\s*to|sold\s*to|customer|client|cliente|facturar\s*a)\b", re.I
)
_SUPPLIER_LABEL = re.compile(
    r"^\s*(?:supplier|seller|vendor|from|issued\s*by|proveedor|emisor)\s*:\s*(.*)$", re.I
)
_LEGAL_SUFFIX = re.compile(
    r"(?<![\w.])(?:ltd|limited|plc|llc|inc|corp|gmbh|ag|b\.?v|n\.?v|s\.?l\.?[up]?|s\.?a\.?u?|sas|sarl"
    r"|s\.?r\.?l|ab|oy|a/s)\.?(?!\w)",
    re.I,
)
_INVOICE_NUMBER = re.compile(
    r"\b(?:invoice|factura)\s*(?:no\.?|number|n[úu]m(?:ero|\.)?|n[º°o]\.?|#)\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9/.\-]*[A-Z0-9])",
    re.I,
)
_DATE_SPECIFIC = re.compile(
    r"\b(invoice\s*date|date\s*of\s*issue|issue\s*date|fecha\s*(?:de\s*)?(?:emisi[óo]n|factura))\b",
    re.I,
)
_DATE_GENERIC = re.compile(r"\b(date|fecha)\b", re.I)
_DUE = re.compile(r"\b(due|vencimiento|payment\s*terms)\b", re.I)
_TOTAL = re.compile(r"\b(total|amount\s*due|importe\s*total)\b", re.I)
_TOTAL_STRONG = re.compile(
    r"\b(total\s*due|amount\s*due|total\s*a\s*pagar|importe\s*total|invoice\s*total|total\s*factura"
    r"|grand\s*total|total\s*amount)\b",
    re.I,
)
_NOT_TOTAL = re.compile(r"\b(sub-?\s*total|net\s*total|base\s*imponible|vat|iva|tax)\b", re.I)
_TAX_LABEL = re.compile(
    r"\b(?:vat|tax\s*id|nif|cif|ust-?idnr\.?(?:\s*/\s*vat\s*id)?)\b"
    r"(?:\s*(?:reg(?:istration)?\.?|no\.?|number|id|nr\.?))*\s*[:#]?\s*(.+)$",
    re.I,
)
_SUBTOTAL = re.compile(
    r"\b(sub-?\s*total|net\s*total|net\s*amount|taxable\s*amount|base\s*imponible)\b", re.I
)
_TAX_AMOUNT = re.compile(r"\b(vat|iva|igic|tax)\b.*(%|@)", re.I)
_WITHHOLDING = re.compile(r"\b(retenci[óo]n|irpf|withholding)\b", re.I)
_SECTION_START = re.compile(
    r"\b(invoice|factura|date|fecha|total|subtotal|description|qty|quantity|concepto|importe"
    r"|amount)\b",
    re.I,
)
_CUSTOMER_BLOCK_MAX_LINES = 4

Line = tuple[int, str]


class HeuristicExtractor:
    def extract(self, document: Document) -> ExtractorOutput:
        lines = [
            (page, line.strip())
            for page, text in enumerate(document.pages, start=1)
            for line in text.split("\n")
        ]
        customer = _customer_lines(lines)
        own = [line for index, line in enumerate(lines) if index not in customer]
        total = _total(own)
        candidates = {
            "supplier_name": _supplier(lines, customer),
            "invoice_number": _first_match(own, _INVOICE_NUMBER),
            "invoice_date": _invoice_date(own),
            "total_amount": total,
            "currency": _currency(own, total),
            "tax_id": _tax_id(own),
            "subtotal_amount": _last_amount(own, _SUBTOTAL),
            "tax_amount": _last_amount(
                [line for line in own if not _WITHHOLDING.search(line[1])], _TAX_AMOUNT
            ),
            "customer_name": _customer_name(lines, customer),
            "customer_tax_id": _tax_id([lines[index] for index in sorted(customer)]),
        }
        return ExtractorOutput(candidates=candidates, used="heuristic")


def _customer_lines(lines: list[Line]) -> set[int]:
    """Indexes of the customer block: a 'Bill to'-style label and the few lines after it.

    The block ends at a blank line, at a line that opens another section, or after
    _CUSTOMER_BLOCK_MAX_LINES lines, because text extracted from PDFs usually loses blank lines.
    """
    indexes: set[int] = set()
    remaining = 0
    for index, (_, line) in enumerate(lines):
        if _BILL_TO.match(line):
            remaining = _CUSTOMER_BLOCK_MAX_LINES
        elif not line or _SECTION_START.search(line) or _SUPPLIER_LABEL.match(line):
            remaining = 0
        if remaining:
            indexes.add(index)
            remaining -= 1
    return indexes


def _pick(found: list[tuple[str, str, int]], ambiguous: bool = False) -> Candidate:
    """First (raw, evidence, page); ambiguous when several distinct raw values compete."""
    if not found:
        return Candidate()
    raw, evidence, page = found[0]
    competing = len({normalize.canon(item[0]) for item in found}) > 1
    return Candidate(raw=raw, evidence=evidence, page=page, ambiguous=ambiguous or competing)


def _supplier(lines: list[Line], customer: set[int]) -> Candidate:
    for index, (page, line) in enumerate(lines):
        if index in customer or not (match := _SUPPLIER_LABEL.match(line)):
            continue
        if match[1].strip():
            return Candidate(raw=match[1].strip(), evidence=line, page=page)
        following = next(((p, text) for p, text in lines[index + 1 :] if text), None)
        if following:
            return Candidate(raw=following[1], evidence=following[1], page=following[0])
    suffixed = [
        (line, line, page)
        for index, (page, line) in enumerate(lines)
        if index not in customer and _LEGAL_SUFFIX.search(line)
    ]
    return _pick(suffixed)


def _first_match(lines: list[Line], pattern: re.Pattern[str]) -> Candidate:
    found = [(m[1], line, page) for page, line in lines if (m := pattern.search(line))]
    return _pick(found)


def _invoice_date(lines: list[Line]) -> Candidate:
    tiers: dict[str, list[tuple[str, str, int]]] = {"specific": [], "generic": [], "none": []}
    for page, line in lines:
        dates = normalize.find_dates(line)
        if not dates or _DUE.search(line):
            continue
        if _DATE_SPECIFIC.search(line):
            tier = "specific"
        elif _DATE_GENERIC.search(line):
            tier = "generic"
        else:
            tier = "none"
        tiers[tier].extend((matched, line, page) for _, matched in dates)
    for tier in ("specific", "generic", "none"):
        if tiers[tier]:
            return _pick(tiers[tier], ambiguous=tier == "none")
    return Candidate()


def _total(lines: list[Line]) -> Candidate:
    strong, plain = [], []
    for page, line in lines:
        if not _TOTAL.search(line) or _NOT_TOTAL.search(line):
            continue
        amounts = normalize.find_amounts(line)
        if not amounts:
            continue
        entry = (amounts[-1][2], line, page)
        (strong if _TOTAL_STRONG.search(line) else plain).append(entry)
    chosen = strong or plain
    if not chosen:
        return Candidate()
    raw, evidence, page = chosen[-1]
    competing = len({normalize.parse_amount(item[0]) for item in chosen}) > 1
    return Candidate(raw=raw, evidence=evidence, page=page, ambiguous=competing)


def _currency(lines: list[Line], total: Candidate) -> Candidate:
    if total.evidence and (found := normalize.find_currencies(total.evidence)):
        code = next((c for c, amb, _ in found if not amb), found[0][0])
        return Candidate(raw=code, evidence=total.evidence, page=total.page)
    counts: Counter[str] = Counter()
    first_seen: dict[str, tuple[str, int]] = {}
    for page, line in lines:
        for code, _, _ in normalize.find_currencies(line):
            counts[code] += 1
            first_seen.setdefault(code, (line, page))
    if not counts:
        return Candidate()
    code = counts.most_common(1)[0][0]
    line, page = first_seen[code]
    return Candidate(raw=code, evidence=line, page=page, ambiguous=len(counts) > 1)


def _tax_id(lines: list[Line]) -> Candidate:
    found = [
        (tax_id, line, page)
        for page, line in lines
        if (m := _TAX_LABEL.search(line)) and (tax_id := normalize.normalize_tax_id(m[1]))
    ]
    return _pick(found)


def _last_amount(lines: list[Line], pattern: re.Pattern[str]) -> Candidate:
    found = [
        (amounts[-1][2], line, page)
        for page, line in lines
        if pattern.search(line) and (amounts := normalize.find_amounts(line))
    ]
    if not found:
        return Candidate()
    raw, evidence, page = found[-1]
    competing = len({normalize.parse_amount(item[0]) for item in found}) > 1
    return Candidate(raw=raw, evidence=evidence, page=page, ambiguous=competing)


def _customer_name(lines: list[Line], customer: set[int]) -> Candidate:
    """First company name in the customer block, cut right after its legal suffix."""
    for index in sorted(customer):
        page, line = lines[index]
        label = _BILL_TO.match(line)
        body = (line[label.end() :] if label else line).lstrip(" :")
        if suffix := _LEGAL_SUFFIX.search(body):
            return Candidate(raw=body[: suffix.end()].strip(), evidence=line, page=page)
    return Candidate()
