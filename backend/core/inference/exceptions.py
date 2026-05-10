"""Typed failures for orchestration around inference."""


class InferenceError(Exception):
    """Base inference failure."""


class InferenceTimeout(InferenceError):
    """Completion exceeded configured timeout."""


class InferenceSchemaError(InferenceError):
    """Structured output failed validation after repair attempts.

    ``raw_text`` (W7/D5 iterate) carries the last failed LLM response
    body so the operator can see exactly what the model emitted —
    truncated JSON, markdown wrapper, freeform prose, etc. The
    ValidationError on ``__cause__`` tells you the schema violation;
    ``raw_text`` tells you whether it was a token-budget cutoff or
    something else entirely.
    """

    def __init__(self, message: str, *, raw_text: str | None = None) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class InferenceRateLimit(InferenceError):
    """Upstream rate limit (may be retried by caller)."""


class InferenceAPIError(InferenceError):
    """Non-recoverable API error."""
