---
title: "Five Viral Myths of AI Code Review Fatigue: Publication & Open-Science Replication Package"
intent: "Top-level overview, verified five-myth findings, direct evidence map for the IEEE Software manuscript and 3-part blog series, and 1-command verification guide for pr-review-replication."
type: "index"
status: "active"
last_updated: "2026-11-22"
---

# Five Viral Myths of AI Code Review Fatigue—Tested Against 130,000+ Production Pull Requests

**Author:** Shashi Nath Kumar · **ORCID:** [`0009-0001-2864-4241`](https://orcid.org/0009-0001-2864-4241) · **SSRN Preprint:** [`7742641`](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7742641) · **Zenodo Dataset DOI:** [`10.5281/zenodo.24452362`](https://doi.org/10.5281/zenodo.24452362) · **License:** [Apache-2.0](LICENSE)

This repository provides the practitioner manuscript ([`paper/Five_Viral_Myths_AI_Code_Review_Fatigue_SSRN_Preprint.pdf`](paper/Five_Viral_Myths_AI_Code_Review_Fatigue_SSRN_Preprint.pdf) · [SSRN Abstract `7742641`](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7742641) · Markdown source [`paper/draft_v1_ieee_software.md`](https://github.com/kumarshaz/pr-review-replication/blob/main/paper/draft_v1_ieee_software.md)) and the complete open-science replication package (`36` SHA-256 verified JSON/MD/CSV evidence artifacts archived at [Zenodo `10.5281/zenodo.24452362`](https://doi.org/10.5281/zenodo.24452362) + standalone analysis pipeline scripts) backing both the paper and the companion **3-part blog series** on [`kumarshaz.github.io`](https://kumarshaz.github.io):

- **Part 1 (Flagship Essay):** *Five Viral AI Code-Review Myths—Tested Against 130,000+ Production Pull Requests*
- **Part 2 (Practitioner Note):** *Human-First Blind Review: Why Letting an AI Bot Speak First Collapses Human Vetoes 7.1x*
- **Part 3 (Executive Perspective):** *The Senior Reviewer Gini Trap (0.675): Replacing Vanity AI Velocity Metrics with Board-Level Engineering KPIs*

---

## 1. Evidence Map: Where Every Empirical Claim Lives

| Empirical Claim / Blog & Paper Topic | Verified Headline Telemetry (`BH-FDR q < 0.05`, Zero Synthetic Data) | Primary Evidence Artifacts | Generating Script |
| :--- | :--- | :--- | :--- |
| **Myth 1 Reversed (`NQ-03`)**<br>PR Description Bloat | `<100` chars (`N=237`): `60.76%` stamp / `7.17%` CR vs. `3,000+` chars (`N=1,022`): **`22.02%` CR (`3.07x`**, `q=1e-6`, Power `100%`) & `32.78%` stamp (`-46.1%`); walkthrough SZZ `37.58%` vs. `43.36%`. | [`nq03_pr_description_bloat_log.csv`](replication/results/pr_review/data_tables/nq03_pr_description_bloat_log.csv) · [`open_questions_nq01_nq08_results.json`](replication/results/pr_review/open_questions_nq01_nq08_results.json) | [`p17_open_questions_nq01_to_nq08.py`](replication/pipeline/src/pipelines/p17_open_questions_nq01_to_nq08.py) |
| **Myth 2 Refuted (`NQ-08`)**<br>CodeRabbit 60-Day Cliff | `99,454` CodeRabbit PRs (`457` repos; `87,899` fixed cohort across `362` repos surviving `>=61d`): comments dip `4.92 -> 4.08` by Day 30, then flatline at **`4.20–4.34`/PR past Day 181** (`zero_comment_pct < 0.20%`) while bug labels climb **`3.13% -> 5.86%`** (`assertive 8.90%`). | [`nq08_queue_burst_and_fatigue_log.csv`](replication/results/pr_review/data_tables/nq08_queue_burst_and_fatigue_log.csv) · [`coderabbit_policy_outcomes_log.csv`](replication/results/pr_review/data_tables/coderabbit_policy_outcomes_log.csv) | [`p17_open_questions_nq01_to_nq08.py`](replication/pipeline/src/pipelines/p17_open_questions_nq01_to_nq08.py) |
| **Myth 3 Refuted & Reframed (`NQ-08`)**<br>Burst vs. Senior Gini Trap | High-burst (`5+`/24h, `N=4,458`) cuts stamping **`-21.12 pp`** (`44.05% -> 22.93%`, Power `100%`). True crisis is **`Gini = 0.6747`** (`2,491` reviewers): **`91.8%`** (`3,317/3,615`) on `6y+` veterans (`6.39%` CR) vs. `2–6y` (`13.64%` CR) and `<2y` (`1.28%` CR). | [`nq08_queue_burst_and_fatigue_log.csv`](replication/results/pr_review/data_tables/nq08_queue_burst_and_fatigue_log.csv) · [`analyzed_human_reviewed_prs_log.csv`](replication/results/pr_review/data_tables/analyzed_human_reviewed_prs_log.csv) | [`p17_open_questions_nq01_to_nq08.py`](replication/pipeline/src/pipelines/p17_open_questions_nq01_to_nq08.py) |
| **Myth 4 Refuted (`NQ-05`, `SM-02/04`)**<br>Bot-First Anchoring Law | `Bot_First` (`N=426`) vs. `Human_First` (`N=86`) collapses CR **`7.1x`** (`26.74% -> 3.76%`, `p=2.29e-13`, Power `100%`), surges stamping `+22.34 pp`, compresses merge `4.20x` (`160.3m -> 38.2m`). `2+` stacked bots = **`2.20%` CR** (`N=182`). `CodeReviewBench`: `24.00%` factual accuracy. | [`nq05_review_speed_bimodality_log.csv`](replication/results/pr_review/data_tables/nq05_review_speed_bimodality_log.csv) · [`multi_scale_sample_persistence_log.csv`](replication/results/pr_review/data_tables/multi_scale_sample_persistence_log.csv) · [`code_review_bench_15tools_log.csv`](replication/results/pr_review/data_tables/code_review_bench_15tools_log.csv) | [`p17_open_questions_nq01_to_nq08.py`](replication/pipeline/src/pipelines/p17_open_questions_nq01_to_nq08.py) · [`p14_sample_power_audit.py`](replication/pipeline/src/pipelines/p14_sample_power_audit.py) |
| **Myth 5 Nuanced (`NQ-01/02/04/06`)**<br>Compact Checkers, Cold-File Tests & Force-Push | `TypeSafe Jev` (`N=312`): `-24.14 pp` merge drop (`5.04x` self-close, Power `99.97%`), cold-file SZZ null (`OR_MH=0.9537`), `Jev_Clean` DiD `+0.4205` (`7x` complacency), `89.14%` agent override. Force-push spikes 30d SZZ **`+21.01 pp`** (`p=0.0046`); cold-file tests cut agent SZZ **`-5.47 pp`** (`p=0.0107`). | [`JEV_JUDGMENT_AND_SZZ_REPORT.md`](replication/results/pr_review/JEV_JUDGMENT_AND_SZZ_REPORT.md) · [`jev_judgment_and_szz_outcomes.json`](replication/results/pr_review/jev_judgment_and_szz_outcomes.json) · [`nq04_pingpong_rework_szz_log.csv`](replication/results/pr_review/data_tables/nq04_pingpong_rework_szz_log.csv) · [`nq06_assertion_theater_szz_log.csv`](replication/results/pr_review/data_tables/nq06_assertion_theater_szz_log.csv) · [`szz_defect_traceability_ledger.csv`](replication/results/pr_review/data_tables/szz_defect_traceability_ledger.csv) | [`p16_jev_judgment_and_szz_outcomes.py`](replication/pipeline/src/pipelines/p16_jev_judgment_and_szz_outcomes.py) · [`p00b_build_szz_constraints.py`](replication/pipeline/src/pipelines/p00b_build_szz_constraints.py) |
| **Board KPI Stratification (`NQ-07`)**<br>Language-Tier Bare-Git SZZ | `Compiled_Systems` (Rust/C++) near parity (`33.19%` vs. `32.41%` 30d SZZ); `Managed_OO` (Java/C#) agent **`56.16%`** (`35.71%` cold-file, `42.24%` churn) vs. Human **`25.00%`**. | [`nq07_language_turnover_szz_log.csv`](replication/results/pr_review/data_tables/nq07_language_turnover_szz_log.csv) · [`OPEN_QUESTIONS_NQ01_NQ08_REPORT.md`](replication/results/pr_review/OPEN_QUESTIONS_NQ01_NQ08_REPORT.md) | [`p17_open_questions_nq01_to_nq08.py`](replication/pipeline/src/pipelines/p17_open_questions_nq01_to_nq08.py) |

---

## 2. Quickstart: 1-Command Verification

```bash
# 1. Create virtual environment & install pinned dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Verify all canonical results, 10,410-PR SZZ ledger, 36/36 SHA-256 checksums,
#    zero-leakage & AST zero-fabrication scans (works immediately offline in ~3s):
python3 replication/run_replication.py

# 3. (Optional) Download public raw Zenodo/HF corpora & Tier-1 bare-git clones
#    to also run live DuckDB raw-parquet recomputations & --recompute mode:
python3 replication/scripts/00_fetch_datasets.py --all --clone-tier 1
python3 replication/run_replication.py --recompute
```

**Zero-Fabrication Guarantee:** 100% genuine public repository telemetry (`99,454` CodeRabbit PRs, `33,596` AIDev agent PRs, `6,618` human baselines, `6,055` mined Jev PRs, and `10,410` commit-attributed SZZ PRs across `300` bare-git clones). Zero synthetic rows, mocked fixtures, or paid API requirements.

---

## 3. Repository Structure

```text
.
├── README.md                                          # Overview, evidence map & 1-command verification guide
├── LICENSE                                            # Apache License 2.0
├── CITATION.cff                                       # Machine-readable citation metadata (ORCID-linked)
├── .zenodo.json                                       # Zenodo Dataset release metadata
├── requirements.txt                                   # Pinned Python dependencies
├── environment.yml                                    # Conda environment specification
├── paper/
│   ├── README.md                                      # Manuscript manifest
│   └── draft_v1_ieee_software.md                      # IEEE Software feature manuscript (<= 4,200 words)
└── replication/
    ├── README.md                                      # Detailed verification & recomputation runbook
    ├── DATASETS.md                                    # Public dataset catalog, schemas & Zenodo/HF DOIs
    ├── datasets_manifest.yaml                         # Machine-readable dataset & Tier-1 clone manifest
    ├── study_protocol.md                              # Empirical study design, NQ-01..08 & validity controls
    ├── VERIFICATION_REPORT.md                         # Checked-in audit certificate & 36-artifact SHA-256 ledger
    ├── run_replication.py                             # 1-command master verification runner
    ├── scripts/
    │   ├── 00_fetch_datasets.py                       # Zero-API Zenodo/HF dataset & bare-git clone fetcher
    │   ├── 01_recompute_track3_pipeline.py            # Optional end-to-end raw-to-CSV recomputation runner
    │   └── 02_challenge_track3_replication.py         # Independent DuckDB, SZZ, SHA-256 & AST verifier
    ├── pipeline/                                      # Complete standalone empirical pipeline source code
    │   ├── config/                                    # Standalone paths.py, 38-bot catalog & TOML manifest
    │   └── src/                                       # p00..p17 analysis modules, handlers & stats_utils
    └── results/
        └── pr_review/                                 # 36 SHA-256 verified JSONs, MD reports & 22 CSV ledgers
            ├── export_checksum_manifest.json
            ├── OPEN_QUESTIONS_NQ01_NQ08_REPORT.md
            ├── JEV_JUDGMENT_AND_SZZ_REPORT.md
            ├── SAMPLE_SIZE_EXPANSION_AND_POWER_REPORT.md
            ├── open_questions_nq01_nq08_results.json
            ├── jev_judgment_and_szz_outcomes.json
            └── data_tables/                           # 22 traceable CSV audit ledgers (incl. 10,410-PR SZZ)
```

---

## 4. License & Open-Science Badging
Distributed under the [Apache License 2.0](LICENSE). Engineered to comply with ACM Artifact Evaluation standards for **Artifacts Available**, **Artifacts Evaluated – Functional**, and **Artifacts Evaluated – Reusable**.
