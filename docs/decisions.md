# Design decisions

## How to read this

This service reads a supplier invoice (a PDF or plain text), extracts ten fields, checks them against a
rule config and returns `PASS`, `FAIL` or `REVIEW`, with evidence for each value. The main idea is that
the LLM only **proposes** values. Normalisation, confidence, rules and the verdict are all deterministic
code that checks every proposed value against the document's own text. Each decision below says what
problem it solves, what we chose, what that costs, what we rejected, and what evidence would change our
mind. Every number comes from [evaluation.md](evaluation.md) or from the results files under
`evals/results/`. Start with the table;
read a section only when you want to challenge the decision it covers.

| # | Decision | Chosen | Main alternative rejected | Evidence |
|---|---|---|---|---|
| A1 | Where the LLM sits | LLM proposes; deterministic code decides | LLM returns the verdict | [README architecture](../README.md#architecture) |
| A2 | LLM boundary | Raw-text transport + our own typed validation | SDK `messages.parse` | [test_llm.py](../tests/test_llm.py) |
| A3 | LLM failure | Fall back to the heuristic, say so in the response | HTTP 502 | [test_hybrid.py](../tests/test_hybrid.py), [test_llm.py](../tests/test_llm.py) |
| A4 | Scope | `SUPPLIER_INVOICE`, 10 fields, brief's stack | Other document types, more fields | — |
| A5 | API shape | One URL per operation, JSON or multipart | JSON only | [test_api.py](../tests/test_api.py) |
| A6 | Scanned PDFs | Rejected with 422 | Let the model read the image | [evaluation §8](evaluation.md#8-how-the-document-reaches-the-model) |
| B1 | Provider and offline path | Anthropic, with recorded responses keyed by request hash | A stub without real numbers | [evaluation §7](evaluation.md#7-how-the-llm-runs-are-spent-in-stages-dev-first) |
| B2 | Structured output | JSON schema via `output_config.format` | Free text + regex | [prompts.py](../src/validator/prompts.py) |
| B3 | What the model sees | PDF + our extracted text; evidence must quote our text | Text only | [evaluation §8](evaluation.md#8-how-the-document-reaches-the-model) |
| B4 | Prompt | v4b, chosen by comparing four variants on dev; general instructions only | Keeping the first prompt; tuning to test categories | [evaluation §9](evaluation.md#9-prompt-variants) |
| B5 | Model choice | Rule fixed before results → Opus 5 | Pick after seeing numbers | [evaluation §7](evaluation.md#stage-3-result-the-rule-picks-opus-5) |
| B6 | Call parameters | No server-side model fallback, `effort: low`, no sampling params | Server-side fallback on refusals | [transport.py](../src/validator/transport.py) |
| B7 | Prompt caching | Cache the system prompt | Pad the prompt so Haiku can cache | [evaluation §7](evaluation.md#stage-3-result-the-rule-picks-opus-5) |
| B8 | Hybrid | Heuristic first; LLM only for uncertain or missing brief fields | Call the LLM on any gap | [evaluation §6](evaluation.md#6-final-results-on-the-test-split), [test_hybrid.py](../tests/test_hybrid.py) |
| B9 | Heuristic scope | General fixes only; template-specific labels measured and removed | Keep what scores best on our data | [evaluation §6](evaluation.md#the-heuristic-improved-but-kept-general-on-purpose) |
| C1 | Confidence | Four discrete levels from verifiable signals | Model self-reported score | [test_extraction.py](../tests/test_extraction.py) |
| C2 | Grounding | Evidence must appear in our text, verbatim or line by line | Trust the model's evidence | [test_llm.py](../tests/test_llm.py) |
| C3 | Numeric date order | Decided per document from its own signals | Always day-first | [test_formats.py](../tests/test_formats.py) |
| C4 | Credit notes | Booked negative when the title says credit note | Keep the printed sign | [test_formats.py](../tests/test_formats.py) |
| C5 | Tax total from per-rate lines | Accepted as a sum of printed lines, trusted only if totals reconcile | Reject any computed value | [test_formats.py](../tests/test_formats.py) |
| C6 | Locale coverage | 3-decimal currencies, non-EU tax ids, bare `$` resolved by address | EUR/GBP-only formats | [test_formats.py](../tests/test_formats.py) |
| D1 | `REVIEW` vs `FAIL` | FAIL = document breaks a rule; REVIEW = system is unsure | Binary PASS/FAIL | [test_rules.py](../tests/test_rules.py) |
| D2 | Rule design | Small classes behind a `Protocol` | Registry / DSL | [rules.py](../src/validator/rules.py) |
| D3 | Extra rules | `required_fields`, `amounts_consistent`, `customer_matches` | Only the four minimum rules | [test_rules.py](../tests/test_rules.py) |
| D4 | Reference date | Injectable, defaults to today | Always today | [test_rules.py](../tests/test_rules.py) |
| E1 | Evaluation data | Six third-party/independent sources; author's own invoices excluded | Author-written golden set | [evaluation §1–2](evaluation.md#2-data-sources) |
| E2 | Split and protocol | 80 dev / 80 test, test run once with code frozen | Iterate on all data | [evaluation §4](evaluation.md#4-split-and-protocol) |
| E3 | Label trust | Every label checked against the printed PDF | Trust published labels | [evaluation §3](evaluation.md#3-label-quality) |
| F1 | Configuration | Env vars, fail fast on impossible combinations | Silent defaults | [config.py](../src/validator/config.py) |
| F2 | Logging | JSON lines, request id, never document content | Log payloads | [observability.py](../src/validator/observability.py) |
| F3 | Paid-call cap | `--record` refuses to run without `--max-calls N` | Trust the operator | [test_eval_budget.py](../tests/test_eval_budget.py) |
| F4 | Packaging, Docker, CI | pip + `pyproject.toml`; Docker verified in CI | uv; untested Dockerfile | [ci.yml](../.github/workflows/ci.yml) |

---

## (a) Architecture and boundaries

### A1 — The LLM proposes, deterministic code decides

- **Problem:** an LLM can return plausible but wrong values, and a compliance verdict has to be auditable.
- **Decision:** every extractor (heuristic, LLM, hybrid) returns only raw value + evidence candidates. The
  same deterministic path then normalises, scores confidence, applies the rules and computes the verdict.
- **Why:** a wrong model answer becomes a `REVIEW` instead of a wrong decision. When the models were
  compared on dev, every verdict error of all three was a `REVIEW` on an invoice that should have passed or
  failed ([evaluation §7](evaluation.md#stage-3-result-the-rule-picks-opus-5)); on the final dev split one
  Haiku answer still slips through as a wrong `PASS` (B5). Opus 5 made no wrong `PASS` or `FAIL` on dev or
  test.
- **Rejected:** having the LLM return the verdict, because it cannot be audited or tested deterministically.
- **Revisit if:** a wrong `PASS`/`FAIL` caused by the LLM shows up in evaluation. That would mean the
  checks are too permissive.

### A2 — Two-level LLM boundary: transport, then typed layer

- **Problem:** the failure modes (timeout, rate limit, invalid JSON, refusal) have to be testable without
  calling the API.
- **Decision:** the transport only moves text (the real client, a recording replayer, or a test double).
  A typed layer of our own does `json.loads`, Pydantic validation (`extra="forbid"`), then grounding.
  Refusals, `max_tokens` stops and schema mismatches all raise `LLMInvalidOutput`.
- **Why:** garbage, truncation and timeouts can be injected at the transport. A fake typed client could
  never return invalid JSON, so it could not test these paths.
- **Rejected:** SDK `messages.parse`, because it validates inside the SDK, merges the two levels and makes
  record/replay require faking SDK objects.
- **Revisit if:** we move to a provider whose SDK exposes raw text as easily. The boundary would still
  hold.

### A3 — If the LLM fails, the heuristic answers

- **Problem:** what to return when the LLM times out, errors after retries, refuses or returns invalid
  output.
- **Decision:** `Pipeline` catches `LLMError` and runs the heuristic. The response then shows
  `extractor_used: "heuristic:fallback"` and a warning. Field confidence still sends doubtful values to
  `REVIEW`.
- **Why:** the caller still gets a verdict it can use. Degradation is visible, not silent.
- **Rejected:** HTTP 502, which leaves the caller with nothing. Always forcing `REVIEW` on fallback
  punishes cases the heuristic resolves with full confidence.
- **Revisit if:** fallback verdicts turn out wrong more often than reviewers accept. One option is then to
  force `REVIEW` for fallback cases on layouts the heuristic has never seen.

### A4 — Scope: one document type, ten fields, the brief's stack

- **Problem:** the brief lets us choose the document type, lists six fields as a minimum, and prefers
  Python 3.12 / FastAPI / Pydantic / pytest.
- **Decision:** `SUPPLIER_INVOICE` only; other types are rejected with a clear error. The six brief fields
  plus `subtotal_amount`, `tax_amount`, `customer_name` and `customer_tax_id`. We added a field only if a
  rule uses it (`amounts_consistent`, `customer_matches`). The stack is exactly what the brief names, plus
  ruff.
- **Why:** subtotal/tax catch the classic "subtotal read as total" mistake. The customer fields let a
  platform check who an invoice is addressed to. The stack needs no justification.
- **Rejected:** other document types (we would have to invent a schema the reviewer must learn); a
  document-type registry (over-engineering for one type); extra fields that no rule uses (breadth without
  depth).
- **Revisit if:** a second document type is actually needed.

### A5 — One URL per operation, JSON or multipart by `Content-Type`

- **Problem:** the brief accepts either multipart or JSON with base64/text.
- **Decision:** `POST /v1/validate` and `POST /v1/extract` accept both, and both bodies are declared in
  the OpenAPI schema. Documents are limited to 5 MB (413).
- **Why:** it matches the brief's wording, and `/docs` matches what the service actually accepts.
- **Rejected:** JSON only (simpler, but leaves out an option the brief lists).
- **Revisit if:** no.

### A6 — PDFs without a text layer are rejected

- **Problem:** scanned invoices have no text to check the model's evidence against.
- **Decision:** `422 unreadable_document`. This still holds after B3: the model *could* read a scan, but
  nothing could verify what it read.
- **Why:** accepting scans would mean every field is unverifiable, and grounding (C2) would stop meaning
  anything. The 5 image-only SalorWorks invoices are therefore outside the metric set.
- **Rejected:** letting the model read image-only PDFs (unverifiable); real OCR (out of scope per the
  brief).
- **Revisit if:** OCR is in scope. It would produce a checkable text layer, and the rest of the pipeline
  would stay unchanged.

## (b) Extraction and the LLM

### B1 — Anthropic, with recorded responses as the offline path

- **Problem:** the brief requires a path with no paid credentials, and also asks what was *measured*.
- **Decision:** Anthropic. Each real call is recorded once, keyed by a hash of model, prompt version,
  system prompt, document text, schema and (when sent) the PDF's hash. `LLM_TRANSPORT=replay` serves the
  recordings with no key needed. A changed prompt changes the key, so an old recording misses instead of
  being served. The CI quality gate flags any fallback, which is how a missing recording shows up.
- **Why:** reviewers reproduce real latency, token and cost numbers offline.
- **Rejected:** a deterministic stub only (it would give estimates, not measurements); providers outside
  the brief's list.
- **Revisit if:** a different provider is required. Only the transport would change.

### B2 — Structured output via JSON schema

- **Problem:** free-text model output would need fragile parsing.
- **Decision:** `messages.create` with `output_config.format` (JSON schema). Each field is one nullable
  `{value, evidence}` object, because the API rejects schemas with more than 16 union-typed parameters.
- **Why:** it removes most parse failures. The ones that remain are still caught by our validation (A2).
- **Rejected:** a nullable value plus a nullable evidence per field (20 unions, over the limit).
- **Revisit if:** the schema limit changes, or fields are added.

### B3 — The model sees the PDF and our extracted text; evidence must quote our text

- **Problem:** `pypdf` text follows drawing order, not layout. Table columns and two-column headers come
  apart, so a text-only model may pair labels and values wrongly.
- **Decision:** `LLM_INPUT=pdf` (default). The PDF goes in as a `document` block, followed by our plain
  text in `<document>` tags. The prompt tells the model to copy evidence only from our text.
  `PDF_TEXT=plain` is the default; `layout` and `LLM_INPUT=text` are configurable.
- **Why:** measured on Haiku 4.5, 47 dev invoices, prompt v3: plain text scored 97% fields / 74% verdicts
  at $0.0038 per document; layout text 97% / 74% / $0.0040; PDF + text 100% / 94% / $0.0060. Invoice dates
  went from 35/47 to 46/47 correct. The cost is +57% per invoice on Haiku, and more on Opus/Sonnet, which
  read images at higher resolution. We saw the predicted risk once: the model quoted `$ 355.07` from the
  rendering instead of `$ 355,07` from our text. The check rejected it, and the cost was one unnecessary
  `REVIEW` ([evaluation §8](evaluation.md#8-how-the-document-reaches-the-model)).
- **Rejected:** text only (misreads dates); layout text (no gain for the model, more tokens); PDF only
  (evidence unverifiable).
- **Revisit if:** cost per document matters more than verdict agreement on a stream of clean, known
  layouts, or the ~57%+ premium grows on the chosen model.

### B4 — Prompt: chosen by a controlled comparison on dev

- **Problem:** a prompt changed one fix at a time never shows which instruction helps and which hurts, and
  tuning a prompt on the data it is scored on inflates the score.
- **Decision:** four variants were compared on the same 80 dev invoices, same model (Haiku 4.5, the
  cheapest), same input and code: v3 (the prompt until then), v4a (clearer field rules from dev errors),
  v4b (v4a plus `issuer_country` and `date_format` filled before the fields) and v4c (a control that isolates
  the effect of those two properties). The service uses **v4b**, fixed before the test split was run.
  Every instruction is general; none targets a test case.
- **Why:** v4b scored 99% of fields and 80/80 invoice dates, against 97% and 79/80 for v3. The comparison
  also showed that a sensible-sounding instruction ("decide the country, then read the date") made dates
  worse (74/80); adding the two up-front properties to that same prompt (v4b) brought them to 80/80,
  more than cancelling the harm. A control without either reached 77/80; the properties were not tested
  without the sentence.
  Verdict agreement stayed within two invoices across variants: the remaining `REVIEW`s come from text
  layers the grounding check cannot read, which no prompt fixes
  ([evaluation §9](evaluation.md#9-prompt-variants)).
- **Rejected:** keeping v3 untested; picking a variant by intuition; comparing on Opus (about five times the cost for the same comparison); instructions aimed at test categories (a draft that did so was reverted
  before any model call).
- **Revisit if:** the chosen model changes a lot. The comparison ran on Haiku and the winner was applied
  to Opus to stay within the API budget.

### B5 — Model choice: a rule fixed before any result; it picked Opus 5

- **Problem:** choosing a model after seeing the numbers lets you bend the criterion to the result.
- **Decision:** the rule was written before stage 3: *the default model is the cheapest one whose dev field
  exact match and dev verdict agreement are both within 3 points of the best model, unless its p95 latency
  is more than twice the best model's.* `LLM_MODEL` defaults to `claude-opus-5`.
- **Why:** on dev (67 invoices, PDF + text, prompt v3):

  | Model | Fields | Verdicts | Cost / doc | p95 |
  |---|---|---|---|---|
  | Haiku 4.5 | 96% | 79% | $0.0076 | 10.8 s |
  | Sonnet 5 | 95% | 73% | $0.0140 | 7.7 s |
  | Opus 5 | 98% | 90% | $0.0351 | 8.6 s |

  Haiku is 11 verdict points behind and Sonnet 17, both outside the margin. Sonnet does not beat Haiku here.
  In that comparison no model produced a wrong `PASS`/`FAIL`, so what a cheaper model costs is mainly extra
  manual reviews, not wrong decisions ([evaluation §7](evaluation.md#stage-3-result-the-rule-picks-opus-5)). Replayed with
  today's code the numbers move by a point or two and the choice is the same.
  On the test split, run once with prompt v4b, Opus 5 scored 98% of fields and 95% of verdicts at $0.034 per
  invoice, with no wrong `PASS`/`FAIL` ([evaluation §6](evaluation.md#6-final-results-on-the-test-split)).
- **Why 3 points, and why fixed in advance.** Dev has 80 invoices, so one invoice moves a score by 1.25
  points. A gap of 3 points or less is two invoices: within the noise of a sample this size, so it counts
  as a tie and the cheaper model wins. A wider gap is a real difference in quality. Writing the rule down
  before the runs means the result could not bend the criterion; the latency clause exists because this is
  a synchronous API.
- **Is Opus worth about five times the price? Measured, yes.** Same 80 dev invoices, same prompt (v3),
  same input, replayed with today's code:

  | | Opus 5 | Haiku 4.5 |
  |---|---|---|
  | Cost per invoice | $0.0335 | $0.0073 |
  | Invoices left undecided (`REVIEW` where a `PASS` or `FAIL` was due) | 8 of 80 | 13 of 80 |
  | Wrong decisions | 0 | 1 (an invoice that should `FAIL` got `PASS`) |

  With the final prompt (v4b) Haiku makes no wrong decision but leaves 15 of 80 undecided. Per 1,000
  invoices, Haiku saves about **$26** and adds about **90 manual reviews** (plus, with v3, about a dozen
  wrong `PASS`es). Opus pays for itself as soon as one review costs more than **about $0.30**, which is
  under a minute of a finance clerk's time; a real review (open the PDF, check the fields, decide) takes
  several. A wrong `PASS` costs far more: an invoice paid that should have been rejected. The extra cost of
  Opus is cheaper than the work and the risk it removes.
- **Where the difference is.** On the clean, single-template Mendeley invoices Haiku is as good as Opus
  (94% vs 92% of verdicts). The gap is on hard layouts: on the Spanish utility bills (IDSEM) Opus agrees on
  73% of verdicts, Haiku on 27%. That is the traffic the LLM path is for; clean, recurring layouts should
  not reach an LLM at all (B8, B9).
- **Rejected:** choosing by price alone; choosing after the fact.
- **Revisit if:** the customer's traffic is mostly clean layouts, or a manual review is measured to cost
  under about $0.30. Then Haiku at a fifth of the price is the right trade.

### B6 — No server-side model fallback, `effort: low`, no sampling parameters

- **Problem:** the API can reroute refused requests to another model, and determinism is usually sought
  through `temperature=0`.
- **Decision:** no server-side fallback: a refusal is `LLMInvalidOutput` and triggers the heuristic
  fallback (A3). `effort: low` on Opus 5 and Sonnet 5; Haiku 4.5 rejects the parameter. No sampling
  parameters, because these models reject them.
- **Why:** the model named in the response is always the one that answered, which keeps the per-model
  cost comparison clean. Stability comes from the schema, deterministic validation and recordings, not
  from sampling.
- **Rejected:** server-side fallback (silently changes the model and the reported cost).
- **Revisit if:** refusals become frequent in production.

### B7 — Prompt caching on the system prompt

- **Problem:** the instructions are identical on every call; only the document changes.
- **Decision:** the system prompt is sent with `cache_control: ephemeral`. Cost estimates price cache
  reads at 0.1× and writes at 1.25× input, based on the API's `usage`.
- **Why:** measured over all recorded calls, Opus 5 read the cached instructions on 157 of 160 calls (~24%
  cheaper per invoice) and Sonnet 5 on 66 of 67 (~22%). Haiku 4.5 needs a 4,096-token prefix: 0 hits in 434
  calls, as documented.
- **Rejected:** padding the prompt to reach Haiku's minimum (pays for tokens in order to save tokens); the
  Batch API on the synchronous path (up to 24 h latency; suitable for bulk jobs).
- **Revisit if:** we switch to Haiku, or the prompt grows past 4,096 tokens.

### B8 — Hybrid: call the LLM only when the heuristic is unsure

- **Problem:** the brief asks "heuristic vs LLM vs hybrid". The hybrid only pays off if it skips the LLM
  on some documents.
- **Decision:** run the heuristic first. Call the LLM if any field it found is uncertain
  (0 < confidence < 1), or if one of the six brief fields is missing. A missing optional field does not
  trigger a call. After the call, each field keeps whichever candidate scores higher; ties go to the LLM.
  All three modes are measured on the same data.
- **Why:** measured on test, the hybrid matches the LLM (98% fields, 95% verdicts, no wrong `PASS`/`FAIL`)
  but saves nothing: the general heuristic (B9) is never sure of a whole invoice on these varied layouts,
  so it called the LLM on 80 of 80. With rules written for one frequent template it skipped the LLM on 36
  of 80 invoices at the same verdict agreement and cut the cost per invoice by a third ($0.034 → $0.023).
  That is the case the hybrid is for: a customer's frequent suppliers.
- **Rejected:** calling on any field below 1.0, including missing optional ones (almost every invoice
  would call); per-field LLM calls (more complex, loses cross-field context); shipping the template rules
  that made the hybrid pay on our data (B9).
- **Revisit if:** production traffic concentrates on known templates. The share of `hybrid:heuristic_only`
  responses is the metric to watch.

### B9 — The heuristic stays general: no rules learnt from one template

- **Problem:** the heuristic improves fastest by adding the exact labels of the templates it fails on. On an
  evaluation set whose templates also appear in the test half, that looks like progress but is memory.
- **How we think about it.** In production, invoices with a clear, recurring structure (a customer's
  frequent suppliers) would be handled by rules written for those templates, deterministic and free, and
  would never reach the LLM (B8). What this service has to prove is the other case: invoices with
  unconventional, difficult layouts from suppliers nobody wrote rules for. The evaluation was built to
  measure exactly that (six sources, 21 countries, deliberately hard layouts). Teaching the general
  heuristic the templates of our own evaluation set would only make that measurement lie. Template rules
  are per-customer configuration, not general code.
- **Decision:** only general fixes, each driven by a dev error and covered by a unit test on invented
  inputs: a value on the line after its label, tables printed as labels then values, standard accounting
  labels in German, French, Italian, Portuguese and Dutch, an invoice number must contain a digit, a date
  on the line after its label, a six-line customer block. Two labels found only in the Mendeley template
  (`Net worth`, `Gross worth`) were measured and removed.
- **Why:** with them the heuristic scored 73% of fields and 78% of verdicts on test, and the hybrid saved a
  third of the cost; without them 64% and 55%. The gain was almost all on Mendeley, whose template is in
  both dev and test; on the stress set, whose layouts never repeat, the verdicts did not improve. A
  number learnt from the evaluation data would mislead anyone deploying this on new suppliers
  ([evaluation §6](evaluation.md#the-heuristic-improved-but-kept-general-on-purpose)).
- **Rejected:** keeping the template labels (overfitting to our data); per-template rule files (the right
  tool in production, per customer, but not something to tune on the test set).
- **Revisit if:** a customer's supplier list is known. Rules for its most frequent templates are then
  exactly what makes the hybrid worth it.

## (c) Trust and verification

### C1 — Confidence from verifiable signals, in four levels

- **Problem:** the brief asks for per-field confidence "with your own definition".
- **Decision:** the same scoring applies to every extractor:

  | Confidence | Condition |
  |---|---|
  | 1.0 | normalised, evidence found in the document and containing the value, no competing reading |
  | 0.6 | grounded but ambiguous (e.g. `1.500`, a numeric date with no order signal, a summed tax total) |
  | 0.3 | evidence not in the document, evidence does not contain the value, or value not parseable |
  | 0.0 | not found |

  Any rule that depends on a field below 1.0 returns `REVIEW`.
- **Why:** the levels are explainable, auditable and catch hallucinations. They are conservative, which
  means more `REVIEW`.
- **Rejected:** model self-reported confidence (not calibrated); logprobs (not available with structured
  output, and provider-specific); a continuous score (false precision without calibration data).
- **Revisit if:** labelled production data allows calibration.

### C2 — Grounding: evidence must be in our text and must contain the value

- **Problem:** a model can quote a real line but report a different value, or quote text that does not
  exist.
- **Decision:** evidence must match our extracted text after collapsing whitespace, or, when it spans
  several lines, every line must appear in the text (PDF text layers split table columns). The value must
  then be readable from the evidence: amounts are compared numerically, dates in the document's order
  (C3), names after case and accent folding.
- **Why:** this is what turns model errors into `REVIEW`. The line-by-line rule and the space/NBSP
  thousands separators came from the Haiku pilot, where correct values were being rejected: same
  recordings, dev verdicts 27% → 64% ([evaluation §4, contamination log](evaluation.md#contamination-log)).
- **Rejected:** trusting the model's evidence; fuzzy matching (it would accept near-hallucinations).
- **Revisit if:** unnecessary `REVIEW`s from evidence formatting (like `355.07` vs `355,07`) become a
  measurable share of reviews.

### C3 — Numeric date order is decided per document

- **Problem:** `04/08/2026` is 4 August in Europe and 8 April in the US. The first design read every date
  day-first; every Mendeley invoice is from a US issuer and dates month-first.
- **Decision:** (1) an unambiguous numeric date in the same document (a component above 12) fixes the
  order; (2) otherwise a US postal address means month-first, and `€`, `£` or an EU VAT number mean
  day-first; (3) conflicting or absent signals mean the date is read day-first at 0.6, so the verdict is
  `REVIEW`. The same signals resolve a bare `$` to USD. A model reading that contradicts the document's
  order scores 0.3.
- **Why:** the order is decided by code and not delegated to the model. European invoices behave as
  before.
- **Rejected:** always day-first (wrong for US invoices); marking every date with both parts ≤ 12
  ambiguous (sends most European invoices to `REVIEW`); trusting the model's reading.
- **Revisit if:** new sources show dates misread (for example Canadian issuers, or a mix of conventions in
  one document).

### C4 — Credit notes are booked negative; corrective invoices keep their printed sign

- **Problem:** credit notes often print positive amounts. Booked as positive, a credit becomes a charge.
- **Decision:** if the first 15 non-empty lines carry an unambiguous credit-note title (`credit note`,
  `nota de crédito`, `avoir`, `Gutschrift`…), total, subtotal and tax are negated. Corrective invoices
  (`factura rectificativa`, `korekta`) are excluded on purpose, because they can increase the original
  invoice as well as reduce it. A negative model value is accepted against positive printed evidence only
  on a credit note.
- **Why:** this is the accounting convention: a finance team books the credit as negative whatever sign
  is printed. As a result a credit note fails `total_amount_positive`, which is the rule working as
  written.
- **Rejected:** keeping the printed sign (wrong bookings); negating corrective invoices (wrong when they
  add to the original).
- **Revisit if:** the business wants credit notes to go through a different rule set rather than failing
  `total_amount_positive`.

### C5 — A tax total summed from printed per-rate lines is accepted, and fully trusted only when the totals reconcile

- **Problem:** multi-rate invoices (e.g. IDSEM) print one tax line per rate and never their sum. Models
  add them up, and the check rejects the result as "not printed".
- **Decision:** a `tax_amount` equal to the sum of 2–6 amounts printed in its evidence is accepted at 0.6.
  It rises to 1.0 only when subtotal and total are both at 1.0 and subtotal + tax = total within 0.01. A
  value that is not a sum of printed lines stays ungrounded.
- **Why:** every addend is printed and verifiable, and the cross-check proves the sum. Without that proof
  the field stays in `REVIEW`. IDSEM is where the best model still fails (IDSEM dev verdicts with the earlier prompt: Opus 73%, Haiku 27%, Sonnet 33%;
  Opus on test with the final prompt: 93%).
- **Rejected:** rejecting every computed value (sends every multi-rate invoice to review); trusting any
  sum (easy to hit by coincidence).
- **Revisit if:** the cross-check rejects correct sums often. With prompt v4b the tax total is right on
  79 of 80 dev invoices; the utility bills still end in `REVIEW` because their other amounts cannot be
  verified (scrambled text layer), not because of the tax rule.

### C6 — Locale coverage: three-decimal currencies, non-EU tax ids, symbols

- **Problem:** the GOBL and SalorWorks sources include KWD (three minor digits) and tax ids such as CUIT,
  NIT, RFC and UEN, which the European-only parsers rejected.
- **Decision:** in a document whose currency is KWD, BHD, OMR, JOD, TND, LYD or IQD, `1.500` reads as
  1.500 rather than as an ambiguous thousand. Tax ids accept EU VAT, Spanish NIF, 9-digit ids, and any
  8–20-character token with at least five digits. Prefixed dollars (`A$`, `C$`…) are distinct; a bare `$`
  or `¥` is ambiguous unless resolved (C3).
- **Why:** these are general fixes, made on dev before the test split was frozen, with unit tests written
  from invented inputs. The tax-id fix needed no re-recording.
- **Rejected:** per-country checksum validation (next step, together with a VIES lookup).
- **Revisit if:** false tax-id matches appear. The 8–20/5-digit rule is permissive.

## (d) Rules and verdicts

### D1 — `FAIL` means the document breaks a rule; `REVIEW` means the system is unsure

- **Problem:** the brief asks for `PASS | FAIL | REVIEW` but does not define `REVIEW`, or whether "present"
  means "extracted" or "extracted reliably".
- **Decision:** a field reliably absent (confidence 0.0) → `FAIL`. A doubtful field → `REVIEW`. Precedence
  is FAIL > REVIEW > PASS. Two cases were chosen deliberately: a missing currency when `allowed_currencies`
  is set gives `REVIEW` (the rule does not say "must be present"), and subtotal + tax ≠ total (±0.01) gives
  `REVIEW`, because withholdings such as Spanish IRPF and discounts legitimately break the identity.
- **Why:** it keeps "the document is non-compliant" separate from "a person should look", which is what a
  compliance workflow needs.
- **Rejected:** binary PASS/FAIL (hides uncertainty); `REVIEW` for any missing field (weakens FAIL).
- **Revisit if:** operations says the `REVIEW` rate is too high. Calibrating C1 comes before loosening D1.

### D2 — Rules as small classes behind a `Protocol`

- **Problem:** the brief asks that new rules not require rewriting existing ones, without forcing patterns.
- **Decision:** each rule has an `id` and `evaluate()`, returns `None` when it does not apply, and is
  listed in `DEFAULT_RULES`.
- **Why:** adding a rule means one class and one line.
- **Rejected:** a decorator registry, a plugin loader, a rules DSL in the config.
- **Revisit if:** rules must be configured per customer at runtime.

### D3 — Three rules beyond the brief's four

- **Problem:** the brief's example config has `required_fields`, but none of the four minimum rules uses
  it.
- **Decision:** `required_fields_present` (unknown field names are a 4xx config error),
  `amounts_consistent` (only when all three amounts are present), and `customer_matches` (only when
  `expected_customer_tax_id` is set; `ESB12345678` equals `B12345678`). Overlapping rules each report
  independently.
- **Why:** each one uses evidence the brief's rules ignore. With the brief's config the last one does not
  run, so default verdicts are unchanged.
- **Rejected:** ignoring `required_fields`; merging overlapping failures into one.
- **Revisit if:** duplicate failure messages confuse users.

### D4 — Invoice age is measured against an injectable reference date

- **Problem:** "not older than `max_age_days`" does not say relative to what.
- **Decision:** `reference_date` in the request, defaulting to today. The limit is inclusive. A future
  invoice date is `FAIL`.
- **Why:** the tests and the evaluation set would otherwise change results with the calendar. The
  evaluation gives each case its own date and config (Mendeley invoices are from 2011–2021 and in USD).
- **Rejected:** always today.
- **Revisit if:** no.

## (e) Evaluation and data

### E1 — Six sources the author did not write; the author's invoices excluded

- **Problem:** the first 14 invoices were written by the heuristic's author. The heuristic scored 100% of
  fields on them and about half on invoices written by someone else.
- **Decision:** metrics use only: Mendeley (72, CC BY 4.0, US single template), Mustang (6, German
  ZUGFeRD), IDSEM (30, Spanish electricity bills), SalorWorks (10, Gulf, AED/KWD), GOBL (26, 14 countries,
  credit/corrective notes), and a stress set (16 PDFs written by two isolated agents that never saw the
  code). The 14 author-written invoices are unit-test fixtures only. Every figure is reported per source.
- **Why:** no single template can hide the hard layouts. Rejected sources and the reasons are in
  [evaluation §2](evaluation.md#sources-considered-and-rejected) (DocILE: no redistribution; RVL-CDIP and
  FATURA: images without text).
- **Rejected:** author-written data (circular); Mendeley alone (one template).
- **Revisit if:** real customer documents become available under a data processing agreement. No source
  here is real.

### E2 — 80 dev / 80 test; the test split is run once, with code frozen

- **Problem:** anything tuned against the scoring data inflates the score.
- **Decision:** each source is split 50/50 with a fixed seed (`evals/splits.json`). Failures are inspected
  and fixed only on dev, and fixes must be general, because dev and test share the Mendeley template.
  Test failures are hidden unless `--show-test-failures` is passed. LLM calls are spent in stages (smoke,
  pilot, refine, compare, test). Every exposure to protected content is logged
  ([contamination log](evaluation.md#contamination-log)).
- **Why:** the test number is the only one that measures generalisation.
- **Rejected:** iterating on all data; recording everything at once (pays before learning anything).
- **Revisit if:** the test split is ever used for tuning. It would then have to be replaced.

### E3 — Labels are verified against the printed document

- **Problem:** published labels can be wrong.
- **Decision:** every label must appear in the printed text, and the printed document wins over embedded
  XML/JSON. The stress set was labelled twice, blind.
- **Why:** of 76 Mendeley labels, 4 were wrong or unverifiable (~5%) and were excluded. The stress set's
  blind double labelling agreed on 159/160 fields, and the one disagreement was the second annotator's
  error.
- **Rejected:** trusting published labels.
- **Revisit if:** no.

## (f) Operations

### F1 — Configuration from the environment, fail fast

- **Problem:** a misconfigured deployment should not start and then fail on the first request.
- **Decision:** `EXTRACTOR`, `LLM_MODEL`, `LLM_TRANSPORT`, `LLM_TIMEOUT_S` (30 s), `LLM_INPUT`, `PDF_TEXT`
  and `LOG_LEVEL` are read at startup. Unknown values, or `llm`/`hybrid` with `live` transport and no key,
  raise `ConfigError`. The SDK retries 408/409/429/5xx twice. `.env.example` runs fully offline.
- **Why:** configuration errors show up at deploy time, not in production traffic.
- **Rejected:** silent defaults.
- **Revisit if:** no.

### F2 — Structured JSON logs without document content

- **Problem:** the brief asks for request id, latency, model and verdict in logs, and invoices carry
  personal and commercial data.
- **Decision:** one JSON line per request with request id, latency, extractor, model, token counts,
  verdict, document length and hash, never document content or secrets. Errors never expose stack traces.
- **Why:** logs support monitoring (drift, spend, fallback rate) without leaking data.
- **Rejected:** logging payloads for debugging.
- **Revisit if:** no.

### F3 — Hard cap on paid API calls in the evaluation runner

- **Problem:** a recording run over 160 documents × several models can spend money by mistake.
- **Decision:** `python -m evals.run --record` refuses to start without `--max-calls N`. A `CallBudget`
  wrapper stops the run once N live calls have been made. Replayed calls are free and not counted.
- **Why:** spend is bounded by construction, not by care.
- **Rejected:** relying on the operator.
- **Revisit if:** no.

### F4 — pip + `pyproject.toml`; Docker verified in CI

- **Problem:** the development machine had no Docker, and shipping an untested Dockerfile is worse than
  shipping none.
- **Decision:** `pip install -e ".[dev]"` with bounded versions. GitHub Actions runs ruff, pytest and the
  three quality gates (`--check-baseline`: the heuristic, and the LLM and the hybrid on test, replayed), then runs `docker compose up --build` and polls `/health`.
- **Why:** the reviewer installs no extra tools, and the container is tested on every push.
- **Rejected:** uv (faster, with a lockfile, but one more tool to install); a Dockerfile nobody ran.
- **Revisit if:** reproducible pinned installs matter more than setup friction. A lockfile would then be
  worth adding.

---

## What we would decide differently with more budget

- **Re-run the model comparison with the final prompt.** Models were compared with prompt v3; the prompt was
  then tuned on Haiku and applied to Opus. With v4b Haiku extracts 99% of dev fields, so the gap to Opus may
  be smaller than the 11 verdict points measured with v3.
- **Measure the hybrid on production-like traffic.** Our data is deliberately varied, so the general
  heuristic was never confident; a real customer's stream repeats suppliers and templates. Rules for those
  templates, written from the customer's own documents rather than from the test set, are where the hybrid
  pays (B9).
