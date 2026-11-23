---
title: "PR Review Myths & Playbooks: Open-Science Verification Runbook"
intent: "Step-by-step verification protocol, environment setup, full pipeline recomputation instructions, and evidence file index for pr-review-replication."
type: "reference"
status: "active"
last_updated: "2026-11-22"
---

# `pr-review-replication`: Open-Science Verification Runbook (`replication/`)

This directory contains the self-contained verification runner, standalone end-to-end empirical pipeline scripts (`pipeline/`), canonical processed evidence artifacts (`36` SHA-256 verified JSON/MD/CSV files in `results/pr_review/`), and raw public dataset downloader supporting [`paper/draft_v1_ieee_software.md`](https://github.com/kumarshaz/pr-review-replication/blob/main/paper/draft_v1_ieee_software.md) and its companion 3-part blog series.

---

## 1. Fast 1-Command Verification (`~3–5` Seconds)

```bash
python3 replication/run_replication.py
```

The master orchestrator runs [`scripts/02_challenge_track3_replication.py`](scripts/02_challenge_track3_replication.py) without mutating checked-in canonical tables:
1. **Raw Public Parquet & Independent DuckDB Audit** *(automatically enabled when `scratch/` datasets are present)*: Verifies raw row counts across `AIDev`, `CodeRabbit` (`99,454`), `TypeSafe Jev` (`6,055`), `CodeReviewer` (`11,013`), `CodeReviewBench` (`150`), and `AgenticPRs` (`334,039`), and independently recomputes CodeRabbit comment averages, `Gini = 0.6747` across `2,491` human reviewers, `24.00%` prose-bot factual accuracy, and `116.1`-char pre-LLM human comments directly via DuckDB.
2. **All Five Myths (`NQ-01`–`NQ-08`, `SM-02`, `SM-04`, `SM-05`) Assertions:** Audits every reported headline metric, `BH-FDR q`-value, Wilson CI, and statistical power value.
3. **Bare-Git SZZ Ledger Integrity:** Audits all `10,410` linked merged PRs in `results/pr_review/data_tables/szz_defect_traceability_ledger.csv` (`0` `k60d` boundary leaks, `pre_pr_30d_hotspot_fixes >= 0`, `0` NaN/Inf).
4. **Cryptographic SHA-256 Verification:** Validates all `36 / 36` exported JSON, Markdown, and CSV artifacts against `results/pr_review/export_checksum_manifest.json`.
5. **Zero-Fabrication AST & Zero-Leakage Boundary Scan:** AST-scans every `.py` file under `replication/` for zero random/synthetic generation and confirms zero local machine path leakage across all tracked files.

---

## 2. Optional Full Raw-to-CSV Pipeline Recomputation

To download all public raw corpora and Tier-1 bare-git clones (zero GitHub API keys required) and re-run the complete analysis scripts (`pipeline/src/pipelines/p00..p17`) into an isolated verification folder:

```bash
# 1. Fetch public Zenodo/Hugging Face datasets & bare-git clones
python3 replication/scripts/00_fetch_datasets.py --all --clone-tier 1

# 2. Recompute Track-3 empirical outputs end-to-end and verify
python3 replication/run_replication.py --recompute
```

---

## 3. Audit Certificate
See [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) for the complete checked-in verification verdict and SHA-256 checksum ledger.
