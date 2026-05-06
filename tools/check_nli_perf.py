"""DeBERTa NLI latency + memory check (Week 2 / Day 1).

Scores 60 (premise, hypothesis) pairs in a single batch and asserts:

- Wall time < 30 seconds
- Resident memory of the calling process stays below 1.2 GB

Run inside the nli_worker container so the resident-memory measurement
matches what `docker stats nli_worker` would show in production:

    docker compose run --rm nli_worker python tools/check_nli_perf.py

Exits 0 on pass, 1 on fail. Fail message prints the actual wall-time and
peak RSS so the operator can see how close we are to the budget.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make `backend/` importable. Two layouts supported:
#   - Inside nli_worker container: backend lives at /app (Dockerfile WORKDIR);
#     the tools/ tree is bind-mounted at /repo_tools.
#   - On the host: backend is at <repo>/backend, we compute that from __file__.
if Path("/app").is_dir() and (Path("/app") / "core" / "nli").is_dir():
    sys.path.insert(0, "/app")
else:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPO_ROOT / "backend"))

from core.nli.deberta_client import score_pairs  # noqa: E402

WALLTIME_BUDGET_SECONDS = 30.0
MEMORY_BUDGET_MB = 1200.0
NUM_PAIRS = 60


def _rss_mb() -> float:
    """Resident set size of this process in MB.

    Linux: read /proc/self/status (no extra deps). Windows: fall back to
    psutil if available, else 0.0 (the container check is the operative
    one anyway — local Windows runs are advisory).
    """
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                # "VmRSS:    824400 kB"
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return float(parts[1]) / 1024.0
    try:
        import psutil  # type: ignore[import-not-found]

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _build_pairs() -> list[tuple[str, str]]:
    """60 pairs of varying lengths so the batch exercises a realistic
    distribution. Repeating one short pair 60x would underestimate
    real per-call cost because the model would benefit from CPU caches /
    branch predictors that won't help in production.
    """
    seeds = [
        (
            "The German B2B SaaS market reached €2.4 billion in 2024, the "
            "largest in continental Europe and roughly 1.6x the size of France.",
            "Germany's B2B SaaS market is approximately €2.4B in 2024.",
        ),
        (
            "France posted 22% YoY growth in B2B SaaS spend in 2024, "
            "outpacing Germany's 14% — driven by public-sector "
            "digitization mandates.",
            "France's SaaS market grew faster than Germany's in 2024.",
        ),
        (
            "Average B2B SaaS procurement cycle in German Mittelstand: "
            "7.2 months, vs 4.8 months in France for comparable deal sizes.",
            "German Mittelstand procurement is faster than France.",
        ),
        (
            "Mittelstand firms typically have between 10 and 500 employees, "
            "are family-owned, and concentrate in NRW + Bavaria.",
            "Mittelstand companies are mid-sized German businesses.",
        ),
        (
            "Stripe processed approximately $1 trillion in payment volume "
            "in 2024, up from $817 billion the prior year.",
            "Stripe handled around $1T in 2024 payments.",
        ),
    ]
    pairs: list[tuple[str, str]] = []
    while len(pairs) < NUM_PAIRS:
        pairs.extend(seeds)
    return pairs[:NUM_PAIRS]


def main() -> int:
    pairs = _build_pairs()
    print(f"Scoring {len(pairs)} pairs in a single batch ...", flush=True)

    rss_before = _rss_mb()
    t0 = time.perf_counter()
    results = score_pairs(pairs)
    wall = time.perf_counter() - t0
    rss_after = _rss_mb()
    rss_peak = max(rss_before, rss_after)

    print(
        f"  wall={wall:.2f}s  results={len(results)}  "
        f"rss_before={rss_before:.0f}MB  rss_after={rss_after:.0f}MB",
        flush=True,
    )

    failures: list[str] = []
    if wall >= WALLTIME_BUDGET_SECONDS:
        failures.append(
            f"latency: {wall:.2f}s >= {WALLTIME_BUDGET_SECONDS}s budget"
        )
    if rss_peak >= MEMORY_BUDGET_MB:
        failures.append(
            f"memory: peak RSS {rss_peak:.0f}MB >= {MEMORY_BUDGET_MB:.0f}MB budget"
        )
    if len(results) != len(pairs):
        failures.append(
            f"shape: returned {len(results)} results for {len(pairs)} input pairs"
        )

    if failures:
        print("FAIL:", "; ".join(failures), flush=True)
        return 1
    print("OK: latency + memory under budget.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
