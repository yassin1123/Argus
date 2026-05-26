"""Hallucination red-team suite — Phase 5 / Week 21 / Day 4.

Adversarial claim-evidence pairs hand-built to exploit specific
verifier weaknesses. Every pair's ground truth is NOT
``supported``; an escape is when the verifier calls it supported
anyway.

The suite is **separate** from the W21/D1 golden set: golden_set
measures calibration on a balanced sample; red_team measures
the verifier under deliberate attack. Catch rate on red_team is
the trust-defending metric — every escape is a real
vulnerability that ships in a real client deliverable if not
caught.
"""

from .adversarial_cases import (
    AdversarialCase,
    ExploitType,
    build_adversarial_cases,
)
from .numeric_probe import (
    NumericProbeResult,
    numeric_consistency_check,
)

__all__ = [
    "AdversarialCase",
    "ExploitType",
    "NumericProbeResult",
    "build_adversarial_cases",
    "numeric_consistency_check",
]
