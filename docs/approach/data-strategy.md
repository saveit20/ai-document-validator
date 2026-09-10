# Data and evaluation strategy — anti-overfitting

> It stems from the author's critical review (2026-09-10): the initial invoices were too clean
> and the heuristic was designed while looking at them, so measuring it on them inflates the metrics.

## 1. Diagnosis

- **Real circularity.** The 14 dev invoices and the heuristic's patterns were written by the same author, and
  the patterns were checked against those invoices one by one. Any metric on dev is optimistic.
- **Data too clean.** One label per line, one column, one page, no noise. A real invoice, after PDF text
  extraction, comes out messy: interleaved columns, tables in a different order, the legal name only in the
  footer, "Total" repeated with other meanings, several VAT rates, other languages.
- **Consequence for the challenge:** without difficult invoices, the eval would conclude that the heuristic is
  enough, and the answer to *"when would you not use an LLM"* would be false. This fits the brief: it only
  excludes *"perfect coverage of every invoice layout on earth"* and OCR; the quality of the golden set and the
  honesty of the metrics weigh **High**.

## 2. Two sets

| Set | Author | Use | Can be looked at during development |
|---|---|---|---|
| `evals/golden/` (dev, 14) | Claude, before the heuristic | development, debugging, unit tests | yes |
| `evals/holdout/` (16) | 2 independent subagents, with no access to the code, the plan or dev | **main metric in the README** | **no**: it is only run and reported |

**Anti-cheating rule:** no extractor or prompt is tuned in response to a specific holdout failure.
If a general error discovered in the holdout is fixed, `evaluation.md` declares that the holdout has
become partially contaminated, and in what way.

## 3. How the holdout is built

- **Genuinely laid-out PDFs** (positioned text, two columns, tables, several pages, footers), generated with
  `fpdf2` and a TTF font. No dumping text line by line: `pypdf` extraction must produce the real mess, which
  also tests ingestion.
- Each agent leaves a reproducible generator script in `evals/holdout/generate_batch_{a,b}.py`.
- Each invoice carries **difficulty** tags so the metrics can be broken down.
- All content is text (no images), because OCR is out of scope.

## 4. Difficulty taxonomy

| Tag | What it breaks |
|---|---|
| `two_column_header` | issuer and customer in columns: extraction merges them into one line |
| `supplier_in_footer` | the legal name only appears in the legal footer; at the top, a trade name |
| `multi_page` | totals on page 2; header repeated on every page |
| `table_totals` | labels and figures in different columns of a table |
| `label_value_split` | the label on one line and the value on the next |
| `total_distractors` | "Total items", "Total weight", "Total excl. VAT" before the real total |
| `multi_vat` | several VAT rates; total tax = sum |
| `discount` | subtotal, discount, taxable base, VAT, total |
| `language_fr`, `language_de`, `language_it_pt` | labels in other languages |
| `number_format` | `1 234,56`, `1'234.50`, dates `15.06.2026` |
| `us_date` | `06/05/2026` on a US invoice (month first): deliberately clashes with ASSUMPTION-09 |
| `ocr_noise` | text layer with OCR-like errors (`lnvoice`, `T0TAL`, `2O26`) |
| `credit_note_refs` | credit note citing the original invoice and date |
| `prepayment` | invoice total versus a "balance due" of 0.00 |
| `currency_far` | the currency is only stated in a sentence far from the total |

## 5. Labelling guide (the same one the agents receive)

- `supplier_name`: the issuer's legal name as printed, with its legal form. If there is only a trade name at
  the top and the legal name in the footer, the legal name is labelled. `null` if there is none.
- `invoice_number`: the identifier as printed, without the label or `#`.
- `invoice_date`: the actual issue date, `YYYY-MM-DD`. For `us_date`, the true date (month first).
- `total_amount`: invoice total including taxes, decimal with `.` and 2 decimals; negative for credit notes. For
  `prepayment`, the invoice total, not the outstanding balance.
- `currency`: ISO 4217 code if there is a code or symbol; `null` if not stated.
- `tax_id` / `customer_tax_id`: tax identifier in canonical form (upper case, no spaces, dots or
  hyphens), with a country prefix only if it is printed.
- `subtotal_amount`: taxable base (after discounts) if it is printed as a figure; `null` otherwise.
- `tax_amount`: total tax charged; the sum if there are several rates; never withholdings such as IRPF.
- `customer_name`: the recipient's legal name.
- `verdict`: what a careful human reviewer would decide given the **true values** and the rules (§6).
  A value printed in a genuinely ambiguous way → REVIEW.

## 6. Rules for the true verdict

Reference date `2026-06-30`; default config = the one in the brief (`max_age_days` 90 → limit `2026-04-01`,
`allowed_currencies` EUR and GBP, `required_fields` the 4 from the example).

1. Date present, not earlier than `2026-04-01` and not later than `2026-06-30` → otherwise FAIL.
2. Total present and > 0 → otherwise FAIL.
3. Supplier present → otherwise FAIL.
4. Currency outside the list → FAIL; not stated → REVIEW.
5. Required fields missing → FAIL.
6. If subtotal, tax and total are printed and do not add up (±0.01) → REVIEW.
7. If the config includes `expected_customer_tax_id`: different → FAIL; missing → REVIEW (`ESB12345678` is
   equivalent to `B12345678`).

Precedence: FAIL > REVIEW > PASS.

## 7. Label verification

A third agent, once the first two have finished: for each PDF it extracts the text with `pypdf`, proposes its
own labels **without looking at the existing ones**, and then compares. Every discrepancy is resolved by hand
and recorded. The result goes into `docs/evaluation.md`: inter-labeller agreement and resolved discrepancies.

## 8. What is reported

- Holdout metrics as the headline figure; dev metrics as a reference, marked as optimistic.
- Breakdown by difficulty tag: where each extractor fails.
- Case-by-case failures, without hiding any.

## 9. Holdout contamination log

| Date | Change | Origin | Effect on holdout |
|---|---|---|---|
| 2026-09-10 | The customer block is also closed at a line that opens another section and after 4 lines, not only at a blank line | **Dev** failure (`inv_10_pdf`: pypdf does not preserve blank lines) | 41% → 54% fields, 38% → 44% verdicts. General change, not motivated by any holdout case. Claude read the agents' reports (which difficulty each invoice covers) but not the case-by-case failures, which the eval hides by default. |
| 2026-09-10 14:00 | None | When reformatting `generate_batch_a.py`, the tool displayed, unrequested, its first ~240 lines (contents of `hA_01`: issuer/customer blocks in two columns) | Exposure declared. No extractor or prompt has been modified as a result; the PDF and the label remain byte-for-byte identical (hash verified). |
| 2026-09-10 14:10 | Extraction prompt reverted to the version pre-registered in the plan (written before the holdout existed) | Claude detected that its draft added 5 instructions that responded to specific holdout categories (legal name in the footer, balance after prepayment, currency name, US date, several VAT rates) | None: it was reverted before any call to the model. It is teaching to the test, even if with the taxonomy rather than the answers. |

## 10. Revision v2 (DEC-15): mixed independent sources

DEC-15 and the other DEC-xx IDs refer to the working decision log (its final form is docs/decisions.md).

Section §2 is replaced by this:

| Source | Author | Licence | Cases | In metrics |
|---|---|---|---|---|
| Mendeley + katanaml labels | third parties | CC BY 4.0 (PDF) + MIT (labels) | those cross-matched and verified | yes: 50% dev, 50% test |
| Agent holdout | 2 isolated agents + verifier | own | 16 | yes: 50% dev, 50% test |
| Claude's golden set | Claude | own | 14 | **no**: unit-test fixtures only |

- Split stratified by source, with a fixed seed, saved in a versioned manifest (`evals/splits.json`).
- **dev**: failures are looked at and fixed. **test**: aggregate metrics only; case-by-case failures are
  hidden by default.
- Since half of the holdout moves to dev, the anti-cheating rule now applies to **test**, not to the whole holdout.
- Report per source: the volume of Mendeley (a single template) must not mask the difficult layouts.
- Foreseeable and useful failure: Mendeley uses US dates (month first) and `$`, conflicting with ASSUMPTION-09.
  It will show up in **dev**, so fixing it is allowed: the date format must be inferred from the document.

## 11. Quality of the third-party labels (katanaml)

76 labels cross-matched with their Mendeley PDF: 72 verified, 4 discarded.
- 1 empty (`None`).
- 1 with a gross total that does not appear printed in the PDF.
- 2 with a company name mistranscribed (`Dunn-Campbel.`) or with the Tax Id in the name field.
- In addition, 3 differ only in capitalisation; they are accepted because the truth is the printed name.

Conclusion for the report: even a dataset labelled and published by a third party carries ~5% wrong labels.
That is why every label is verified against the document before entering the eval.

## 12. Rule for fixing the heuristic with Mendeley

dev and test share the Mendeley template. A fix specific to that template would also raise the test figure
without the system generalising any better. Only **general** fixes are allowed (e.g. inferring the date format
from the document, or reading the value on the line after the label), and they are declared here.

### General fixes applied (2026-09-10, after the Haiku pilot on dev)

Diagnosis on dev: Haiku extracts 96% of the fields, but the verdict is only correct in 27%: verification
was rejecting correct values. Causes, all general and covered by the robustness report
(which was written from invented inputs, not from the evaluation cases):

| Fix | Origin | Effect (Haiku dev, same recordings) |
|---|---|---|
| Thousands separators with space / NBSP / apostrophe | R01 | verdict 27% → 64% together with the following |
| Accounting negatives `(1.234,56)` and `1.234,56-` | R08 | |
| Date order per document (ASSUMPTION-09 revised) | R02, R19 | |
| More ISO codes, `A$`/`C$`…, currency names; `$` resolved by US address | R06, R16 | |
| Evidence accepted line by line (columns separated by the text layer) | dev failure `hA_01` and Mendeley | |
| `canon` with letters from any alphabet | R13 | |

**Prompt v3** (invalidates the recordings; Haiku is re-recorded on dev): two general instructions. (1) Copy the
numbers from the evidence with their original separators: on dev the model rewrote `$ 802,73` as `$ 802.73`
and verification, correctly, rejected it. (2) Read numeric dates according to the issuer's convention
(proposal P1 of the robustness report). Neither responds to a test category.

## 13. Third source: Mustang (DEC-19)

6 German ZUGFeRD invoices (Apache-2.0). Labels from the embedded EN 16931 XML, verified against the PDF:
in `mst_weclapp` the XML says 963.11 and the PDF prints 963.12 (the printed value prevails); issuer and customer
tax IDs in the XML but not printed → `null`. Contributes real ERP layouts, German number format, dates with
month names, prepayments and two VAT rates. Little variety of language or currency (5 EUR, 1 GBP).

## 14. IDSEM and SalorWorks (approved by the author)

- **IDSEM:** 30 electricity invoices (5 × 6 labelled templates), read via HTTP ranges from the 30.9 GB zip
  (6.3 MB; the zip has offsets truncated to 32 bits, so a custom reader was written outside the repository).
  `tax_amount` = null in all 30: two VAT lines are printed, never their sum. 15/15 split per template
  (3/2 alternating).
- **SalorWorks:** 10 invoices with text (AED, KWD with 3 decimals, USD). The 5 Arabic/bilingual/scanned ones
  are images with no text: outside the metrics set (the system rejects them by design). 5/5 split.
- dev and test grow to 67 cases each.

## 15. GOBL (the author's decision: explore)

26 invoices from 13 countries and 9 currencies, rendered to PDF with Edge from the HTML published by gobl.html
(without installing anything). Labels from the GOBL JSON verified against the printed text. 2 discarded
(possible real natural person; printed total not backed by the JSON). 13/13 split. dev and test: 80 each.
General fix before freezing the test: non-European tax identifiers (CUIT, NIT, RFC, UEN, NIP,
codice fiscale) in `normalize_tax_id`; does not require re-recording. API budget (set by the author): ~$3.4 for
Opus on GOBL dev (13) + test (80), with a hard cap via `--max-calls`.

Candidate sources pending the author's decision (search of 2026-09-10): IDSEM (sample of 60 Spanish
electricity invoices via HTTP ranges, ~42 MB), SalorWorks (CC BY 4.0, Arabic/RTL, 1.7 MB), FATURA (CC BY 4.0,
50 templates, image only), CORD (receipts, CC BY 4.0).
