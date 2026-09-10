# Assumptions

Everything that is not in the brief and had to be decided in order to move forward. The evaluator cannot
be asked, so each gap is closed with a documented decision.

Assumptions that affect the system's behaviour are also reflected in the README.

## Format

```text
### ASSUMPTION-01 — <short title>

**Ambiguity:** what the brief does not say.
**Alternatives:** the reasonable interpretations.
**Chosen:** which one and why (the simplest and most defensible).
**Impact:** what would change if the assumption were false.
**In the README:** yes / no
```

---

### ASSUMPTION-01 — The golden set is synthetic and written by us

**Ambiguity:** a golden set of ≥ 5 fixtures is required, but no documents are provided.
**Alternatives:** (a) our own synthetic invoices; (b) look for public sample invoices.
**Chosen:** (a). We control the labels and can design trap cases. (b) raises licensing and personal-data
concerns, and does not add more signal in a 24-hour challenge.
**Impact:** risk of circularity (see spec.md §3); mitigated by writing fixtures and labels before the
extractor and by reporting the failures.
**In the README:** yes
**Status:** proposed — to be validated by the author

### ASSUMPTION-02 — PDF with embedded text, no OCR

**Ambiguity:** "PDF bytes or plain text ... you may ship fixtures instead of real OCR".
**Alternatives:** (a) accept text and PDFs with a text layer; (b) text only; (c) OCR.
**Chosen:** (a). It satisfies "PDF bytes" with a text-extraction library, without getting into OCR, which
is out of scope. A PDF with no extractable text returns an explicit error.
**Impact:** scanned invoices are not processed; this is declared as a limitation.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-03 — Semantics of PASS / FAIL / REVIEW

**Ambiguity:** `PASS | FAIL | REVIEW` is required, but it is not defined when REVIEW applies. Nor whether
"present" means "extracted" or "extracted with sufficient confidence".
**Alternatives:**
(a) REVIEW when some rule depends on a field extracted with confidence below a threshold, or when the
extractor failed; FAIL only when a rule fails on reliable data.
(b) Never REVIEW; everything is PASS or FAIL.
(c) REVIEW for any missing field.
**Chosen:** (a). It is the only option that uses the third state for what it exists for in compliance: to
separate "the document is non-compliant" from "the system is not sure". A missing field with reliable
extraction means the document does not contain it → FAIL. A doubtful field → REVIEW, a person looks at it.
Precedence: FAIL if any rule fails on reliable data; otherwise REVIEW if any rule is doubtful; otherwise PASS.
**Impact:** defines the visible behaviour of the product. Changes the expected verdict of several
fixtures.
**In the README:** yes
**Status:** accepted by the author (P-04)

### ASSUMPTION-04 — `required_fields` generates its own rule

**Ambiguity:** the example config includes `"required_fields": ["supplier_name", "invoice_number",
"invoice_date", "total_amount"]`, but it is not among the four minimum rules.
**Alternatives:** (a) a generic rule "the listed fields are present"; (b) ignore it.
**Chosen:** (a). It is in the config for a reason, and it also demonstrates extensibility: a new rule
added without touching the others. Only the six field names are accepted; an unknown name is a config
error (4xx).
**Overlap to resolve in PLAN:** three of the four fields in the example already have their own presence
rule (date, amount, supplier). Only `invoice_number` adds something new. It must be decided whether a
missing field produces one or two failures in the response.
**Impact:** if it was not expected, it is a harmless extra rule.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-05 — `max_age_days` is measured against an injectable reference date

**Ambiguity:** "not older than max_age_days" does not say relative to which date.
**Alternatives:** (a) the current date; (b) an optional reference date in the request, defaulting to today.
**Chosen:** (b). In production it is today; in tests and the eval it is fixed, so that they do not expire
with the calendar. A future date is treated as suspicious (the rule fails with its own message).
Inclusive boundary: an age of exactly `max_age_days` days passes.
**Impact:** without this, the golden set would change its result every day.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-06 — Only `SUPPLIER_INVOICE` is supported

**Ambiguity:** the config carries `document_type`, but a single type is requested.
**Alternatives:** (a) accept only `SUPPLIER_INVOICE` and reject the rest with 4xx; (b) design a
document-type registry.
**Chosen:** (a). The brief asks for one type; building the registry would be over-engineering. Any
other type returns a clear error.
**Impact:** adding a type would imply a new field schema; it is mentioned in "next steps".
**In the README:** yes
**Status:** proposed

### ASSUMPTION-07 — Amounts in European and English-speaking formats

**Ambiguity:** the brief does not state the locale of the invoices; the domain (B2B compliance, Spanish
company) suggests invoices in EUR with the format `1.234,56`.
**Alternatives:** (a) support both formats, disambiguating by separator position;
(b) only one.
**Chosen:** (a). It is a real trap case and cheap to cover. Amounts are represented as
`Decimal`, never `float`.
**Impact:** a genuinely ambiguous amount (`1.234` without decimals) lowers the field's confidence.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-08 — Missing currency with `allowed_currencies` defined → REVIEW

**Ambiguity:** `currency` is "ISO 4217 code when present", but rule 4 requires it to be in the list if
the list exists. It does not say what to do if the invoice does not state a currency.
**Alternatives:** (a) FAIL; (b) REVIEW; (c) PASS.
**Chosen:** (b). Rule 4, unlike the others, does not say "must be present": it cannot be claimed that
the document is non-compliant, but it cannot be verified that it complies either. This is exactly the
REVIEW case (P-04).
**Impact:** changes the expected verdict of `inv_11_no_currency`.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-09 — Numeric dates are read day first

**Ambiguity:** `03/06/2026` is 3 June (Europe) or 6 March (US).
**Alternatives:** (a) always day first; (b) based on the currency or the issuer's country; (c) flag as
ambiguous every date whose day and month are both ≤ 12.
**Chosen:** (a). The domain is European B2B compliance. (c) would send almost every Spanish invoice to
REVIEW. (b) adds a fragile heuristic. The LLM prompt says the same, so that both extractors are
consistent.
**Impact:** a US invoice with a numeric date would be misread; this goes into the limitations.

**Revision 2026-09-10 (the data contradicts the assumption):** the 36 external dev invoices are from the US
(address with state and ZIP code) and date month first. New rule, per document:
1. an unambiguous numeric date in the document itself (one component > 12) fixes the order;
2. otherwise, the issuer's country: US postal address → month first; `€`, `£` or a European VAT number → day first;
3. conflicting signals or none → read day first, but confidence drops to 0.6 (REVIEW).
The same criterion resolves `$`: with a US address and no European signals it is USD with full confidence.
European invoices keep the previous behaviour (day first, full confidence). Prompt v3 asks the model for
the same convention, and confidence is still decided by the code, not by the model.
**Status:** validated by the author (2026-09-10).
**In the README:** yes

### ASSUMPTION-10 — Arithmetic mismatch → REVIEW, with a tolerance of 0.01

**Ambiguity:** what to do if subtotal + taxes ≠ total.
**Alternatives:** (a) FAIL; (b) REVIEW; (c) ignore it.
**Chosen:** (b). Withholdings (IRPF), discounts or surcharges legitimately break the identity, and so does
an extraction error. Neither case proves that the document is non-compliant. Tolerance of 0.01 for
rounding. The rule only applies if all three amounts are present.
**Impact:** `inv_14_irpf_withholding` is REVIEW.
**In the README:** yes
**Status:** proposed

### ASSUMPTION-11 — Customer rule only with `expected_customer_tax_id`; ES prefix equivalence

**Ambiguity:** the brief does not define a customer rule, nor how to compare a Spanish tax ID (NIF) with a
VAT number.
**Chosen:** the rule only exists if the config includes `expected_customer_tax_id` (the config in the brief
does not include it, so it does not change the default verdicts). `ESB12345678` and `B12345678` are the
same company: the country prefix of a European VAT number is ignored when comparing. Different customer →
FAIL; missing → REVIEW.
**Impact:** `inv_02` (PASS by equivalence) and `inv_13` (FAIL) use a config with the field.
**In the README:** yes
**Status:** proposed
