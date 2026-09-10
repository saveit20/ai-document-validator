# How the work was run

This project was built in 24 hours with AI coding assistants. To keep that honest, the work followed a
written protocol from the first minute. This page is the English summary of the rules that governed the
work; the working files themselves (status board, phase checklists, decision log drafts) are the author's
private notes and are not part of the deliverable. What the assistants did, and what was rejected, is in
[AI_USAGE.md](../AI_USAGE.md).

## Principles

- **The brief is the only source of truth.** It was transcribed word for word and re-checked against the
  PDF before any design. When a choice was unclear, the question was "what does the brief value?", not
  "what is most impressive?" ("Prefer depth over breadth").
- **Nothing is claimed without evidence.** A step is done when a test, a command output or a measurement
  says so, never because it "looks right". Every number in the documentation was checked against a
  replayed run before submission.
- **The LLM is an untrusted dependency.** It proposes; deterministic code verifies and decides
  ([decisions.md](decisions.md) A1). The same rule applied to the coding assistants: their output was
  accepted only after tests, evaluation or an independent review.
- **Say what was not done.** A limitation stated with its reason is worth more than a feature done badly.

## Phases and exit criteria

Each phase ended with a gate. A gate passed only with written evidence, and work never skipped ahead of an
open gate. Going back was allowed and expected: when reality contradicted the plan, the plan changed, in
writing.

| Phase | Exit criterion | What it produced here |
|---|---|---|
| 1. Understand | Requirements traced to the brief; input/output contract; acceptance criteria; assumptions listed | 22 requirements with brief quotes, 14 acceptance criteria, the `REVIEW` vs `FAIL` meaning settled by the author |
| 2. Plan | Architecture, the deterministic/LLM boundary, an incremental plan, what is left out | The design (LLM proposes, code decides), 8 increments, a stated cut order if time ran short |
| 3. Build | The critical path runs end to end and is verified | The service, the rules, the three extractors, tests first where behaviour was specified |
| 4. Evaluate | Tests plus a measured evaluation of the AI behaviour | Six sources, a frozen dev/test split, stage-by-stage paid runs, CI quality gates |
| 5. Harden and deliver | Adversarial review, a reproducible delivery | Fresh-clone run, fact-check of every number, a brief-compliance check of the running code |

Examples of going back, all recorded in the docs: the author-written test invoices were dropped from
every metric once the heuristic scored 100% on them (circular); the way the document reaches the model was
re-opened after the first model runs and changed the default (evaluation §8); the prompt was compared
side by side before the test budget was spent (evaluation §9).

## Who decides what

The assistants did most of the writing. Decisions that change **what is delivered** or **what it costs**
were the author's; decisions about **how it is built inside** were delegated, and explained.

| The author decided | Delegated to the assistant, and explained |
|---|---|
| Scope and where to cut it | Module and function structure |
| The stack where the brief leaves it open, and the LLM provider | Input and output validation |
| Every assumption that changes delivered behaviour | Test design and evaluation mechanics |
| Data: which sources, licences, the labelling policy | Prompt wording (then compared by measurement) |
| The API budget and each paid run | Error handling and reliability |
| Model choice rule, final sign-off | Documentation wording |

## Stop points

The assistant did not run the project end to end on its own. It stopped and waited for the author at:
the end of Understand (requirements, assumptions, no solution code yet), the end of Plan (architecture and
what was left out), a mid-time checkpoint (is the critical path running? if not, cut scope), before every
paid LLM run (what it measures, how many calls, what it costs), and before delivery (README and
acceptance checklist). At each stop the assistant explained what it had done and why, in plain language.

## Working rules

- **Scope control.** Before adding a dependency, layer or service, two questions: is it needed for a
  requirement or does it remove a real risk, and can it be defended in two minutes? If either answer was
  no, it was not added. This kept out queues, vector stores, multiple providers and agent frameworks.
- **Ambiguity without a person to ask.** Name it, list the reasonable readings, pick the simplest
  defensible one, record it (README, Assumptions) and continue.
- **Data code is part of the system.** Every source is rebuilt by a script in `evals/sources/` that
  regenerates the committed labels exactly; no manual steps.
- **No overfitting.** Fixes found on dev had to be general and covered by a unit test on invented inputs;
  the test split was run once with the code frozen ([evaluation.md](evaluation.md) §4).
- **LLM integration standards.** Provider SDK behind a transport interface; structured output validated
  by our own schema; timeouts, retries only for transient errors, a controlled fallback; tests never call
  the real API; recorded responses make every LLM number replayable offline.
- **Spending.** Paid calls were staged (cheapest model first, then the others) and capped: the evaluation
  runner refuses to call the API without an explicit `--max-calls` limit. Total: about $9.20.
- **Hygiene.** No secrets in the repository or its history; logs never hold document content; no working
  notes inside the code.
