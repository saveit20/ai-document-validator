# Evaluation data: what it covers and why

[evaluation.md](evaluation.md) says how the data is split, scored and reported. This page says what the data
is: why it was assembled this way, what each source adds, how labels were made, and how to rebuild it.

## Why several sources

An extractor tuned on one invoice template looks excellent on that template and fails on the next. The
first evaluation set was written by the system's author: the heuristic scored 100% of fields on it and
about half on invoices written by someone else. So the rule became: **measure on documents the author did
not write, from as many layouts, countries, languages and currencies as can be found with a licence that
allows redistribution**, and report every metric per source so that one large, easy source cannot hide the
hard ones.

Two constraints narrowed the search:

- **Redistributable.** A reviewer must be able to rerun the evaluation, so every document ships in the
  repository. Datasets behind request forms or with non-commercial or unclear licences were rejected.
- **A text layer.** Grounding checks each value against the document's text, and OCR is out of scope.
  Image-only datasets (receipts, scans) cannot be verified and were rejected.

Dozens of candidate datasets and repositories were examined in three search rounds; the rejected ones and
the reasons are listed in
[evaluation.md §2](evaluation.md#sources-considered-and-rejected).

## Coverage

| Source | Invoices | Layouts | Countries | Label language | Currencies | What it stresses |
|---|---|---|---|---|---|---|
| Mendeley | 72 | 1 template | US | English | USD | month-first dates, `$`, table totals split from their labels |
| Mustang | 6 | 6 (ERP and sample layouts) | DE | German | EUR, GBP | German number and date formats, prepayments, two VAT rates, a GBP invoice that prints its tax in EUR |
| IDSEM | 30 | 6 utility templates | ES | Spanish | EUR | 2–4 pages, dates written out in Spanish, VAT or IGIC per rate with no total line, scrambled text order |
| SalorWorks | 10 | 1 family | AE, KW | English | AED, KWD, USD | three-decimal currency, discounts, freight and duty, a USD invoice from a UAE seller |
| GOBL | 26 | 1 family, country variants | ES, FR, PL, DE, IT, PT, GR, MX, CO, AR, SA, SG, US, ZW | English, Spanish, French, Polish | EUR, USD, PLN, MXN, COP, ARS, SAR, SGD | credit notes, corrective and simplified invoices, reverse charge, tax-included prices, withholding, non-EU tax ids |
| Held-out set | 16 | 16 | ES, FR, DE, IT, PT, CH, GB, US | Spanish, English, French, German, Italian | EUR, GBP, USD, CHF | two-column headers, name only in the footer, totals on page 2, distractor totals, OCR-like noise, Swiss number format |

In total: 160 invoices from six sources, about 30 distinct layouts, 18 countries, 12 currencies and 6
label languages. Split 50/50 per source into dev (80) and test (80).

What the set does **not** cover, stated plainly: non-Latin label text that survives PDF text extraction
(the Arabic invoices in SalorWorks are images, and GOBL's Arabic text extracts garbled), scanned documents,
handwritten documents, and real customer invoices. No source is real: freely licensed real invoices do not
exist, because they carry personal and commercial data.

## How labels were made

Every source brings its own ground truth: a third party's labels (Mendeley), structured data embedded in
the PDF (Mustang's EN 16931 XML), the dataset's per-document JSON (IDSEM), the pack's expected values
(SalorWorks) or the invoice data the PDF was rendered from (GOBL). None of it was trusted as is:

1. **The printed document wins.** Every labelled value must appear in the PDF's text; a label the PDF does
   not show, or contradicts, is corrected to what is printed or set to null. Even the published
   third-party labels were about 5% wrong.
2. **One labelling policy for every source**, written before any data was scored and applied the way a
   finance team would book the invoice:
   - dates as `YYYY-MM-DD`, in the issuer's convention;
   - `total_amount` is the invoice total with tax, not a balance still due after a prepayment;
   - `tax_amount` is the tax total; when the invoice prints one line per rate and no total, it is their sum;
   - credit notes are negative, even when printed without a minus sign;
   - tax ids in canonical form, with the country prefix only when it is printed as part of the id.
3. **The expected verdict is computed, not guessed**: the labelled values are run through the same rule
   engine, with a rule config and reference date chosen per case so that the set contains passes, invoices
   in a disallowed currency, and invoices that are too old.

## Rebuilding the data

The scripts that built each source are in `evals/sources/`, with the exact commands, what each one
downloads and which tools it needs. Each writes to a work directory by default, so a rebuild cannot
silently overwrite the committed labels. Licences and attributions are in each source's
`LICENSE-DATA.txt` under `evals/external/`.
