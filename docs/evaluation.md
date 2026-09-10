# Evaluation

How quality is measured, on which data, and why that data was chosen. The short version: two sources that
the system's author did not write, split 50/50 into a dev half we inspect and a test half we do not, with
every number broken down by source.

## 1. Why this matters more than the extractor

The first version of the evaluation used 14 invoices written by the same person who wrote the heuristic
extractor, and the extractor's patterns were checked against those invoices while it was being built. On
them the heuristic scored **100% of fields**. On invoices written by someone else it scored **about half**.
Any metric measured on data shaped by its own author is a measure of memory, not of generalisation, so
those 14 invoices are now used only as unit-test fixtures and appear in no metric.

## 2. Data sources

| Source | Author | Licence | Cases used | Role |
|---|---|---|---|---|
| Mendeley *Samples of electronic invoices* (Kozłowski & Weichbroth, 2021) | third party | CC BY 4.0 | 72 | dev + test |
| Held-out set (`evals/holdout/`) | two isolated agents that never saw the code | this project | 16 | dev + test |
| Author-written invoices (`evals/golden/`) | the system's author | this project | 14 | unit tests only |

**Mendeley.** Programmatically generated, single template, US style (month-first dates, `$`, US tax ids,
company names without a legal form). PDFs with a real text layer. Labels come from
[katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1)
(MIT), made by a third party on the same invoices. Attribution and the list of changes are in
`evals/external/mendeley/LICENSE-DATA.txt`.

**Held-out set.** 16 PDFs with deliberately messy, European layouts: two-column headers, legal name only in
the footer, totals on page two, label and value in separate table columns, several VAT rates, discounts,
French / German / Italian labels, a US invoice, OCR-style noise, a credit note, a prepayment, a currency
stated away from the totals. Each invoice is tagged with its difficulty.

### Sources considered and rejected

| Source | Why not |
|---|---|
| DocILE (Rossum, 6.7k real annotated business documents) | access through a research-only request form, no redistribution: a reviewer could not reproduce it |
| RVL-CDIP (Hugging Face) | scanned 1980s-90s tobacco-litigation images, no text layer (OCR is out of scope), only a document-class label, no fields, 38.8 GB, unclear licence |
| FATURA / FATURA2 | original licence CC BY-NC-SA (non-commercial); the Hugging Face copy relabels it |
| ~30 other Hugging Face invoice datasets | images only, no licence, retail receipts, or no field labels |
| Invoice PDFs found on the web | personal data, unknown rights, no labels |

**No source is real.** Freely licensed real invoices essentially do not exist, because real invoices carry
personal and commercial data. In production this evaluation would run on customer documents under a data
processing agreement.

## 3. Label quality

Labels were not trusted blindly.

- **Held-out set, labelled twice.** A third agent labelled all 16 PDFs without seeing the original labels,
  then compared. Agreement: 159/160 fields and 15/16 verdicts; the only disagreement was the second
  annotator's mistake (it read a middle dot `·` as `€`). 100% after adjudication.
- **Mendeley, verified against the PDF.** Each of the 76 katanaml labels was matched to its PDF by invoice
  number, and every labelled party name, date, tax id and amount had to appear in the printed text. 72
  passed. 4 were excluded: one empty label, one total that is not printed in the PDF, one misspelt company
  name (`Dunn-Campbel.`), one with the tax id in the name field. Three more differed only in letter case and
  were kept, with the printed name as ground truth. **Even a published third-party dataset had ~5% wrong
  labels.**

## 4. Split and protocol

`evals/splits.json` records the split: each source (Mendeley, held-out batch A, held-out batch B) is shuffled
with a fixed seed and cut in half.

| Split | Mendeley | Held-out | Total | Use |
|---|---|---|---|---|
| dev | 36 | 8 | 44 | failures inspected, bugs fixed |
| test | 36 | 8 | 44 | aggregate metrics only; per-case failures hidden unless `--show-test-failures` |

Rules we held ourselves to:

- Nothing is tuned against a test failure. The evaluation command hides test failures by default.
- Fixes found on dev must be **general**. Dev and test share the Mendeley template, so a template-specific
  fix would raise the test score without making the system generalise.
- Every exposure to held-out content is logged below, even accidental ones.
- The LLM extraction prompt was written before the evaluation data existed. A later draft that added
  instructions aimed at specific difficulty categories was reverted before any model call.

### Contamination log

| When | What | Effect |
|---|---|---|
| Customer-block fix | A dev bug (PDF text loses blank lines, so the customer block never ended) was fixed with a general rule | Also raised the then-hidden held-out score; declared |
| Formatting the generator | Reformatting `generate_batch_a.py` displayed part of one held-out invoice | No code or prompt changed; PDFs verified byte-identical |
| Prompt draft | Five instructions mirrored held-out difficulty categories | Reverted before any model call |

## 5. Metrics

| Metric | Definition |
|---|---|
| Field exact match | predicted value equals the label after normalisation (amounts compared numerically; names case- and whitespace-insensitive) |
| Precision / recall per field | correct ÷ predicted non-null; correct ÷ labelled non-null |
| Verdict agreement | predicted `PASS`/`FAIL`/`REVIEW` equals the label, plus a 3×3 confusion matrix |
| By difficulty | verdict agreement per difficulty tag |
| LLM calls, latency, cost | from recorded responses: mean and p95 latency, cost per document using the price table in `src/validator/pricing.py` |

Every figure is reported for the whole split and separately per source.

Because Mendeley invoices date from 2012–2021 and are in USD, the brief's config would make every one of them
fail. Each Mendeley case therefore carries its own config and reference date, cycling through three
scenarios (pass, disallowed currency, invoice too old), so verdicts carry information.

## 6. Results so far — heuristic extractor

`python -m evals.run --extractor heuristic`

| Configuration | Field exact match | Verdict agreement |
|---|---|---|
| test / all | 47% | 50% |
| test / Mendeley | 44% | 50% |
| test / held-out | 62% | 50% |

On the dev half of Mendeley the heuristic finds **no** invoice date (0/36) and **no** total, subtotal or
tax (0/36): the template prints each label on one line and its value on the next, dates are month-first,
and the totals table lists all labels before all values. It returns `FAIL` for every invoice, so its 50%
verdict agreement is only the invoices that were supposed to fail. Hand-written rules work for the layouts
they were written for; this is the gap the LLM path has to close, and the next section measures whether it
does and at what cost.
