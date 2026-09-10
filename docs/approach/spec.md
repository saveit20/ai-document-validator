# Specification — output of phase 1 (UNDERSTAND)

> Internal working document. Code and README are written in English (C-01).
> Every requirement cites the brief.

## 1. Restatement

A Python HTTP service that receives a supplier invoice (text or PDF with embedded text) and a rules
configuration; extracts six typed fields with per-field confidence and evidence; evaluates configurable
business rules and returns a `PASS | FAIL | REVIEW` verdict with the detail of each rule. It comes with
an evaluation harness over our own golden set that measures the quality of the extraction and of the
verdict. It must work without paid credentials. The actor is a downstream system of a B2B compliance
platform that needs to be able to trust the result or dispute it.

## 2. What is asked vs. what is evaluated

The brief is unusually explicit about how it scores. Three areas weigh **High**:

| Evaluated area (weight) | What the reviewer must see in the repo |
|---|---|
| Problem framing & trade-offs (High) | A reasoned heuristic vs LLM vs hybrid decision, **backed by numbers from the eval**, not by opinion |
| Extraction + rules design (High) | Rules extensible without rewriting existing ones; strict typing; LLM failures handled |
| Evaluation mindset (High) | A golden set with genuinely hard cases and honest metrics, failures included |
| Production instincts (Medium) | Timeouts, structured logging, offline stub, measured latency and cost |
| Code quality & tests (Medium) | Tests that protect behaviour, not ceremony |
| AI-assisted workflow (Medium) | `AI_USAGE.md` with rejected AI suggestions and why |
| Communication (Medium) | README reviewable in 15 minutes |

Sentence from the brief that sums up the bet: *"Prefer depth over breadth. A sharp, well-tested core
beats a half-finished LLM playground."*

## 3. Data reconnaissance

**There is no data.** The only attachment is the brief. No invoice or dataset has been provided.

Consequences:

- There is no `analysis/` to do: it is not created (the working protocol (summarised in
  `docs/process.md`), §5, last rule).
- **We design the golden set ourselves.** This is now the data work of the challenge, and the
  "Evaluation mindset" area weighs High.
- **Circularity risk**: if we write the invoices and the extractor at the same time, the extractor ends
  up fitted to our own fixtures and the metrics come out inflated. Mitigation: the fixtures and their
  labels are written **before** the extractor, with deliberate variety and cases designed to break it;
  and failures are reported, not hidden. The brief scores "metrics honesty".
- **Personal data**: the fixtures are synthetic; there is no real data. Even so, in production an
  invoice from a self-employed person contains a natural person's tax ID (NIF). The README documents
  what is sent to the LLM provider (`ai-standards.md` §9).

Minimum variety the golden set must cover (made concrete in phase 2):

| Axis | Cases |
|---|---|
| Date format | ISO, `DD/MM/YYYY`, `15 March 2026`, `March 15, 2026` |
| Amount format | `1,234.56`, `1.234,56`, symbol before/after, no decimals |
| Currency | ISO code, symbol (`€`, `£`, `$`), absent |
| Tax ID | EU VAT (`ESB12345678`, `GB123456789`), absent |
| Expected verdict | PASS, FAIL due to old date, FAIL due to disallowed currency, FAIL due to amount ≤ 0, REVIEW due to ambiguous field |
| Traps | several amounts (subtotal, VAT, total), several dates (issue, due), customer name next to the supplier's |
| Input | plain text and at least one PDF with embedded text |

## 4. Input/output contract

Functional contract; the exact Pydantic schemas are fixed in phase 2.

### Inputs

| Input | Type | Required | Validation |
|---|---|---|---|
| document | PDF bytes with embedded text, or plain text | yes | not empty; maximum size; readable PDF |
| metadata | free-form object (e.g. file name) | no | — |
| config | JSON: `document_type`, `max_age_days`, `allowed_currencies?`, `required_fields?` | yes | supported `document_type`; `max_age_days` integer > 0; ISO 4217 codes |

### Outputs

**Extraction**: for each of the six fields → `value` (typed and normalised, or `null`),
`confidence` (own, documented definition), `evidence` (fragment of the source text, optional),
`page` (optional).

**Verdict**: `status` (`PASS | FAIL | REVIEW`), `rules` (list of `{id, passed, message}`), the full
extraction, and `llm` (`model`, `latency_ms`, `input_tokens`, `output_tokens`) **only if an LLM was
used**.

**Errors**: JSON with code and message; never a raw traceback. Unreadable document or invalid config →
4xx. LLM provider failure → controlled error (code to be decided in phase 2).

## 5. Functional requirements

| ID | Requirement | Type | Source |
|---|---|---|---|
| FR-01 | Accept the document as PDF or text, plus optional metadata | MUST | "Input: PDF bytes or plain text + optional metadata" |
| FR-02 | Extract `supplier_name`, `invoice_number`, `invoice_date` (ISO), `total_amount` (number), `currency` (ISO 4217), `tax_id` | MUST | table "Fields to extract (minimum)" |
| FR-03 | Typed output with value, defined and documented per-field confidence, and optional evidence | MUST | "typed structured object ... per-field confidence (your definition — document it)" |
| FR-04 | Offline path without paid credentials | MUST | "You must also support a offline/dev path" |
| FR-05 | LLM extraction (OpenAI / Anthropic / Bedrock) | OPTIONAL | "You may use an LLM API" |
| FR-06 | Rule: `invoice_date` present and not older than `max_age_days` | MUST | "Minimum rules" 1 |
| FR-07 | Rule: `total_amount` present and > 0 | MUST | "Minimum rules" 2 |
| FR-08 | Rule: `supplier_name` present and not empty | MUST | "Minimum rules" 3 |
| FR-09 | Rule: if `allowed_currencies` is given, `currency` must be in the list | MUST | "Minimum rules" 4 |
| FR-10 | Rule: fields in `required_fields` present | MUST (interpretation, ASSUMPTION-04) | example config: `"required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"]` |
| FR-11 | Rules extensible without rewriting existing ones | MUST | "Design the rule evaluation so new rule types can be added without rewriting existing ones" |
| FR-12 | Verdict with status, per-rule results, extracted fields and LLM metadata if one was used | MUST | "Verdict response should include at least" |
| FR-13 | `POST /v1/validate` with a documented contract | MUST | HTTP API table + "Document the contract" |
| FR-14 | `GET /health` | MUST | HTTP API table |
| FR-15 | `POST /v1/extract` | OPTIONAL, valued | "Optional but valued" |
| FR-16 | OpenAPI consistent with reality | OPTIONAL, valued | "Optional but valued" |
| FR-17 | Structured JSON logging (request id, latency, model, verdict) | OPTIONAL, valued | "Optional but valued" |
| FR-18 | Golden set ≥ 5 fixtures + a command that reports per-field metrics, verdict agreement and failures | MUST (non-negotiable) | "Evaluation harness (non-negotiable)" |
| FR-19 | README: how to run the API and the eval, decisions, trade-offs, next day, example request/response | MUST | "What to deliver" 2 and 6 |
| FR-20 | README: when not to use an LLM, measured or estimated latency/cost, what to monitor | MUST | "Cost, latency, and risk notes" |
| FR-21 | `AI_USAGE.md` with tools, 1–2 rejected suggestions, verification, extraction prompts | MUST | "AI usage requirements" |
| FR-22 | Unit tests for the rules + at least one API or pipeline integration test | MUST | "What to deliver" 4 |
| FR-23 | Additionally extract `subtotal_amount`, `tax_amount`, `customer_name`, `customer_tax_id` | EXTENSION (DEC-13; DEC-xx IDs refer to the working decision log, whose final form is `docs/decisions.md`) | "Fields to extract (minimum)" |
| FR-24 | Rule `amounts_consistent`: subtotal + taxes = total (±0.01), otherwise → REVIEW | EXTENSION (DEC-13) | "Enough evidence to trust (or dispute) the result" |
| FR-25 | Rule `customer_matches` with optional `expected_customer_tax_id` in the config | EXTENSION (DEC-13) | same |
| FR-26 | Eval on two sets (dev and independent holdout) with a breakdown by difficulty | MUST (eval quality, DEC-14) | "Golden set quality, metrics honesty" |

## 6. Non-functional requirements

| ID | Requirement | Source |
|---|---|---|
| NFR-01 | Python 3.12+, FastAPI + Pydantic, pyproject.toml, pytest, public type hints | C-02 to C-05 |
| NFR-02 | Runnable locally by a reviewer without friction | C-06, "README that a teammate can run" |
| NFR-03 | No secrets in the repo | C-07 |
| NFR-04 | Timeouts and provider failures handled | "Production instincts: Logging, timeouts, stubs" |
| NFR-05 | Latency and cost per document measured or estimated | FR-20 |
| NFR-06 | LLM provider swappable behind an interface | "keep adapters swappable", "deterministic stub behind an interface" |

## 7. Acceptance criteria

| AC | Covers | Check |
|---|---|---|
| AC-01 | FR-01 | The same invoice as text and as PDF produces the same extraction |
| AC-02 | FR-02, FR-03 | For each fixture, the output validates against the schema and carries confidence on every field |
| AC-03 | FR-04 | With no keys in the environment, `validate` and the eval work end to end |
| AC-04 | FR-06 | Date 91 days old with `max_age_days=90` → rule fails; 90 → passes; absent → fails or REVIEW according to ASSUMPTION-03 |
| AC-05 | FR-07 | `0`, negative and absent → the rule fails; `0.01` → passes |
| AC-06 | FR-08 | `""` and whitespace only → fails |
| AC-07 | FR-09 | Currency outside the list → fails; without `allowed_currencies` → the rule is not evaluated or passes |
| AC-08 | FR-11 | Adding a new rule does not require touching the code of existing ones (shown in a test or in the README) |
| AC-09 | FR-12 | The response includes `llm` with model, latency and tokens when an LLM was used, and does not include it when not |
| AC-10 | FR-13 | Integration test of `POST /v1/validate` with a 200 response and the correct verdict |
| AC-11 | FR-13 | Invalid config or unreadable document → 4xx with a message, no traceback |
| AC-12 | FR-05 | Corrupt LLM output (invalid JSON, missing field) or timeout → controlled error, tested with a fake transport |
| AC-13 | FR-18 | One command reproduces the eval metrics, without network, and lists failures case by case |
| AC-14 | NFR-03 | No keys in the repository or in the git history |

## 8. Deterministic / LLM boundary

This is the central question of the challenge: *"You choose the simplest approach that meets the goal
(heuristic vs LLM vs hybrid) and can explain why"*.

| Piece | Nature | Why |
|---|---|---|
| Extract text from the PDF | Deterministic | PDF library; no OCR (out of scope) |
| Normalise dates, amounts, currencies | Deterministic | Known format rules; an LLM here is expensive and less reliable |
| Business rules and verdict | Deterministic | They are the client's explicit rules; they must be auditable and repeatable |
| Evaluation harness | Deterministic | It has to be reproducible |
| `invoice_date`, `total_amount`, `currency`, `tax_id` | Heuristic viable | Regular patterns; the challenge is choosing *which* date or amount, not reading it |
| `supplier_name`, `invoice_number` | Where an LLM adds most | They depend on layout and semantic context: "who issues" versus "who is billed" |

Design hypothesis to be decided in phase 2 (not now): **measurable hybrid**. A deterministic heuristic
extractor, which is both the mandatory offline path and the baseline; an optional LLM extractor behind
the same interface; deterministic normalisation and verification after both. The eval runs both on the
same golden set, and the comparison answers *"when would you not use an LLM"* with numbers.

## 9. Risks and failure modes

| Area | What can fail | Impact | Mitigation |
|---|---|---|---|
| Golden set | Circularity: fixtures tailored to the extractor | High: invalidates the eval | Fixtures and labels before the extractor; trap cases; failures reported |
| LLM | No API key in the environment | High: no real latency/cost numbers | Decision P-02 |
| LLM | Invalid JSON, missing field, invented value | High | Schema + check that the evidence appears in the text |
| LLM | Timeout, 429, 5xx | Medium | Timeout + backoff only on transient errors + controlled error |
| Extraction | Confuses subtotal with total, due date with issue date, customer with supplier | High | Trap cases in the golden set; low confidence → REVIEW |
| Input | Scanned PDF without text | Medium | Explicit "no extractable text" error; OCR out of scope |
| Input | Invalid, empty or huge document or config | Medium | Validation at the edge, size limit |
| Rules | `max_age_days` depends on "today": tests that expire | Medium | Injectable reference date (ASSUMPTION-05) |
| Delivery | Private working notes ending up in the delivered repo | Medium | Decision P-01 |
| Time | Building too wide | High | "Prefer depth over breadth"; list of exclusions in phase 2 |

## 10. Assumptions

Recorded in `assumptions.md` (ASSUMPTION-01 to 07).

## 11. Initial decisions

Recorded in the working decision log, whose final form is `docs/decisions.md` (DEC-01 to 04).
Decisions that belong to the author are tracked in the status board (a private working file), under
"Decisions pending for the author".
