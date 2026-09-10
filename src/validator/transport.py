"""LLM transport boundary: moves text to and from the model; never parses or validates it."""


class LLMError(Exception):
    """Base class for LLM failures that the pipeline recovers from."""


class LLMUnavailable(LLMError):
    """The call did not complete: timeout, network, rate limit, 5xx, auth, or no recording."""


class LLMInvalidOutput(LLMError):
    """The model answered, but not with usable content."""
