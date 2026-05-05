"""Typed failures for orchestration around inference."""


class InferenceError(Exception):
    """Base inference failure."""


class InferenceTimeout(InferenceError):
    """Completion exceeded configured timeout."""


class InferenceSchemaError(InferenceError):
    """Structured output failed validation after repair attempts."""


class InferenceRateLimit(InferenceError):
    """Upstream rate limit (may be retried by caller)."""


class InferenceAPIError(InferenceError):
    """Non-recoverable API error."""
