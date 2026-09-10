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
    r"(?:\b(?:invoice|factura|facture|fattura|factuur|faktura|fatura|rechnung)s?\s*-?\s*"
    r"(?:no\b\.?|nr\b\.?|number|nummer|n[úu]m(?:ero|éro)?\b\.?|n[º°]\.?|n\.|#|id\b)?"
    r"|\b(?:numer|n[úu]mero|no\.?)\s+(?:de\s+)?(?:faktury|factura|facture|fatura))"
    r"\s*[:#]?\s*([A-Z0-9][A-Z0-9/.\-]*[A-Z0-9]|\d)",
    re.I,
)
_DATE_SPECIFIC = re.compile(
    r"\b(invoice\s*date|date\s*of\s*issue|issue\s*date|fecha\s*(?:de\s*)?(?:emisi[óo]n|factura))\b",
    re.I,
)
_DATE_GENERIC = re.compile(r"\b(date|fecha)\b", re.I)
_DUE = re.compile(r"\b(due|vencimiento|payment\s*terms)\b", re.I)
_TOTAL = re.compile(
    r"\b(total[a-z]*|amount\s*due|importe\s*total|gesamt\w*|rechnungs(?:betrag|total)|endbetrag"
    r"|zu\s*zahlen|[àa]\s*payer|te\s*betalen|gross\s*amount|montant\s*total"
    r"|valor\s*total)\b",
    re.I,
)
_TOTAL_STRONG = re.compile(
    r"\b(total\s*due|amount\s*due|total\s*a\s*pagar|importe\s*total|invoice\s*total|total\s*factura"
    r"|grand\s*total|total\s*amount|total\s*ttc|gesamtbetrag|rechnungs(?:betrag|total)"
    r"|totale\s*documento|totaal\s*te\s*betalen|zu\s*zahlen|montant\s*total)\b",
    re.I,
)
_NOT_TOTAL = re.compile(
    r"\b(sub-?\s*total|net\s*total|base\s*imponible|vat|iva|tax|total\s*h\.?t\b\.?|hors\s*tax\w*"
    r"|netto\w*|imponibile|zwischensumme|subtotaal)",
    re.I,
)
_TAX_LABEL = re.compile(
    r"\b(?:vat|tax\s*id|nif|cif|ust-?idnr\.?(?:\s*/\s*vat\s*id)?)\b"
    r"(?:\s*(?:reg(?:istration)?\.?|no\.?|number|id|nr\.?))*\s*[:#]?\s*(.+)$",
    re.I,
)
_SUBTOTAL = re.compile(
    r"\b(sub-?\s*total|net\s*total|net\s*amount|taxable\s*amount|base\s*imponible|total\s*h\.?t\b"
    r"|hors\s*tax\w*|netto\w*|imponibile|subtotaal|zwischensumme|net\s*value"
    r"|importe\s*neto)",
    re.I,
)
_TAX_WORD = r"(?:vat|iva|igic|tax|tva|mwst|ust|btw|gst|hst|moms)"
_TAX_AMOUNT = re.compile(
    rf"\b{_TAX_WORD}\b.*(%|@)|%\s*{_TAX_WORD}\b|^\s*{_TAX_WORD}\b\s*(?:\[%\])?\s*[\d(-]"
    rf"|\b(?:total\s*{_TAX_WORD}|{_TAX_WORD}\s*amount|cuota\s*iva)\b",
    re.I,
)
_TAX_ID_LINE = re.compile(
    r"\b(?:vat|tax)\s*(?:id|reg\w*|no\b|number|nr)|\b(?:nif|cif|ust-?idnr|tin|trn)\b", re.I
)
# A line that holds only an amount (with an optional currency code or symbol, or a percentage).
_VALUE_ONLY = re.compile(
    r"^\s*(?:[A-Z]{3}|[$€£¥₹])?\s*-?\(?\d[\d.,'’  ]*\)?\s*(?:%|[A-Z]{3}|[$€£¥₹]|-)?\s*$"
)
_WITHHOLDING = re.compile(r"\b(retenci[óo]n|irpf|withholding)\b", re.I)
_SECTION_START = re.compile(
    r"\b(invoice|factura|date|fecha|total|subtotal|description|qty|quantity|concepto|importe"
    r"|amount)\b",
    re.I,
)
# Label, name, two address lines and a tax id line; the block also ends at the next section.
_CUSTOMER_BLOCK_MAX_LINES = 6
_VALUE_DATE = re.compile(r"^\s*[\d./\-]{6,10}\s*$|^\s*\d{1,2}\s+\w+\.?\s+\d{2,4}\s*$")

Line = tuple[int, str]
Row = tuple[int, str, str]
"""(page, text to match, evidence). A label rejoined with its value reads "label value" but keeps
"label\\nvalue" as evidence, because that is how the document's text layer prints it."""


class HeuristicExtractor:
    def extract(self, document: Document) -> ExtractorOutput:
        lines = [
            (page, line.strip())
            for page, text in enumerate(document.pages, start=1)
            for line in text.split("\n")
        ]
        customer = _customer_lines(lines)
        own = [line for index, line in enumerate(lines) if index not in customer]
        rows = _value_rows(own)
        total = _total(rows)
        candidates = {
            "supplier_name": _supplier(lines, customer),
            "invoice_number": _invoice_number(own),
            "invoice_date": _invoice_date(own),
            "total_amount": total,
            "currency": _currency(own, total),
            "tax_id": _tax_id(own),
            "subtotal_amount": _last_amount(rows, _SUBTOTAL),
            "tax_amount": _last_amount(
                [
                    row
                    for row in rows
                    if not _WITHHOLDING.search(row[1]) and not _TAX_ID_LINE.search(row[1])
                ],
                _TAX_AMOUNT,
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


def _is_label(text: str) -> bool:
    return any(ch.isalpha() for ch in text) and not any(ch.isdigit() for ch in text)


def _value_rows(lines: list[Line]) -> list[Row]:
    """Every line, plus labels rejoined with values the text layer printed on later lines.

    Two layouts are recognised: one label followed by a single value, and a table printed as a run
    of labels followed by a run of values, which are paired in order from the last label. A label
    followed by more values than labels is left alone: the pairing would be a guess.
    """
    rows: list[Row] = [(page, text, text) for page, text in lines]
    index = 0
    while index < len(lines):
        if not _is_label(lines[index][1]):
            index += 1
            continue
        end_labels = index
        while end_labels < len(lines) and _is_label(lines[end_labels][1]):
            end_labels += 1
        end_values = end_labels
        while end_values < len(lines) and _VALUE_ONLY.match(lines[end_values][1]):
            end_values += 1
        labels = lines[index:end_labels]
        values = lines[end_labels:end_values]
        if values and len(values) <= len(labels):
            for (page, label), (_, value) in zip(labels[-len(values) :], values, strict=True):
                rows.append((page, f"{label} {value}", f"{label}\n{value}"))
        index = end_values if values else end_labels
    return rows


def _invoice_number(lines: list[Line]) -> Candidate:
    """The first labelled identifier that contains a digit; a plain word is never a number."""
    found = []
    for page, line in lines:
        position = 0
        while match := _INVOICE_NUMBER.search(line, position):
            if any(ch.isdigit() for ch in match[1]):
                found.append((match[1], line, page))
                break
            position = match.start(1)
    return _pick(found)


def _invoice_date(lines: list[Line]) -> Candidate:
    """A date on a line with an issue-date label beats one with a generic date label, which beats an
    unlabelled one. A date alone on its line takes the label of the line before it, when that line is
    only a label, because the text layer often prints a label and its value on separate lines."""
    tiers: dict[str, list[tuple[str, str, int]]] = {"specific": [], "generic": [], "none": []}
    previous = ""
    for page, line in lines:
        if not line:
            continue
        label, evidence = line, line
        if _is_label(previous) and _VALUE_DATE.match(line):
            label, evidence = f"{previous} {line}", f"{previous}\n{line}"
        previous = line
        dates = normalize.find_dates(line)
        if not dates or _DUE.search(label):
            continue
        if _DATE_SPECIFIC.search(label):
            tier = "specific"
        elif _DATE_GENERIC.search(label):
            tier = "generic"
        else:
            tier = "none"
        tiers[tier].extend((matched, evidence, page) for _, matched, _ in dates)
    for tier in ("specific", "generic", "none"):
        if tiers[tier]:
            return _pick(tiers[tier], ambiguous=tier == "none")
    return Candidate()


def _total(rows: list[Row]) -> Candidate:
    strong, plain = [], []
    for page, text, evidence in rows:
        if not _TOTAL.search(text) or _NOT_TOTAL.search(text):
            continue
        amounts = normalize.find_amounts(text)
        if not amounts:
            continue
        entry = (amounts[-1][2], evidence, page)
        (strong if _TOTAL_STRONG.search(text) else plain).append(entry)
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


def _last_amount(rows: list[Row], pattern: re.Pattern[str]) -> Candidate:
    found = [
        (amounts[-1][2], evidence, page)
        for page, text, evidence in rows
        if pattern.search(text) and (amounts := normalize.find_amounts(text))
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
