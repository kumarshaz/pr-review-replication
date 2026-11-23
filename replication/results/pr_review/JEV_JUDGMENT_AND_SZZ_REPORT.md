---
title: "Jev Decision-Model Tollgates: Human Judgment (NQ-01) & Bare-Git SZZ Outcomes (NQ-02)"
intent: "Empirical evaluation of compact Jev decision-model tollgates vs verbose prose bots on human formal review judgment, corrective commits, and within-repo bare-git SZZ post-release bugfix outcomes."
type: "study-protocol"
status: "active"
skills_applied:
  - "empirical-methodologist"
last_updated: "2026-11-22"
---
# Jev Decision-Model Tollgates: Human Judgment (NQ-01) & Bare-Git SZZ Outcomes (NQ-02)

**Generated (UTC):** `2026-11-22T19:32:45.718439+00:00`  
**Signals Source:** `jev_bot_signals_reparsed.parquet` | **SZZ Ledger:** `szz_defect_traceability_ledger.csv`

## 1. NQ-01: Verbosity, Information Density & Human Engagement Across Regimes

| Regime | PRs | Merged % (95% CI) | Median Bot Chars | Post-Bot Human Comment % | Formal Review Hydration % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `no_bot_control` | 4,475 | 78.23% [77.0, 79.4] | N/A | 12.76% | 0.00% (0/4475) |
| `prose_review_bot_control` | 849 | 89.99% [87.8, 91.8] | 2731.5 | 53.83% | 0.00% (0/849) |
| `jev_pr_risk_histogram` | 285 | 96.84% [94.1, 98.3] | 564.0 | 12.98% | 8.42% (24/285) |
| `jev_decision_model_linter` | 165 | 63.64% [56.1, 70.6] | 515.5 | 24.24% | 73.33% (121/165) |
| `static_sast_bot_control` | 123 | 65.04% [56.3, 72.9] | 996.0 | 54.47% | 0.00% (0/123) |
| `deterministic_merge_gate` | 55 | 98.18% [90.4, 99.7] | 2450.0 | 100.00% | 0.00% (0/55) |
| `jev_review_router` | 51 | 80.39% [67.5, 89.0] | 157.0 | 100.00% | 0.00% (0/51) |
| `jev_council_architect_review` | 30 | 96.67% [83.3, 99.4] | 1522.1 | 100.00% | 0.00% (0/30) |
| `jev_taste_policy_gate` | 20 | 20.00% [8.1, 41.6] | 319.0 | 15.00% | 0.00% (0/20) |
| `jev_loop_review_gate` | 1 | 0.00% [0.0, 79.3] | 1285.0 | 0.00% | 0.00% (0/1) |
| `jev_way_of_working_advisor` | 1 | 0.00% [0.0, 79.3] | 2471.2 | 100.00% | 0.00% (0/1) |

### Hydrated Jev Repos (`getsentry/sentry`, `craftmilldev/loopway`, `craftmilldev/sesh`) Formal Judgment

| Stratum | PRs | Merge % | Pre-Review Self-Close % | Human Reviewed | CR % | Substantive (>20c) % | Post-Jev Commit % |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Coding_Agent::Jev_Clean` | 143 | 92.31% | 1.40% | 32 | 3.12% | 15.62% | 50.35% |
| `Coding_Agent::Jev_Flagged` | 64 | 71.88% | 4.69% | 30 | 6.67% | 30.00% | 67.19% |
| `Coding_Agent::No_Jev_Control` | 705 | 56.03% | 17.45% | 0 | 0.00% | 0.00% | 0.00% |
| `Human_Engineer::Jev_Clean` | 31 | 83.87% | 0.00% | 28 | 0.00% | 28.57% | 100.00% |
| `Human_Engineer::Jev_Flagged` | 74 | 62.16% | 6.76% | 55 | 0.00% | 20.00% | 74.32% |
| `Human_Engineer::No_Jev_Control` | 701 | 65.76% | 6.13% | 0 | 0.00% | 0.00% | 0.00% |

### Verbosity vs. Human Judgment Correlations
- **`getsentry/sentry`** (`n=254`, formal reviewed `n=121`): Spearman `rho(log_bot_chars, post_bot_human_comment) = 0.1881` (p=0.002606937022198858); `rho(log_bot_chars, human_CR) = -0.0916`; `rho(log_bot_chars, rubber_stamp) = -0.0158`.
- **`AIDev` Cohort C** (`n=1671`): Spearman `rho(log_bot_chars, human_CR) = -0.0674` (p=0.0058140933603913775); `rho(log_bot_chars, rubber_stamp) = -0.0933` (p=0.00013446567865294743).

## 2. NQ-02: Commit-Attributed Bare-Git SZZ Outcomes (14d & 30d Uncensored)

| Window | Author Origin | Arm | N | SZZ Bugs | SZZ Bugfix % (95% CI) | Reverts | Mean File Survival % |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 14d | `Coding_Agent` | `Jev_Clean` | 78 | 49 | 62.82% [51.7, 72.7] | 1 | 2.60% |
| 14d | `Coding_Agent` | `Jev_Flagged` | 47 | 19 | 40.43% [27.6, 54.7] | 0 | 26.16% |
| 14d | `Coding_Agent` | `No_Bot_Control` | 742 | 280 | 37.74% [34.3, 41.3] | 0 | 33.26% |
| 14d | `Coding_Agent` | `Prose_Bot_Control` | 22 | 9 | 40.91% [23.3, 61.3] | 0 | 49.19% |
| 14d | `Human_Engineer` | `Jev_Clean` | 10 | 8 | 80.00% [49.0, 94.3] | 0 | 21.09% |
| 14d | `Human_Engineer` | `Jev_Flagged` | 55 | 41 | 74.55% [61.7, 84.2] | 1 | 19.00% |
| 14d | `Human_Engineer` | `No_Bot_Control` | 1,451 | 742 | 51.14% [48.6, 53.7] | 0 | 39.15% |
| 14d | `Human_Engineer` | `Prose_Bot_Control` | 494 | 293 | 59.31% [54.9, 63.6] | 0 | 46.40% |
| 14d | `Human_Engineer` | `Static_SAST_Control` | 2 | 1 | 50.00% [9.4, 90.5] | 0 | 0.00% |
| 30d | `Coding_Agent` | `No_Bot_Control` | 572 | 298 | 52.10% [48.0, 56.2] | 0 | 78.19% |
| 30d | `Coding_Agent` | `Prose_Bot_Control` | 18 | 10 | 55.56% [33.7, 75.4] | 0 | 62.28% |
| 30d | `Human_Engineer` | `No_Bot_Control` | 1,087 | 681 | 62.65% [59.7, 65.5] | 0 | 67.29% |
| 30d | `Human_Engineer` | `Prose_Bot_Control` | 288 | 219 | 76.04% [70.8, 80.6] | 0 | 65.71% |

### Mantel-Haenszel Within-Repo Matched Summaries (Simpson's Paradox Guardrail)

| Window | Cohort | Comparison | Matched Strata | Treat k/n (%) | Ctrl k/n (%) | MH Odds Ratio (95% CI) | CMH p-value |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 14d | `ALL` | `jev_flagged_vs_jev_clean` | 6 | 55/90 (61.11%) | 57/88 (64.77%) | 2.2574 [0.8023, 6.3519] | 0.1364 |
| 14d | `ALL` | `jev_any_vs_no_bot_control` | 8 | 117/190 (61.58%) | 450/619 (72.70%) | 0.8198 [0.5175, 1.2987] | 0.3881 |
| 14d | `ALL` | `jev_any_vs_prose_bot_control` | 1 | 2/5 (40.00%) | 0/1 (0.00%) | N/A | 0.4795 |
| 14d | `Human_Engineer` | `jev_flagged_vs_jev_clean` | 2 | 36/43 (83.72%) | 8/10 (80.00%) | 0.9388 [0.1576, 5.5936] | 0.9453 |
| 14d | `Human_Engineer` | `jev_any_vs_no_bot_control` | 4 | 49/65 (75.38%) | 306/365 (83.84%) | 1.3223 [0.5146, 3.3978] | 0.5244 |
| 14d | `Coding_Agent` | `jev_flagged_vs_jev_clean` | 4 | 19/47 (40.43%) | 49/78 (62.82%) | 3.5528 [0.8656, 14.5817] | 0.07319 |
| 14d | `Coding_Agent` | `jev_any_vs_no_bot_control` | 4 | 68/125 (54.40%) | 144/254 (56.69%) | 0.6984 [0.4098, 1.1902] | 0.1872 |
| 14d | `Coding_Agent` | `jev_any_vs_prose_bot_control` | 1 | 2/5 (40.00%) | 0/1 (0.00%) | N/A | 0.4795 |

### Hotspot Confounding Control & Post-Jev Pre-Merge Fix Mediation
- **Hotspot control status:** `computed`
- **Mediation arms (u14 Jev_Flagged with commit timelines):** 2 arms evaluated.

## 3. Generated Audit Artifacts
- JSON summary: `jev_judgment_and_szz_outcomes.json`
- Within-repo SZZ CSV: `jev_szz_within_repo_outcomes_log.csv`
- Verbosity vs. judgment CSV: `jev_verbosity_vs_human_judgment_log.csv`
- Verbose log: `verbose_p16_jev_judgment_and_szz_20261122_193240.log`
