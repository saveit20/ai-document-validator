# Design decisions

Each entry records the context, the decision, the alternatives we rejected and why. Entries are numbered
in the order they were taken; later entries can revise earlier ones, and say so.

## D1 — Document type: `SUPPLIER_INVOICE`

The brief suggests it as the default. Choosing another type would have meant inventing a field schema the
reviewer has to learn, for no extra signal.

## D2 — Stack exactly as the brief asks

Python 3.12, FastAPI + Pydantic, `pyproject.toml`, pytest, ruff. Deviating would need a justification and
buys nothing.

## D3 — Dockerfile and docker-compose, verified in CI

The development machine has no Docker. Rather than ship an untested Dockerfile, CI builds the image, starts
it with `docker compose up` and polls `/health` on every push. Local run instructions with a virtualenv are
also provided.

## D4 — Packaging with pip and `pyproject.toml`

No extra tool for the reviewer to install. uv would be faster and lock versions; dependencies are bounded in
`pyproject.toml` instead.

## D5 — LLM provider: Anthropic, with recorded responses for the offline path

The model is called once over the evaluation set and every response is recorded, keyed by a hash of model,
prompt version, system prompt, document text and schema. Reviewers replay those recordings without an API
key. Changing the prompt changes the key, so stale recordings fail loudly instead of being served silently.

## D6 — Structured output through `output_config.format`, validated by us

The SDK's `messages.parse` validates inside the SDK, which merges transport and validation into one step. We
keep two levels instead: a **transport** that returns raw text (and can be faked to return garbage, time out
or rate-limit) and a **typed layer** that parses JSON, validates it with Pydantic and grounds each value in
the document. That split is what lets the failure modes be tested at all.

## D7 — One URL per operation, JSON or multipart by `Content-Type`

`POST /v1/validate` and `POST /v1/extract` accept both `application/json` (text or base64) and
`multipart/form-data` (file + config). Both bodies are declared in the OpenAPI schema so `/docs` matches
reality.

## D8 — Confidence from verifiable signals, in discrete levels

Model self-reported confidence is not calibrated, and logprobs do not apply to structured output. Every
extracted value is scored the same way, whatever the extractor:

| Confidence | Condition |
|---|---|
| 1.0 | normalised, evidence found verbatim in the document, no competing candidates |
| 0.6 | grounded but ambiguous (competing candidates, or a format such as `1.500`) |
| 0.3 | evidence not in the document (possible hallucination), or found but not parseable |
| 0.0 | not found |

Any rule that depends on a field below 1.0 returns `REVIEW`. Discrete levels are explainable and can be
calibrated later against labelled data; a continuous score without calibration data would be false
precision.

## D9 — Rules as small classes behind a `Protocol`

Adding a rule means writing one class and adding it to `DEFAULT_RULES`; a test adds a rule without touching
the others. No registry, plugin loader or rules DSL: the brief asks not to force patterns.

## D10 — If the LLM fails, fall back to the heuristic

Timeouts, 5xx after the SDK's retries, refusals and invalid output all fall back to the heuristic extractor.
The response says so in `extractor_used` and `warnings`. Returning a 502 would leave the caller without a
verdict it could have had; field confidence still sends doubtful values to `REVIEW`.

## D11 — Three extraction modes, all measured

`heuristic` (free, deterministic, the offline path), `llm`, and `hybrid` — a cascade that runs the heuristic
first and calls the LLM only when some field is below full confidence. The evaluation runs all of them on
the same documents, so "when would you not use an LLM" is answered with numbers.

## D12 — No server-side model fallback, low effort, no sampling parameters

The API offers a server-side fallback that reroutes refused requests to another model. We do not enable it:
it would silently change the model and contaminate the per-model comparison and the reported cost. Opus 5
and Sonnet 5 get `effort: low` (field extraction is shallow work); Haiku 4.5 rejects that parameter. There is
no `temperature=0`: the SDK does not accept sampling parameters on these models, and stability comes from
schema-constrained output, deterministic validation and recorded responses rather than from sampling.

## D13 — Ten fields: the six in the brief plus subtotal, tax and customer

The brief lists the fields as a minimum. We add only fields that enable a rule: `subtotal_amount` and
`tax_amount` for `amounts_consistent` (subtotal + tax = total, otherwise `REVIEW` — withholdings such as
Spanish IRPF legitimately break it), and `customer_name` / `customer_tax_id` for `customer_matches` (only
when the config sets `expected_customer_tax_id`; `ESB12345678` and `B12345678` are the same company).

## D14 — Extraction prompt pre-registered before the evaluation data existed

A later draft of the prompt added instructions aimed at specific difficulty categories of the held-out set.
It was reverted before any model call: tuning the prompt to the test categories would inflate the headline
score.

## D15 — Evaluation data: two independent sources, mixed and split 50/50

Details, numbers and every source we considered are in [evaluation.md](evaluation.md). In short:

- **Mendeley "Samples of electronic invoices"** (Kozłowski & Weichbroth, 2021, CC BY 4.0): PDFs with a text
  layer, labelled with the ground truth of **katanaml-org/invoices-donut-data-v1** (MIT), each label checked
  against the printed PDF.
- **Held-out set**: 16 layout-rich PDFs written by two isolated agents that never saw the extractor, and
  labelled twice blind.
- Each source is split 50/50 with a fixed seed into **dev** (inspected, used to fix bugs) and **test** (never
  inspected; the headline number). The 14 invoices written by the system's author are **excluded from all
  metrics** and kept only as unit-test fixtures, because they are circular.
- No source is real. Freely licensed real invoices do not exist, because real invoices contain personal and
  commercial data; production would use customer documents under a data processing agreement.
