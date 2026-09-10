# Rebuilding the external evaluation data

One builder per source. Each reads raw inputs from `--raw-dir` and writes to `--out`, which defaults to
`<system temp>/evals-sources/<source>/`, so running a builder never overwrites the committed labels in
`evals/external/`. To regenerate those on purpose, pass `--out evals/external/<source>` explicitly.
Run from the repository root with the project's virtual environment.

## Labelling policy (all sources)

Full text in [docs/data.md, "How labels were made"](../../docs/data.md#how-labels-were-made).

- **The printed document wins.** A label value the PDF text layer (pypdf) does not show is set to null; a
  value printed differently is overridden with what is printed. Each builder prints these discrepancies.
- `total_amount` is the total with tax. `tax_amount` is the tax total; when only one line per rate is
  printed, it is the sum of those printed lines (IDSEM).
- Credit notes are negative, even when printed without a minus sign (GOBL).
- Tax ids in canonical form, with the country prefix only when it is printed as part of the id.
- The expected verdict is computed by the project's rule engine (`validator.rules`) over the labels, with
  a scenario cycle seeded by `20260910`: two passes, one disallowed currency, one invoice past the
  90-day window (reference date = invoice date + 30 or + 120 days).

## Sources

### Mendeley (`mendeley.py`) — 72 cases

- **Licence:** PDFs CC BY 4.0 (Kozlowski & Weichbroth 2021, doi 10.17632/tnj49gpmtz.2); labels from
  `katanaml-org/invoices-donut-data-v1` on Hugging Face, MIT.
- **Raw data:** `RAW/mendeley/tnj49gpmtz-2.zip` (126.5 MB, "Download all" at
  https://data.mendeley.com/datasets/tnj49gpmtz/2) and `RAW/katanaml/validation.parquet` +
  `RAW/katanaml/test.parquet` (19.9 MB + 10.4 MB, the dataset's `validation` and `test` splits). Download
  by hand; the builder does not download.
- **Extra tools:** `pyarrow` for the `label` step (not a project dependency: `pip install pyarrow`).
- **Command:**

  ```
  python -m evals.sources.mendeley --raw-dir RAW --out OUT
  ```

  `--splits-out evals/splits.json` also rewrites the dev/test manifest; `--steps materialise` reuses an
  existing `RAW/mendeley/labeled.json` without pyarrow.
- **Labels:** katanaml ground truth matched to a PDF by invoice number; the case is dropped when the label
  is empty, a party name disagrees with the PDF, or any date, tax id or amount is not printed.

### Mustang (`mustang.py`) — 6 cases

- **Licence:** Apache-2.0.
- **Raw data:** the ZUGFeRD / Factur-X sample PDFs in `library/src/test/resources` of
  https://github.com/ZUGFeRD/mustangproject (the 11 inspected files total 0.8 MB; the six kept are listed
  in `KEEP`).
- **Command:** `python -m evals.sources.mustang --raw-dir RAW --out OUT`
- **Labels:** from the CII XML embedded in each PDF, checked against the printed text. One override:
  `mst_weclapp` prints a total of 963,12 while the XML says 963.11, so the label is 963.12.
  `LICENSE-DATA.txt` for this source is hand-written, not generated.

### IDSEM (`idsem.py`) — 30 cases

- **Licence:** CC BY 4.0, Zenodo record 6373179.
- **Raw data:** the 30.9 GB `idsem.zip` is never downloaded whole. Its central directory (27 MB) is saved
  as `cdfull.bin`. `index` parses it and unwraps the 32-bit local-header offsets, which wrap past 4 GB
  because the archive is not zip64. `fetch` then range-reads 5 bills (PDF + JSON) per training template,
  chosen with the fixed seed: 6.3 MB transferred (7.4 MB of PDFs once decompressed), capped at 45 MB.
- **Commands:**

  ```
  python -m evals.sources.idsem index --cd cdfull.bin --index RAW/index.json
  python -m evals.sources.idsem fetch --index RAW/index.json --raw-dir RAW      # network
  python -m evals.sources.idsem label --raw-dir RAW --out OUT
  ```

  `cdfull.bin` is the byte range [central directory offset, end-of-central-directory) of the archive. It
  was taken by hand with an HTTP range request; no script here fetches it.
- **Labels:** IDSEM JSON keys mapped as documented in the module docstring. The bills print one VAT/IGIC
  line per rate and no total, so `tax_amount` = N5 + N8, kept only when every non-zero line is printed.

### SalorWorks (`salorworks.py`) — 10 cases

- **Licence:** CC BY 4.0, (c) 2026 Salorworks.
- **Raw data:** a clone of https://github.com/SalorWorks/shopify-invoice-test-pack at commit
  `bb2e531cfa504e6f7200243620121c523f9f7622` (3.3 MB).
- **Command:** `python -m evals.sources.salorworks --raw-dir REPO --out OUT`
- **Labels:** each fixture's `expected.json`, checked against the text layer. Fixtures without a text layer
  (images only) are written to `OUT/scanned/` and are not committed. That covers 5 of the 15 fixtures,
  among them the Arabic and bilingual ones.

### GOBL (`gobl.py`) — 26 cases

- **Licence:** Apache-2.0 (invopop/gobl, invopop/gobl.html).
- **Raw data:** clones of https://github.com/invopop/gobl (commit `4a2e3ac6`, 9 MB) and
  https://github.com/invopop/gobl.html (commit `86aca060`, 6.4 MB) under `RAW/gobl` and `RAW/gobl.html`.
- **Extra tools:** Microsoft Edge (`--edge`, default
  `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`) prints the example HTML to PDF, and `git`
  records the commits in `LICENSE-DATA.txt`.
- **Commands:**

  ```
  python -m evals.sources.gobl --raw-dir RAW --out OUT                      # render + label
  python -m evals.sources.gobl --raw-dir RAW --skip-render --pdf-dir evals/external/gobl --out OUT
  ```

  Edge output is not byte-stable across versions and machines, so labels are reproduced from the committed
  PDFs with `--skip-render`.
- **Labels:** from the GOBL JSON each HTML was rendered from, checked against the PDF text. Two examples
  are dropped (`DROP`): a sole trader that looks like a real person, and a total that contradicts the
  printed amount to pay. Real company names are flagged in `notes`.
