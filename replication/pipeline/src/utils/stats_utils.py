"""Statistical test, inequality, multiple-testing, and Markdown frontmatter utilities."""

from __future__ import annotations

import datetime
import json
import math
from typing import Any

from scipy import stats

_Z_975 = 1.959963984540054
_Z_80_POWER = 0.8416212335729143
_Z_90_POWER = 1.2815515655446004


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def wilson_ci(k: int, n: int, z: float = _Z_975) -> tuple[float, float]:
    """Compute the two-sided Wilson score confidence interval as proportions in [0.0, 1.0]."""
    if n <= 0:
        return (0.0, 0.0)
    k_clamped = max(0, min(k, n))
    p = k_clamped / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    radical = max(0.0, (p * (1.0 - p) + z2 / (4.0 * n)) / n)
    half = (z * math.sqrt(radical)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def two_prop_z_test(k1: int, n1: int, k2: int, n2: int) -> dict[str, Any]:
    """Compute two-proportion Z-test, Wilson 95% CIs, Cohen's h, and statistical power."""
    if n1 <= 0 or n2 <= 0:
        lo1, hi1 = wilson_ci(k1, n1)
        lo2, hi2 = wilson_ci(k2, n2)
        p1 = k1 / n1 if n1 > 0 else 0.0
        p2 = k2 / n2 if n2 > 0 else 0.0
        return {
            "n1": n1,
            "k1": k1,
            "p1_pct": round(100.0 * p1, 2),
            "ci1_95_pct": [round(100.0 * lo1, 2), round(100.0 * hi1, 2)],
            "n2": n2,
            "k2": k2,
            "p2_pct": round(100.0 * p2, 2),
            "ci2_95_pct": [round(100.0 * lo2, 2), round(100.0 * hi2, 2)],
            "diff_pp": round(100.0 * (p2 - p1), 2),
            "relative_shift_pct": 0.0,
            "z_stat": 0.0,
            "p_value": 1.0,
            "cohens_h": 0.0,
            "achieved_power_pct": 0.0,
            "n_per_arm_for_80pct_power": 0,
            "n_per_arm_for_90pct_power": 0,
            "power_status": "NEEDS_BROADENING (<80%)",
        }

    p1 = k1 / n1
    p2 = k2 / n2
    lo1, hi1 = wilson_ci(k1, n1)
    lo2, hi2 = wilson_ci(k2, n2)

    p_pool = (k1 + k2) / (n1 + n2)
    se_pool = math.sqrt(max(0.0, p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2)))
    z_stat = (p1 - p2) / se_pool if se_pool > 0 else 0.0
    p_val = 2.0 * (1.0 - _norm_cdf(abs(z_stat)))

    p1_c = min(0.9999, max(0.0001, p1))
    p2_c = min(0.9999, max(0.0001, p2))
    h = abs(2.0 * math.asin(math.sqrt(p1_c)) - 2.0 * math.asin(math.sqrt(p2_c)))

    n_harm = (2.0 * n1 * n2) / float(n1 + n2)
    non_centrality = h * math.sqrt(n_harm / 2.0)
    achieved_power = min(1.0, _norm_cdf(non_centrality - _Z_975) + _norm_cdf(-non_centrality - _Z_975))

    h_eff = max(0.01, h)
    n_req_80 = int(math.ceil(2.0 * ((_Z_975 + _Z_80_POWER) / h_eff) ** 2))
    n_req_90 = int(math.ceil(2.0 * ((_Z_975 + _Z_90_POWER) / h_eff) ** 2))

    if achieved_power >= 0.90:
        power_status = "FULLY_POWERED (>=90%)"
    elif achieved_power >= 0.80:
        power_status = "ADEQUATELY_POWERED (80-89%)"
    else:
        power_status = "NEEDS_BROADENING (<80%)"

    return {
        "n1": n1,
        "k1": k1,
        "p1_pct": round(100.0 * p1, 2),
        "ci1_95_pct": [round(100.0 * lo1, 2), round(100.0 * hi1, 2)],
        "n2": n2,
        "k2": k2,
        "p2_pct": round(100.0 * p2, 2),
        "ci2_95_pct": [round(100.0 * lo2, 2), round(100.0 * hi2, 2)],
        "diff_pp": round(100.0 * (p2 - p1), 2),
        "relative_shift_pct": round(100.0 * (p2 - p1) / p1, 2) if p1 > 0 else 0.0,
        "z_stat": round(z_stat, 3),
        "p_value": float(p_val),
        "cohens_h": round(h, 4),
        "achieved_power_pct": round(100.0 * achieved_power, 2),
        "n_per_arm_for_80pct_power": n_req_80,
        "n_per_arm_for_90pct_power": n_req_90,
        "power_status": power_status,
    }


def fisher_exact_2x2(k1: int, n1: int, k2: int, n2: int) -> float:
    """Compute exact two-sided Fisher test p-value for two binomial arms (k1/n1 vs k2/n2)."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    k1_c = max(0, min(k1, n1))
    k2_c = max(0, min(k2, n2))
    table = [[k1_c, n1 - k1_c], [k2_c, n2 - k2_c]]
    _, p_val = stats.fisher_exact(table, alternative="two-sided")
    return float(p_val)


def bh_fdr(p_values: list[float]) -> list[float]:
    """Compute Benjamini-Hochberg FDR-adjusted q-values preserving input ordering."""
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda pair: pair[1])
    q_vals = [1.0] * m
    prev = 1.0
    for rank_rev, (orig_idx, p_val) in enumerate(reversed(indexed)):
        rank = m - rank_rev
        q = min(prev, max(0.0, min(1.0, float(p_val) * m / rank)))
        q_vals[orig_idx] = q
        prev = q
    return q_vals


def gini_coefficient(values: list[float]) -> float:
    """Compute the Gini inequality coefficient for non-negative workload counts."""
    n = len(values)
    if n <= 1:
        return 0.0
    sorted_vals = sorted(float(v) for v in values)
    total = sum(sorted_vals)
    if total <= 0.0:
        return 0.0
    cum = 0.0
    cum_sum = 0.0
    for v in sorted_vals:
        cum += v
        cum_sum += cum
    return float((n + 1 - 2.0 * cum_sum / total) / n)


def yaml_frontmatter(
    title: str,
    intent: str,
    doc_type: str = "reference",
    status: str = "active",
    skills: list[str] | None = None,
) -> str:
    """Render standardized Rule-0 YAML frontmatter for generated Markdown reports."""
    skills_list = skills if skills is not None else ["empirical-methodologist"]
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "---",
        f"title: {json.dumps(title)}",
        f"intent: {json.dumps(intent)}",
        f"type: {json.dumps(doc_type)}",
        f"status: {json.dumps(status)}",
        "skills_applied:",
    ]
    for skill in skills_list:
        lines.append(f"  - {json.dumps(skill)}")
    lines.extend([
        f"last_updated: {json.dumps(today)}",
        "---",
        "",
    ])
    return "\n".join(lines)
