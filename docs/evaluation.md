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
| GOBL example invoices (`evals/external/gobl/`) | third party (invopop), rendered to PDF by this project | Apache-2.0 | 26 | dev + test |
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

**GOBL.** Example invoices from an open-source e-invoicing library, covering 13 countries (Spain, France,
Poland, Germany, Italy, Portugal, Greece, Mexico, Colombia, Argentina, Saudi Arabia, Singapore, the US and
Zimbabwe), 9 currencies, labels in English, Spanish, French and Polish, and credit notes, corrective and
simplified invoices, reverse charge, tax-included prices and withholding. The library ships the rendered
HTML of its examples; we printed it to PDF with a headless browser, so the PDFs have a real text layer and
the structured JSON is the ground truth, checked against the printed text. It adds many locales but a single
layout family. Two examples were left out: one names what looks like a real private person, and one prints a
total that its data does not support.

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

| Split | Mendeley | Mustang | IDSEM | SalorWorks | GOBL | Held-out | Total | Use |
|---|---|---|---|---|---|---|---|---|
| dev | 36 | 3 | 15 | 5 | 13 | 8 | 80 | failures inspected, bugs fixed |
| test | 36 | 3 | 15 | 5 | 13 | 8 | 80 | aggregate metrics only; per-case failures hidden unless `--show-test-failures` |

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
| Heuristic fixes after the test run | General fixes designed on dev errors only; heuristic and hybrid then re-run on test (a second look, for these two configurations only). A version with template-specific labels was measured and rejected as overfitting | Test figures for the heuristic and the hybrid in §6 are from this second run; the LLM figures are unchanged |
| Finance labelling policy | IDSEM and GOBL labels were aligned with the pre-registered guide (tax total summed from per-rate lines, credit notes negative), by rule and without looking at any test output | The heuristic's IDSEM field score fell from 43% to 37% (it does not sum tax lines); its quality-gate baseline was lowered accordingly, with this reason |
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

## 6. Final results on the test split

Run once, after the model (§7), the input (§8) and the prompt (§9) had been chosen on dev and the code was
frozen. `python -m evals.run --extractor llm --model claude-opus-5 --split test` replays it.

| Configuration | Field exact match | Verdict agreement | Verdict errors | Mean / p95 latency | Cost / invoice |
|---|---|---|---|---|---|
| Heuristic | 64% | 55% | 36: 26 `FAIL` (25 on valid invoices), 10 `REVIEW` | 0.11 s / 0.44 s | $0 |
| **Opus 5, PDF + text, prompt v4b** | **98%** | **95%** | 4, all `REVIEW` | 7.0 s / 10.9 s | $0.034 |
| Hybrid, heuristic then Opus 5 | 98% | 96% | 3, all `REVIEW` | 7.0 s / 10.9 s | $0.034 |

Opus 5 per source (fields / verdicts): Mendeley 100% / 100%, Mustang 97% / 100%, IDSEM 100% / 93%,
SalorWorks 94% / 100%, GOBL 95% / 77%, held-out 98% / 100%.

- **No wrong `PASS` or `FAIL`.** Of the four disagreements, three are invoices that should have passed and
  one that should have failed; the system sent all four to a person instead of deciding wrongly.
- **Test is better than dev (95% against 90%)**, because the dev figure for Opus was measured with the
  earlier prompt (v3) and the test run uses v4b. We report both rather than re-running dev, which would have
  cost another ~$2.7.
- **The weakest source is GOBL** (13 test invoices), the one with the most countries and document types.
  Per-case failures on test stay hidden by design.
- **The hybrid saves nothing with a general heuristic**: it called the LLM on all 80 invoices.

The heuristic fails the other way: it wrongly rejects 25 of the 80 test invoices. On layouts it was not
written for it misses a required field, and a field that is reliably absent is a `FAIL`. It never wrongly
passes an invoice, but a system that rejects a third of valid invoices is not usable on varied layouts,
which is why the LLM path exists.

### The heuristic: improved, but kept general on purpose

After the test run the heuristic was improved with general fixes, each driven by a dev error and covered by
a unit test written from invented inputs: a value printed on the line after its label, tables printed as
all labels then all values, total/net/tax and invoice-number labels in German, French, Italian,
Portuguese and Dutch, an invoice number must contain a digit, a date on the line after its label, and a
six-line customer block. Then the heuristic and the hybrid were run on test a second time (declared in the
contamination log).

| Heuristic on test | Fields | Verdicts | Hybrid: invoices without an LLM call | Hybrid cost / invoice |
|---|---|---|---|---|
| Before the fixes | 50% | 55% | 0 of 80 | $0.034 |
| **General fixes (shipped)** | **64%** | **55%** | 0 of 80 | $0.034 |
| General fixes + the Mendeley template's own labels (`Net worth`, `Gross worth`) — not shipped | 73% | 78% | 36 of 80 | $0.023 |

Per source, the template-specific version gained almost only on Mendeley (verdicts 50% → 100%), whose
template is in both dev and test; on the held-out set, the only source whose layouts never repeat
between dev and test, it found more fields (64% → 78%) but its verdicts did not improve. Those two labels
are not standard accounting vocabulary; they are that template's wording. Keeping them would have turned
the hybrid into a 33% saving on our data by learning the evaluation set, so they were removed: the
service must work on invoices we have not seen. The measurement stays here because it shows exactly when
the hybrid pays — once rules exist for a customer's frequent templates.

**What the whole evaluation cost:** 661 recorded calls (Haiku 4.5 434, Sonnet 5 67, Opus 5 160), about
$9.40, including every experiment.

## 7. How the LLM runs are spent: in stages, dev first

Model calls are recorded once and replayed forever after, so every call is paid once. Even so, they are
spent in stages, each one teaching something before the next is paid for. Iteration happens **only on dev**;
the test split is run **once**, at the end, with prompt and code frozen.

| Stage | What | Calls | Purpose |
|---|---|---|---|
| 0. Smoke | cheapest model on 3 dev invoices | 3 | first contact with the real API: schema accepted, parameters accepted, parsing works |
| 1. Pilot | cheapest model on the dev invoices (44 at the time; dev grew to 80 as sources were added) | 44 | find prompt and normalisation failures cheaply |
| 2. Refine | general fixes only; re-record just what changed | as needed | iterate until dev stops improving |
| 3. Compare | the other two models on dev | 88 | decide which models go to test |
| 4. Test | the chosen model and prompt on the 80 test invoices, once | 80 | the headline number |

### Model selection rule (fixed before seeing any result)

The default model is **the cheapest one whose dev field exact match and dev verdict agreement are both within
3 percentage points of the best model**, unless its p95 latency is more than twice the best model's. If a
cheaper model ties the most capable one, the cheaper model wins. The hybrid cascade is evaluated with the
chosen model.

### Stage 3 result: the rule picks Opus 5

Dev as it was at that point (67 invoices, before the GOBL source was added), PDF + text input (§8),
prompt v3, all replayed with the same code. On the final 80-invoice dev split, Opus 5 with v3 scores 97%
of fields and 90% of verdicts.

| Configuration | Field exact match | Verdict agreement | Cost / document | p95 latency |
|---|---|---|---|---|
| Heuristic | 48% | 40% | $0 | 0.44 s (mean 0.11 s, PDF parsing included) |
| Haiku 4.5 | 96% | 79% | $0.0076 | 10.8 s |
| Sonnet 5 | 95% | 73% | $0.0140 | 7.7 s |
| **Opus 5** | **98%** | **90%** | $0.0351 | 8.6 s |
| Hybrid (heuristic → Opus 5) | 98% | 88% | $0.0351 | 8.6 s |

- **The rule selects Opus 5.** Haiku is 11 verdict points behind and Sonnet 17, both outside the 3-point
  margin. Sonnet does not beat Haiku on this data despite costing twice as much.
- **No model produced a wrong `PASS` or `FAIL`.** Every verdict error of every model is a `REVIEW` on an
  invoice that should have passed or failed: when the model is wrong, the grounding check catches it.
  The cost of a weaker model is more manual reviews, not wrong decisions.
- **The hybrid saves nothing here** (with the heuristic of that time; see §6 for the final one). On these varied layouts the heuristic is never confident about every
  field, so the cascade calls the LLM on 67 of 67 invoices. It would pay off on a stream dominated by a few
  known, clean templates, where the heuristic alone reaches full confidence (see the README on when not to
  use an LLM).
- **Prompt caching, measured.** Opus 5 and Sonnet 5 each read ~2,240 cached tokens on 66 of 67 calls (the
  first call writes the cache). On Opus 5 that saves ~$0.010 per invoice, about 22% of what it would cost
  uncached; on Sonnet 5, ~$0.004, also ~22%. Haiku 4.5 needs a 4,096-token prefix: 0 cache hits in 181
  calls, as the documentation predicts. LLM latencies above are API time; PDF parsing adds the heuristic's
  ~0.1 s.
- **Where the best model still fails:** the IDSEM bills print two VAT lines and never their sum; models
  often add them up (a value not printed, rejected by the check), and the scrambled text layer of those
  bills makes some evidence unverifiable. Both end in `REVIEW` (IDSEM verdicts: Opus 73%, Haiku and Sonnet
  27%).

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

Same prompt (v3), same model (Haiku 4.5), same 47 dev invoices (the dev split at that point); only the
input changes.

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

**A pitfall found on the way (heuristic).** With layout text the *heuristic* reaches 100% verdict agreement on
Mendeley dev while its field accuracy drops from 52% to 40%. The layout fixes the date and the totals (label
and value now share a line), but the heuristic takes the column header `Client` as the supplier name, and
the "supplier present" rule is satisfied by any non-empty name. A verdict can be right for the wrong
reason, which is why every report shows field accuracy next to verdict agreement.

## 9. Prompt variants

The prompt had changed three times (v1 written before any data, v2 for an API schema limit, v3 with two
fixes from dev errors), but always one fix at a time. Before spending the test budget we compared variants
side by side: same model (Haiku 4.5, the cheapest, to stay within budget), same 80 dev invoices, same input
(PDF + text), same code. Each variant is in [`evals/prompt_variants.py`](../evals/prompt_variants.py) and
can be replayed with `python -m evals.run --extractor llm --model claude-haiku-4-5-20251001 --split dev
--prompt <variant>`.

| Variant | What changes | Fields | Invoice dates | Tax total | Verdicts | Cost / doc |
|---|---|---|---|---|---|---|
| v3 | the prompt used until then | 97% | 79/80 | — | 82% | $0.0073 |
| v4a | clearer field rules from dev errors: names without address, the taxable base defined, tax total summed from per-rate lines, credit notes negative, and "decide the issuer's country before reading a date" | 98% | 74/80 | 78/80 | 80% | $0.0074 |
| v4b | v4a, and the schema asks for `issuer_country` and `date_format` **before** the fields | **99%** | **80/80** | 79/80 | 81% | $0.0076 |
| v4c (control) | v4a with v3's date sentence and no preamble | 99% | 77/80 | 77/80 | 82% | $0.0074 |

**Chosen: v4b.** It has the best field accuracy and the only perfect date score; its verdict agreement is
one invoice in 80 below v3 and v4c, which is within noise. The control v4c shows where the date gain
comes from: removing v4a's harmful sentence recovers most of it (74 → 77), and the preamble adds the last
three (77 → 80). v4b is the service prompt (`src/validator/prompts.py`); the other variants remain in
`evals/prompt_variants.py` so their recordings stay replayable. The prompt was compared on Haiku to keep
within the API budget and then applied to Opus 5, the model the selection rule picked; Opus dev numbers
in §7 are with v3.

What we learned:

- **An instruction that sounds right can make things worse.** v4a's sentence "decide the issuer's country,
  then read the date in that country's convention" doubled down on the wrong convention: US dates misread
  went from 1 to 6.
- **Making the model write its reasoning into the output fixes it.** v4b asks for the issuer's country and
  the date format as the first two properties of the JSON. Having committed to `MM/DD/YYYY` in writing, the
  model then read all 80 dates correctly. Those two properties are dropped before validation.
- **Clearer field definitions help the fields that were ambiguous**: the tax total went from mostly wrong
  (v3 told the model never to compute) to 79/80 once the finance rule was stated.
- **Verdicts barely move, and that is informative.** The remaining `REVIEW`s are the Spanish utility bills,
  whose scrambled text layer makes evidence unverifiable. No prompt fixes that; it is a limitation of the
  grounding check, and it fails safe.

