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
| Mustang project test resources (`evals/external/mustang/`) | third party | Apache-2.0 | 6 | dev + test |
| IDSEM, Spanish electricity bills (`evals/external/idsem/`) | third party (Scientific Data, 2022) | CC BY 4.0 | 30 (5 per template × 6) | dev + test |
| SalorWorks invoice test pack (`evals/external/salorworks/`) | third party | CC BY 4.0 | 10 | dev + test |
| Held-out set (`evals/holdout/`) | two isolated agents that never saw the code | this project | 16 | dev + test |
| Author-written invoices (`evals/golden/`) | the system's author | this project | 14 | unit tests only |

**Mendeley.** Programmatically generated, single template, US style (month-first dates, `$`, US tax ids,
company names without a legal form). PDFs with a real text layer. Labels come from
[katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1)
(MIT), made by a third party on the same invoices. Attribution and the list of changes are in
`evals/external/mendeley/LICENSE-DATA.txt`.

**Mustang.** Six German ZUGFeRD / Factur-X invoices from the test resources of an open-source e-invoicing
library: real ERP layouts, German number and date formats, prepayments, two VAT rates, one GBP invoice that
also prints its tax in EUR. Labels come from the EN 16931 XML embedded in each PDF and were checked against
the printed text; where they disagree, the printed document wins (one total printed as 963,12 against 963.11
in the XML; tax ids present in the XML but not printed were set to null). Near-duplicates and PDFs without
embedded data were left out.

**IDSEM.** Synthetic Spanish household electricity bills from a 75,000-bill research dataset: six
utility-style templates, 2–4 pages each, dates written out in Spanish or as dd.mm.yyyy, IVA or IGIC
(Canary Islands) tax, placeholder amounts such as `X,XX €` in the detail pages. Five bills per template were
read out of the 30.9 GB archive with HTTP range requests (6.3 MB transferred). The bills print two VAT lines
and never their sum, so `tax_amount` is expected to be null: the evaluation only expects what is printed.

**SalorWorks.** Fictional e-commerce invoices from the Gulf: AED, KWD with three decimals, a USD invoice for
a UAE seller, discounts, freight and duty, a two-page invoice. The pack also has five Arabic, bilingual or
scanned invoices; they are raster images with no text layer, which this system rejects by design, so they
are not in the metric set.

**Held-out set.** 16 PDFs with deliberately messy, European layouts: two-column headers, legal name only in
the footer, totals on page two, label and value in separate table columns, several VAT rates, discounts,
French / German / Italian labels, a US invoice, OCR-style noise, a credit note, a prepayment, a currency
stated away from the totals. Each invoice is tagged with its difficulty.

### Sources considered and rejected

| Source | Why not |
|---|---|
| DocILE (Rossum, 6.7k real annotated business documents) | access through a research-only request form, no redistribution: a reviewer could not reproduce it |
| RVL-CDIP (Hugging Face) | scanned 1980s-90s tobacco-litigation images, no text layer (OCR is out of scope), only a document-class label, no fields, 38.8 GB, unclear licence |
| FATURA / FATURA2 (Zenodo 10371464, CC BY 4.0) | 10,000 images from 50 templates, no text layer (OCR is out of scope), labels are bounding boxes rather than field values |
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

`evals/splits.json` records the split: each source is shuffled with a fixed seed and cut in half (IDSEM per
template, the held-out set per batch).

| Split | Mendeley | Mustang | IDSEM | SalorWorks | Held-out | Total | Use |
|---|---|---|---|---|---|---|---|
| dev | 36 | 3 | 15 | 5 | 8 | 67 | failures inspected, bugs fixed |
| test | 36 | 3 | 15 | 5 | 8 | 67 | aggregate metrics only; per-case failures hidden unless `--show-test-failures` |

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
| Haiku pilot on dev | Fields 96% but verdicts 27%: the grounding check rejected correct values (space thousands separators, US dates, bare `$`, evidence split across table columns). Fixed with general rules, each driven by a unit test written from invented inputs (D16) | Same recordings, dev verdicts 27% → 64%. Test not inspected |
| Prompt v3 | Two general instructions: copy numbers in the evidence with their original separators (the model rewrote `$ 802,73` as `$ 802.73`, which the check rightly rejected), and read numeric dates in the issuer's convention | Recordings invalidated and re-recorded on dev |

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

## 7. How the LLM runs are spent: in stages, dev first

Model calls are recorded once and replayed forever after, so every call is paid once. Even so, they are
spent in stages, each one teaching something before the next is paid for. Iteration happens **only on dev**;
the test split is run **once**, at the end, with prompt and code frozen.

| Stage | What | Calls | Purpose |
|---|---|---|---|
| 0. Smoke | cheapest model on 3 dev invoices | 3 | first contact with the real API: schema accepted, parameters accepted, parsing works |
| 1. Pilot | cheapest model on the 44 dev invoices | 44 | find prompt and normalisation failures cheaply |
| 2. Refine | general fixes only; re-record just what changed | as needed | iterate until dev stops improving |
| 3. Compare | the other two models on dev | 88 | decide which models go to test |
| 4. Test | finalists on the 44 test invoices, once | 44–132 | the headline number |

### Model selection rule (fixed before seeing any result)

The default model is **the cheapest one whose dev field exact match and dev verdict agreement are both within
3 percentage points of the best model**, unless its p95 latency is more than twice the best model's. If a
cheaper model ties the most capable one, the cheaper model wins. The hybrid cascade is evaluated with the
chosen model.

## 8. How the document reaches the model

The prompt is only half of what the model sees. The other half is the document itself, and the way it is
turned into model input can lose information before the model reads a word. We measured it instead of
assuming it.

### What the pipeline does by default

1. `pypdf` extracts the text layer of each page (`extract_text()`, "plain" mode). The text follows the
   order in which the PDF draws its runs, not the visual layout.
2. That text goes to the model inside `<document>` tags, after a cached system prompt.
3. The model returns a value and an evidence string per field; the evidence must be found in the same
   extracted text, so every answer is checked against what the document says.

The model never sees the page. Two consequences were visible in dev:

- **Columns come apart.** In the Mendeley template the totals table prints all labels, then all values:
  `Net worth / VAT / Gross worth / 20,00 / 2,00 / 22,00`. In a two-column header, the seller and customer
  blocks are interleaved line by line (`EMISOR CLIENTE` / `Hormigones… Northwind…`).
- **A PDF without a text layer is rejected.** Five of the SalorWorks invoices (Arabic, bilingual, a poor
  scan) are raster images; the pipeline answers `422 unreadable_document`.

### Options

| Mode | What the model receives | Cost per page (from the API docs) | What it can fix | Risk |
|---|---|---|---|---|
| A. Plain text (default) | pypdf plain text | text only (~0.3–1k tokens per invoice here) | — | layout lost |
| B. Layout text | pypdf `extraction_mode="layout"`: runs placed by position, so columns printed side by side stay on one line; padding cut to 3 spaces | about 2× the characters of A | label/value pairing, two-column headers | wide tables wrap; more tokens |
| C. PDF + text | the PDF as a `document` block (the API renders each page as an image and extracts its text) **plus** our text in `<document>` tags; evidence must still be copied from our text | 1,500–3,000 text tokens per page plus the page image (~1.5k visual tokens on Haiku 4.5; up to ~4.8k on Opus 5 / Sonnet 5, which read images at high resolution) | layout, visual cues (bold totals, stamps), and in principle scanned pages | several times the cost of A; evidence may be copied from the rendering and not match our text |

Mode C keeps the verification honest: the model may *look* at the page, but it must *quote* our extracted
text, so the same grounding check applies. Sending only the PDF would make the evidence unverifiable.

### What we measured

Same prompt (v3), same model (Haiku 4.5), same 47 dev invoices; only the input changes.

| Mode | Field exact match | Invoice date | Verdict agreement | Cost / document | p95 latency |
|---|---|---|---|---|---|
| A. Plain text | 97% | 35/47 | 74% | $0.0038 | 8.8 s |
| B. Layout text | 97% | 35/47 | 74% | $0.0040 | 10.3 s |
| **C. PDF + plain text** | **100%** | **46/47** | **94%** | **$0.0060** | 9.6 s |

- **Layout text changes nothing for the model.** Haiku already paired labels and values correctly from
  plain text; its errors were month-first US dates, and layout text does not fix them.
- **Seeing the page fixes the dates.** With the PDF attached, Haiku reads 46 of 47 dates correctly (35
  before). We do not know exactly which visual cue helps; we only report that it does, on this data.
- **The predicted risk showed up once.** In one invoice the model quoted `$ 355.07` from the rendering
  instead of `$ 355,07` from our text, so the grounding check rejected a correct total and the verdict
  became `REVIEW`. The check did its job; the cost is one unnecessary review.
- **Remaining failures all end in `REVIEW`, none in a wrong `PASS`/`FAIL`:** one wrong date caught by the
  date-convention check, one multi-VAT invoice where the model summed two tax lines that are not printed
  as a total, and the evidence case above.
- **Cost:** +57% per invoice on Haiku (image tokens), still under one cent. On Sonnet 5 and Opus 5 the page
  image costs up to ~3× more tokens, so the premium is larger there; stage 3 measures it.
- **Scanned PDFs.** Mode C could read image-only PDFs, but there would be no text to check the evidence
  against, so every field would be unverified. The pipeline keeps rejecting PDFs without a text layer;
  accepting them would need OCR to produce a checkable text, which is out of scope (see Limitations).

**A pitfall found on the way.** With layout text the *heuristic* reaches 100% verdict agreement on
Mendeley dev while its field accuracy drops from 52% to 40%. The layout fixes the date and the totals (label
and value now share a line), but the heuristic takes the column header `Client` as the supplier name, and
the "supplier present" rule is satisfied by any non-empty name. A verdict can be right for the wrong
reason, which is why every report shows field accuracy next to verdict agreement.

