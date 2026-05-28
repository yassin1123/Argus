"""Boot-time validation + strict-mode policy — Phase 5 / W23 / D4.

See package docstring for the design. This module is the
implementation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


MODE_TEST = "test"
MODE_PILOT = "pilot"
MODE_PRODUCTION = "production"
_VALID_MODES = {MODE_TEST, MODE_PILOT, MODE_PRODUCTION}


def get_mode() -> str:
    """Read ``ARGUS_MODE``. Default is ``pilot`` — a deploy that
    forgets the env var fails CLOSED (refuses heuristic
    substitution) rather than silently degrading. This is the
    W22 bug-class fix."""
    raw = (os.getenv("ARGUS_MODE") or MODE_PILOT).strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "ARGUS_MODE=%r is not in %s; treating as pilot (strict).",
            raw, sorted(_VALID_MODES),
        )
        return MODE_PILOT
    return raw


def is_strict_mode() -> bool:
    """True when heuristic substitution is FORBIDDEN. Pilot + prod."""
    return get_mode() in (MODE_PILOT, MODE_PRODUCTION)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VerifierUnavailable(RuntimeError):
    """Raised in strict mode when the real cross-family verifier
    can't be constructed. The orchestrator + API surfaces map
    this to a clear user-facing message — never silently
    substitute the heuristic."""


# ---------------------------------------------------------------------------
# ConfigCheck / ConfigReport
# ---------------------------------------------------------------------------


@dataclass
class ConfigCheck:
    """One check's result — name + ok + detail (no secret values)."""

    name: str
    ok: bool
    detail: str = ""
    # 'critical' checks fail the boot in strict mode; 'optional'
    # checks just record their state on the report.
    severity: str = "critical"   # critical | optional


@dataclass
class ConfigReport:
    """The full boot-time state. Cached in :data:`_BOOT_REPORT`
    so the health endpoint can read it without re-running the
    checks."""

    mode: str
    strict: bool
    can_run_real_verifier: bool
    all_critical_ok: bool
    degraded: bool                 # True when any critical fails
    checks: list[ConfigCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "strict": self.strict,
            "can_run_real_verifier": self.can_run_real_verifier,
            "all_critical_ok": self.all_critical_ok,
            "degraded": self.degraded,
            "checks": [asdict(c) for c in self.checks],
        }


_BOOT_REPORT: ConfigReport | None = None


def get_boot_report() -> ConfigReport | None:
    return _BOOT_REPORT


# ---------------------------------------------------------------------------
# Individual checks — each returns a ConfigCheck, no exceptions
# (a check that crashes still produces ok=False so the report
# is stable to read).
# ---------------------------------------------------------------------------


def _present(key: str) -> bool:
    v = os.getenv(key) or ""
    return bool(v.strip()) and len(v.strip()) > 16


def _check_anthropic_key() -> ConfigCheck:
    return ConfigCheck(
        name="anthropic_api_key",
        ok=_present("ANTHROPIC_API_KEY"),
        detail=(
            "present"
            if _present("ANTHROPIC_API_KEY")
            else "MISSING — required for cross-family verification"
        ),
        severity="critical",
    )


def _check_openai_key() -> ConfigCheck:
    return ConfigCheck(
        name="openai_api_key",
        ok=_present("OPENAI_API_KEY"),
        detail=(
            "present"
            if _present("OPENAI_API_KEY")
            else "MISSING — required for cross-family verification"
        ),
        severity="critical",
    )


def _check_deberta_module() -> ConfigCheck:
    try:
        import sentence_transformers  # noqa: F401
        return ConfigCheck(
            name="deberta_module",
            ok=True,
            detail="sentence-transformers importable",
            severity="critical",
        )
    except ImportError:
        return ConfigCheck(
            name="deberta_module",
            ok=False,
            detail=(
                "MISSING — sentence-transformers not installed; "
                "DeBERTa cross-encoder falls back to neutral/0.0 "
                "(the production worker-timeout shape). Verifier "
                "ensemble runs degraded."
            ),
            severity="critical",
        )


def _check_database_url() -> ConfigCheck:
    url = (os.getenv("DATABASE_URL") or "").strip()
    return ConfigCheck(
        name="database_url",
        ok=bool(url),
        detail="present" if url else "MISSING — DATABASE_URL unset",
        severity="critical",
    )


def _check_model_pricing() -> ConfigCheck:
    """LiteLLM ships a built-in pricing table; the check is whether
    the litellm import path works at all. A misconfigured router
    yaml would crash later, but the pricing table itself is
    bundled."""
    try:
        import litellm  # noqa: F401
        return ConfigCheck(
            name="model_pricing",
            ok=True,
            detail="litellm import OK (bundled pricing table)",
            severity="optional",
        )
    except ImportError:
        return ConfigCheck(
            name="model_pricing",
            ok=False,
            detail="litellm not importable",
            severity="critical",
        )


def _check_email_adapter() -> ConfigCheck:
    """The W18 email adapter selection. 'capture' is fine for
    pilot + dev; 'smtp' needs SMTP_* env vars."""
    chosen = (os.getenv("ARGUS_EMAIL_ADAPTER") or "capture").strip().lower()
    if chosen == "capture":
        return ConfigCheck(
            name="email_adapter",
            ok=True,
            detail="capture adapter (in-memory; no SMTP needed)",
            severity="optional",
        )
    if chosen == "smtp":
        ok = all(_present(k) for k in (
            "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD",
        ))
        return ConfigCheck(
            name="email_adapter",
            ok=ok,
            detail=(
                "smtp adapter selected; "
                + ("SMTP_* env vars present" if ok else "SMTP_* env vars MISSING")
            ),
            severity="critical" if not ok else "optional",
        )
    return ConfigCheck(
        name="email_adapter", ok=False,
        detail=f"unknown ARGUS_EMAIL_ADAPTER={chosen!r}",
        severity="critical",
    )


# ---------------------------------------------------------------------------
# Public boot-time validator
# ---------------------------------------------------------------------------


def validate_at_boot() -> ConfigReport:
    """Run every check + cache the report. Idempotent within a
    process; main.py calls this once on startup. Re-callable from
    tests (each test gets the fresh state of its env)."""
    global _BOOT_REPORT
    mode = get_mode()
    strict = is_strict_mode()
    checks = [
        _check_anthropic_key(),
        _check_openai_key(),
        _check_deberta_module(),
        _check_database_url(),
        _check_model_pricing(),
        _check_email_adapter(),
    ]
    # The "can run real verifier" predicate is the LOAD-BEARING
    # one. Anthropic + OpenAI keys present AND DeBERTa module
    # importable — anything less and strict-mode engagements
    # MUST fail loud.
    can_real_verifier = (
        all(
            c.ok for c in checks
            if c.name in ("anthropic_api_key", "openai_api_key", "deberta_module")
        )
    )
    critical_ok = all(c.ok for c in checks if c.severity == "critical")
    degraded = not critical_ok
    report = ConfigReport(
        mode=mode,
        strict=strict,
        can_run_real_verifier=can_real_verifier,
        all_critical_ok=critical_ok,
        degraded=degraded,
        checks=checks,
    )
    _BOOT_REPORT = report

    if degraded:
        log = logger.warning if not strict else logger.error
        log(
            "ARGUS BOOT: mode=%s strict=%s -- critical config "
            "degraded. Failed checks: %s. "
            "%s",
            mode, strict,
            [c.name for c in checks if c.severity == "critical" and not c.ok],
            (
                "The orchestrator will REFUSE to run engagements that "
                "need the real verifier; the heuristic substitute is "
                "DISABLED in strict mode (W22 bug-class fix)."
                if strict else
                "Test mode — heuristic substitution permitted, but "
                "results are not pilot-quality."
            ),
        )
    return report


# ---------------------------------------------------------------------------
# Call-site guard — the W22 bug-class fix made unavoidable
# ---------------------------------------------------------------------------


def assert_real_verifier_required() -> None:
    """Raise :class:`VerifierUnavailable` when the current process
    is in strict mode AND can't actually run the real
    cross-family ensemble. This is the guard the orchestrator +
    calibration runners call BEFORE constructing a HeuristicVerifier
    — in strict mode they MUST get the real ensemble or fail
    loud, never silently substitute heuristic output for a real
    one.

    In test mode the guard is a no-op (heuristic substitution
    permitted explicitly).
    """
    if not is_strict_mode():
        return
    report = _BOOT_REPORT or validate_at_boot()
    if report.can_run_real_verifier:
        return
    missing = [
        c.name for c in report.checks
        if c.severity == "critical" and not c.ok
        and c.name in ("anthropic_api_key", "openai_api_key", "deberta_module")
    ]
    raise VerifierUnavailable(
        "verification unavailable: cross-family verifier cannot run "
        f"({', '.join(missing) or 'unknown reason'}). "
        "The heuristic substitute is forbidden in strict mode "
        "(ARGUS_MODE=" + report.mode + "). Set the required keys / "
        "install sentence-transformers, then restart. To run in "
        "test mode anyway, set ARGUS_MODE=test (results will be "
        "labelled non-pilot-quality)."
    )


def enforce_boot_or_exit(report: ConfigReport | None = None) -> None:
    """Production hard-stop: in ``production`` mode, REFUSE TO START when
    the config is degraded (can't run the real cross-family verifier).

    The W23 fail-loud guard (:func:`assert_real_verifier_required`) makes
    a degraded *engagement* impossible; this makes a degraded *boot*
    impossible in production. A prod container that's missing an LLM key
    or DeBERTa crash-loops with a loud error rather than coming up and
    silently serving a verifier that can't actually verify.

    Pilot mode logs the degradation but still boots (a pilot operator may
    intentionally run a read-only / partially-configured instance);
    production does not get that latitude. Test mode is exempt.
    """
    report = report or get_boot_report() or validate_at_boot()
    if get_mode() != MODE_PRODUCTION:
        return
    if report.can_run_real_verifier and not report.degraded:
        return
    failed = [
        c.name for c in report.checks
        if c.severity == "critical" and not c.ok
    ]
    raise SystemExit(
        "FATAL: ARGUS_MODE=production but the config is degraded — refusing "
        "to start. The real cross-family verifier is unavailable "
        f"(can_run_real_verifier={report.can_run_real_verifier}; "
        f"failed critical checks={failed}). Production NEVER runs the "
        "heuristic substitute (the W22 bug class). Provide both LLM "
        "provider keys + install sentence-transformers (DeBERTa), then "
        "restart. To run a deliberately-degraded instance, use "
        "ARGUS_MODE=pilot (boots degraded) or ARGUS_MODE=test."
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
