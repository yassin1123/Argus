"""Boot-time config validation — Phase 5 / Week 23 / Day 4.

The direct lesson from W22: missing API keys silently triggered
the heuristic verifier and wasted two weeks of calibration. This
package makes that bug class impossible — config drift is now
LOUD, never silent.

Three modes (env var ``ARGUS_MODE``):

  - ``test`` — heuristic-mode allowed. Default for unit tests +
    the demo seeder. Health endpoints surface the mode + the
    degraded surfaces so an operator can't mistake a test run
    for a pilot one.
  - ``pilot`` — production-equivalent rigor. The heuristic
    verifier is NEVER used; cross-family LLM keys MUST be
    present at boot. Engagements that can't run the real
    verifier fail loud ("cannot verify — provider unavailable")
    rather than producing heuristic output that looks real.
  - ``production`` — same as ``pilot`` (kept distinct so per-
    mode policies can diverge later, e.g. data-retention
    defaults).

Public surface:

  - :func:`get_mode` — read the current mode (defaults to
    ``pilot`` so a deploy without the env var fails closed, not
    silently degrades).
  - :func:`is_strict_mode` — True for pilot + production.
  - :func:`validate_at_boot` — runs every critical check;
    returns a :class:`ConfigReport`. main.py calls this on
    startup; the health endpoint reads the cached report.
  - :func:`assert_real_verifier_required` — call site guard
    that raises in strict modes when the real verifier isn't
    available. Replaces the silent ``HeuristicVerifier`` fallback
    the W22 bug exposed.
"""

from .validation import (
    ConfigCheck,
    ConfigReport,
    MODE_PILOT,
    MODE_PRODUCTION,
    MODE_TEST,
    VerifierUnavailable,
    assert_real_verifier_required,
    enforce_boot_or_exit,
    get_boot_report,
    get_mode,
    is_strict_mode,
    validate_at_boot,
)

__all__ = [
    "ConfigCheck",
    "ConfigReport",
    "MODE_PILOT",
    "MODE_PRODUCTION",
    "MODE_TEST",
    "VerifierUnavailable",
    "assert_real_verifier_required",
    "enforce_boot_or_exit",
    "get_boot_report",
    "get_mode",
    "is_strict_mode",
    "validate_at_boot",
]
