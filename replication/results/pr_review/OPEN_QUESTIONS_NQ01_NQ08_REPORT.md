---
title: "Open Questions NQ-01 through NQ-08 Empirical Synthesis Report"
intent: "Comprehensive dynamic empirical synthesis of NQ-01..NQ-08 covering Jev tollgates, PR description bloat, ping-pong rework, fast LGTM bimodality, assertion theater, language turnover, and reviewer burstiness/fatigue."
type: "study-protocol"
status: "active"
skills_applied:
  - "empirical-methodologist"
last_updated: "2026-11-22"
---
# Open Questions NQ-01 through NQ-08 Empirical Synthesis Report

**Generated (UTC):** `2026-11-22T19:32:54.649927+00:00` | **Hotspot Control:** `True` | **14d Survival:** `True`

## NQ-01 & NQ-02: Jev Decision-Model Tollgates & Bare-Git SZZ
- Ingested directly from `jev_judgment_and_szz_outcomes.json` (see `JEV_JUDGMENT_AND_SZZ_REPORT.md` for full regime and Mantel-Haenszel tables).

## NQ-03: PR Description Bloat / Walkthrough Theater vs. Scrutiny & SZZ

| Bucket | Scrutiny N | Human CR % | Rubber-Stamp % |
| :--- | ---: | ---: | ---: |
| `1_<100` | 237 | 7.17% | 60.76% |
| `2_100-499` | 1,182 | 8.71% | 46.45% |
| `3_500-1499` | 1,627 | 10.51% | 46.04% |
| `4_1500-2999` | 1,929 | 20.84% | 38.21% |
| `5_3000+` | 1,022 | 22.02% | 32.78% |

## NQ-04: Review Ping-Pong Thrashing & Force-Push Rework vs. SZZ
- Total stratified records written to `nq04_pingpong_rework_szz_log.csv`: 28.

## NQ-05: Fast LGTM vs. Stalled Review Queue Bimodality & Bot-First Ordering
- Total `u30` human-reviewed AIDev PRs: **1,694** (disclosed negative clock-skew PRs: open-to-review=0, review-to-merge=3).

## NQ-06: Assertion Theater (Test Adaptedness vs. Real SZZ Bugfixes)
- Matched `AgenticPRs x SZZ u30` PRs: **189**; full SZZ test-presence audit exported to `nq06_assertion_theater_szz_log.csv`.

## NQ-07: Language-Regime Asymmetry & Code Turnover

| Corpus | Language Regime | N | SZZ 14d % | SZZ 30d % | 14d Turnover % | 30d All-Commit Turnover % | 30d Bugfix File Churn % |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AIDev` | `Compiled_Systems` | 452 | 26.55% | 33.19% | 45.00% | 54.17% | 18.11% |
| `AIDev` | `Dynamic_Gradual` | 2,543 | 33.74% | 42.23% | 56.86% | 66.18% | 25.29% |
| `AIDev` | `Managed_OO` | 536 | 48.88% | 56.16% | 66.01% | 71.32% | 42.24% |
| `AIDev` | `Other` | 507 | 30.97% | 37.67% | 48.74% | 56.85% | 22.10% |
| `AIDev_HumanBaseline` | `Compiled_Systems` | 216 | 24.54% | 32.41% | 51.35% | 61.45% | 13.76% |
| `AIDev_HumanBaseline` | `Dynamic_Gradual` | 1,460 | 36.16% | 46.03% | 54.89% | 66.63% | 25.44% |
| `AIDev_HumanBaseline` | `Managed_OO` | 56 | 23.21% | 25.00% | 31.12% | 44.04% | 10.23% |
| `AIDev_HumanBaseline` | `Other` | 169 | 33.73% | 39.64% | 58.08% | 65.97% | 26.47% |

## NQ-08: Acute Reviewer Queue Burstiness & 60-Day CodeRabbit Fatigue
- Reviewer workload Gini coefficient across **2,491** human reviewers: **0.6747**.
- CodeRabbit merge-rate disclosure: `merge_status_absent_in_zenodo_schema (all 99,454 PRs state='closed'; merge_rate_pct=None)`.

## Audit Tables Generated
- `nq03_pr_description_bloat_log.csv`
- `nq04_pingpong_rework_szz_log.csv`
- `nq05_review_speed_bimodality_log.csv`
- `nq06_assertion_theater_szz_log.csv`
- `nq07_language_turnover_szz_log.csv`
- `nq08_queue_burst_and_fatigue_log.csv`
