---
title: "Empirical Study Protocol: Five Viral Myths of AI Code Review Fatigue"
intent: "Specifies the empirical study design, research questions (NQ-01 to NQ-08), multi-corpus datasets, purified 38-bot attribution rules, hotspot confounding controls, BH-FDR adjustments, and threats to validity for pr-review-replication."
type: "study-protocol"
status: "active"
last_updated: "2026-11-22"
---

# Empirical Study Protocol: Testing Five Viral AI Code-Review Myths Across `130,000+` Production Pull Requests

This document defines the empirical protocol, cohort definitions, statistical tests, and validity guardrails behind [`paper/draft_v1_ieee_software.md`](https://github.com/kumarshaz/pr-review-replication/blob/main/paper/draft_v1_ieee_software.md) and its companion 3-part practitioner blog series.

---

## 1. Research Questions Mapped to Viral Industry Myths (`NQ-01`–`NQ-08`)

| Myth Tested | Pipeline Vector | Hypothesis & Operational Metric | Primary Dataset(s) |
| :--- | :---: | :--- | :--- |
| **Myth 1:** Long AI PR descriptions induce rubber-stamping | `NQ-03` | Stratify human `CHANGES_REQUESTED` veto rate and bare `APPROVED` rubber-stamping across 5 PR body-character buckets (`<100` to `3,000+` chars) and compare 30d SZZ on structured walkthrough PRs. | `AIDev` (`5,997` human-reviewed PRs) + Bare-Git SZZ (`300` repos) |
| **Myth 2:** Teams abandon AI review bots after 60 days | `NQ-08` | Track longitudinal comment density, silence rate (`zero_comment_pct`), close latency, and bug-labeled PR rates from Days `0–15` past Day `181+`, controlled via fixed-cohort survivorship (`>= 61d` repos) and `.coderabbit.yaml` profile (`default`, `chill`, `assertive`). | `CodeRabbit OSS` (`99,454` PRs / `457` repos; `87,899` fixed cohort / `362` repos) |
| **Myth 3:** High-burst reviewers (`5+`/24h) rubber-stamp | `NQ-08` | Measure human CR veto and rubber-stamp rates across 24h burst buckets (`1`, `2–4`, `5+`/24h), Reviewer Workload Gini across all distinct human reviewers, and CR rates across GitHub account tenure (`<2y`, `2–6y`, `6y+`). | `AIDev` (`16,886` formal human reviews, `2,491` reviewers, `3,615` tenure-matched) |
| **Myth 4:** Bot-first & stacked AI bots add free safety | `NQ-05`, `SM-02`, `SM-04`, `RV-02` | Compare `1_Bot_First` vs. `2_Human_First` arrival ordering on human CR vetoes, bare rubber-stamping, and review-to-merge latency; test `2+` stacked bots beside 1 human, `2+` humans vs `1` human + `1` bot, and `191`-repo within-repo controls. | `AIDev` (`1,694` u30 arrival-ordered PRs; `3,121` shared-repo controls) + `CodeReviewBench` (`150` audits) |
| **Myth 5:** Compact checkers eliminate post-merge bugs | `NQ-01`, `NQ-02`, `NQ-04`, `NQ-06`, `NQ-07` | Separate upstream pre-merge author self-triage (`merge %`, `self-closure`, `post-Jev commits`) from hotspot-controlled cold-file SZZ (`OR_MH`, symmetric 14d DiD), post-review force-push 30d SZZ (`NQ-04`), cold-file test SZZ (`NQ-06`), and polyglot language tiers (`NQ-07`). | `TypeSafe Jev` (`6,055` PRs / `312` hydrated) + `300`-Clone Bare-Git SZZ (`10,410` merged PRs) |

---

## 2. Multi-Stage Zero-Fabrication Data Pipeline

1. **Zero-API Acquisition & Bare-Git Cloning (`p00_fetch_datasets.py`):** Downloads public Zenodo/Hugging Face corpora and clones `300` repositories using `--bare --filter=blob:none` without requiring paid LLM keys or GitHub tokens.
2. **Purified 38-Bot Catalog (`pipeline/config/bot_catalog.py`):** Isolates `38` verified Tier-1 review/SAST bots while excluding coding-agent self-replies (`Copilot`, `copilot-swe-agent[bot]`), CI/dependency bots, and merge-queue banners (`graphite-app[bot]` in general PR comments). Also reclassifies bot-operated `User`-typed accounts (`loopway-bot`, `all-hands-bot`, `sentry-bot`).
3. **Offline Decision-Signal Reparsing (`p00_reparse_jev_offline.py`):** Deterministically reparses `TypeSafe Jev` decision verdicts (`Jev_Clean` vs. `Jev_Flagged`) across `26` adopter repositories (`6,055` PRs) into structured verdicts without LLM inference.
4. **Bare-Git Commit-Attributed SZZ (`p00b_build_szz_constraints.py`):** Links `10,410` merged PRs to post-merge bugfix commits and hard reverts over uncensored `14d` (`8,936` PRs) and `30d` (`7,982` PRs) observation windows, computing pre-PR 30-day hotspot baselines (`pre_pr_30d_hotspot_fixes`) and enforcing zero `k60d` 61–90-day boundary leaks.
5. **Statistical Inference, Power & FDR Correction (`p14`, `p16`, `p17`):** Applies two-proportion $Z$-tests with Wilson 95% confidence intervals, achieved post-hoc statistical power, Fisher exact tests, Mann–Whitney $U$ tests, Cochran–Mantel–Haenszel within-repository stratification (`OR_MH`), symmetric 14d-vs-14d Difference-in-Differences, Gini concentration, and Benjamini–Hochberg FDR (`BH-FDR`, $q < 0.05$).

---

## 3. Confounding Controls & Methodological Disclosures

- **Simpson's Paradox Guardrail (Cold-File Stratification):** Because risky PRs cluster in pre-existing hotspot files (`pre_pr_30d_hotspot_fixes >= 1`, Mann–Whitney $p = 5.42 \times 10^{-7}$), naive pooled SZZ metrics invert both test effectiveness (`+9.70 pp` pooled $\to$ `-5.47 pp` cold-file) and Jev outcomes (`OR_MH = 3.55` pooled $\to$ `0.9537` cold-file). All causal post-merge SZZ claims are explicitly evaluated under cold-file stratification (`pre_pr_30d_hotspot_fixes == 0`).
- **Fixed-Cohort Survivorship Control (CodeRabbit):** Alongside all `99,454` PRs (`457` tenure repos), we verify the Day 181+ plateau on a strict fixed cohort of `87,899` PRs from `362` repositories surviving $\ge 61$ days.
- **Zenodo CodeRabbit Merge-Flag Disclosure:** All `99,454` rows in Zenodo `10.5281/zenodo.21878471` record `state='closed'` without a separate merged boolean; `merge_rate_pct` is explicitly set to `null` and never interpolated.
- **Zero Synthetic Data:** Every output table and JSON artifact is computed from real on-disk datasets and verified against automated AST zero-fabrication checks.
