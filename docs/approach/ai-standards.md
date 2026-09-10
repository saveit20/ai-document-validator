# Engineering standards for AI and external APIs

These standards are **stack-independent**. They apply equally in Python, TypeScript or whatever the
brief imposes. The code snippets illustrate the pattern; they are not code to copy: the concrete
implementation is decided with the brief at hand.

Read before writing any integration with an LLM or an external API.

---

## 1. Isolate the provider

Business logic must not import the provider's SDK. A small interface is defined and the rest of the
system talks to it.

Why it matters: it allows testing without a network, changing models without touching the domain, and it
shows an understanding of where the system's boundary lies.

The boundary has **two levels**, and the distinction matters:

```python
# Level 1 — transport. Returns raw text. It may return anything, or fail.
class LLMTransport(Protocol):
    def complete(self, prompt: str) -> str: ...


# Level 2 — typed layer. Parses, validates and returns a schema object, or raises a typed error.
def generate(transport: LLMTransport, prompt: str, schema: type[T]) -> T: ...
```

Why two and not one: if the only boundary returns an already-validated `T`, **a fake implementing it cannot
return invalid JSON**, which is precisely the failure that needs to be tested. Corrupt model output can only
be simulated at the transport level.

Division of responsibilities:

| | Transport (level 1) | Typed layer (level 2) | Domain |
|---|---|---|---|
| Knows | the SDK, timeouts, network retries | the schema, parsing, validation | none of the above |
| Returns | raw text or a transport error | a valid object or a typed error | business result |
| Faked for testing with | corrupt responses, timeouts, 429, 5xx | valid and invalid objects | — |

Limits of this rule:

- **A single real implementation.** Do not build a multi-provider system unless the brief asks for it.
  The boundary exists for testing and decoupling, not to support five providers.
- **One interface, not a hierarchy.** No factories, registries or dynamic configuration layers to choose
  a provider.
- If the brief makes integration with a specific provider an explicit part of the domain, this rule is
  relaxed and documented.

## 2. Structured output

When the result has a known structure, free text is **never** consumed.

```text
LLM → parse → schema validation → business logic
```

- Define the schema first; it is the contract.
- Use the provider's native structured-output mode if there is one; if not, ask for JSON in the prompt
  and validate it anyway. **Validation is not optional even if the provider guarantees the format.**
- Validation happens at the edge. Business logic receives objects that are already valid.
- Flat, small schemas. A huge nested schema increases the model's failure rate.
- Explicit optional fields: the model must be able to say "it is not in the input" without inventing.

## 3. Prompts

The prompt is part of the system, not informal text.

- It lives in its own module, not embedded in the logic.
- It is documented: objective, expected output format, constraints, quality criteria.
- Recommended structure: role → task → context → constraints → output schema → what to do if
  information is missing.
- An explicit instruction against hallucination: what the model must return when the data is not there.
- No contradictory instructions. They are the most common cause of erratic outputs.
- Examples only if they observably improve the result; they take up context and cost money.
- User content is clearly delimited and separated from the system instructions.

## 4. Testing the non-deterministic

**Tests do not call the real API.** They are slow, cost money, fail without a network and their results vary.

The pattern: fake implementations of the boundaries in §1. **Each failure is tested at its own level**, and
confusing the levels is the classic mistake.

**Against a fake transport** (returns whatever raw text it is told to, or raises whatever error it is told
to). Tests the typed layer: parsing, validation, retries, errors.

- malformed JSON;
- empty or truncated response;
- missing required field;
- wrong type or value outside the domain;
- text that is not JSON at all;
- timeout, 429, 5xx;
- missing credential.

**Against a fake typed client** (returns valid schema objects, or raises the typed errors that level 2
defines). Tests the business logic, without serialization noise.

- happy path with different values;
- behaviour when faced with a typed LLM error;
- business cases derived from the acceptance criteria.

None of these situations can be reliably provoked against the real API, and all of them will happen in
production. This is what separates a toy integration from a real one.

If something is to be run against the real API, it goes in a separate, flagged and optional command.

## 5. Reliability of external calls

Every call to an external service considers:

- **An explicit timeout.** Never the SDK default, which is usually infinite or very high.
- **Retry with exponential backoff**, only for transient failures: timeout, 429, 5xx, network error.
  With a maximum number of attempts.
- **Do not retry** what is unrecoverable: 400, 401, 403, invalid credential, malformed prompt.
  Retrying a content error repeats it identically and burns money.
- **Distinguish a transport failure from a content failure.** A response that arrives but does not validate
  against the schema is not a network failure. A repair can be attempted (a second call stating the
  error) if it adds value, but with a hard limit.
- **Controlled degradation.** If there is no valid response after the retries, the system returns a typed,
  understandable error, not a raw exception or a half-finished result.
- **Missing configuration**: if a mandatory key is missing, fail at startup with a clear message, not
  midway through processing.

## 6. Minimal observability

`logging`, never `print`.

Log, when useful: pipeline stage, success or failure, latency, model and provider, number of retries,
tokens and estimated cost if the platform exposes them.

**Never** log: API keys, credentials, or unnecessary sensitive data. Be careful about dumping the full
prompt if it contains user data.

Do not build an observability platform. A configured logger and a few useful lines.

## 7. Cost and limits

- Configure maximum output tokens, so that a runaway model does not drive up the cost.
- Count the calls: a loop over N items is N calls.
- Consider batch processing if the brief implies volume.
- Do not leave a loop that retries without limit.

## 8. Security

- Keys only via environment variables. Never in code, never in the repository.
- `.env` ignored; `.env.example` versioned with empty keys.
- Everything that enters the prompt from outside is untrusted. If the brief makes it relevant,
  consider prompt injection: delimit user content and do not allow embedded instructions to change the
  system's behaviour.
- Model output is also untrusted: validate it before using it, with particular care if it is going to
  feed a query, a command or a rendering.

## 9. Personal and sensitive data

Using a third-party LLM means **sending data to someone else's server**. If the challenge data contains
personal or sensitive information, that is a design decision, not an implementation detail, and it must be
made consciously and documented.

What to check before sending anything to the provider:

- **What does the data contain?** Names, national ID/tax ID numbers, addresses, emails, phone numbers,
  employment or financial data, customer identifiers. This is reviewed in the phase 1 analysis
  (see 01-understand.md), not at the end.
- **Does everything need to be sent?** Almost never. Sending only the field or fragment the task needs is
  cheaper, more accurate and reduces exposure. If a field does not contribute to the reasoning, it does not
  travel.
- **Can it be anonymised or masked** before sending, and reconstructed afterwards? When the task allows it,
  this is the most defensible option.
- **What does the brief say?** If it mentions confidentiality, GDPR, real data or synthetic data, what it
  says prevails and is cited in the README.

In logs and traces:

- Do not dump the full prompt if it contains personal data. Log identifiers or lengths, not the content.
- Never keys, credentials or tokens.
- Be careful with error messages: they commonly carry the input that caused the failure.

The decision taken — sent as is, trimmed, anonymised, or synthetic data used — is documented in the
working decision log (its final form is docs/decisions.md) and summarised in the README. **In a domain with
personal data, this question must be addressed explicitly; leaving it unaddressed is a design flaw.**

## 10. Quick checklist

Before accepting an integration:

- [ ] Business logic does not import the provider's SDK.
- [ ] The boundary has separate transport and typed layers.
- [ ] Content failures are tested against a fake transport, not against the typed client.
- [ ] If there is personal data: it has been decided and documented what travels to the provider and what does not.
- [ ] Output is validated against a schema before it is used.
- [ ] There is an explicit timeout.
- [ ] Retries are only for transient failures and are limited.
- [ ] A definitive failure produces a typed, understandable error.
- [ ] The prompt is in its own module and documented.
- [ ] Tests pass without a network and without an API key.
- [ ] There are no secrets in the code, the logs or the history.
