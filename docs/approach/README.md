# The approach: working documents

These are the documents the work was planned with, translated from the author's working language. They are
here to show how the exercise was approached: the requirements were traced to the brief, the architecture
decided and the evaluation data planned *before* the code was written. The rules the work followed are
summarised in [../process.md](../process.md).

They are working documents and keep their history: statuses, schedules and some plans are as they were
recorded at the time. **Where they differ from the final system, the [README](../../README.md),
[decisions.md](../decisions.md) and [evaluation.md](../evaluation.md) describe what shipped.** Nothing here
is needed to run or review the code.

| Document | What it is |
|---|---|
| [spec.md](spec.md) | The specification, written first: requirements traced to the brief, acceptance criteria, risks |
| [design.md](design.md) | The design, written before the code: architecture, the deterministic/LLM boundary, what was left out, the plan |
| [assumptions.md](assumptions.md) | The assumption register: each ambiguity, the options, the choice, and later revisions |
| [data-strategy.md](data-strategy.md) | How the evaluation data was planned, searched for and chosen to avoid overfitting |
| [ai-standards.md](ai-standards.md) | The standards every LLM integration had to meet |

How to read the references in them:

- **DEC-xx** are entries of the working decision log, whose final form is [decisions.md](../decisions.md).
- **P-xx** are decisions put to the author on the private status board (for example P-04, the meaning of
  `REVIEW`); their outcome is recorded where they are cited.

What changed after these documents were written, all recorded in [decisions.md](../decisions.md) and the
[contamination log](../evaluation.md#contamination-log):

- A required field that was not extracted gives `REVIEW`, not `FAIL` (decision D1).
- Numeric dates are read per document from its own signals, not always day first (ASSUMPTION-09's revision).
- The evaluation moved from author-written invoices to six independent sources; the model was chosen by the
  rule written in advance (Opus 5); the model now sees the PDF as well as its text.
