---
title: "Dataset Inventory, Provenance & Schema Specifications: pr-review-replication"
intent: "Comprehensive data dictionary, physical schema mapping, row counts, Zenodo/Hugging Face persistent identifiers, and methodological disclosures for all public corpora supporting the Five Viral AI Code-Review Myths study."
type: "reference"
status: "active"
last_updated: "2026-11-22"
---

# Dataset Inventory, Provenance & Schema Specifications (`pr-review-replication`)

All empirical claims in [`paper/draft_v1_ieee_software.md`](https://github.com/kumarshaz/pr-review-replication/blob/main/paper/draft_v1_ieee_software.md) and its companion 3-part practitioner blog series are grounded in **100% genuine public repository telemetry** across `130,000+` real GitHub pull requests and `300` local `--bare --filter=blob:none` git clones, with zero synthetic data or paid API requirements.

---

## 1. Core Public Corpora & Persistent Identifiers

| Corpus | Local Raw Path (`scratch/`) | Persistent Identifier / Source | Scale Verified | Primary Empirical Role |
| :--- | :--- | :--- | :--- | :--- |
| **CodeRabbit OSS Activities** | `scratch/coderabbit/` | Zenodo `10.5281/zenodo.21878471` (Nascimento et al., 2025) | `99,454` PRs · `481` repos (`457` tenure repos; `345` `.coderabbit.yaml` configs) | **Myth 2 (`NQ-08`):** 180+ day comment stability (`4.20–4.34`/PR), `87,899`-PR fixed-cohort survivorship (`362` repos), and bug-label climb (`3.13% -> 5.86%`). |
| **AIDev Curated Benchmark** | `scratch/aidev/` | Zenodo `10.5281/zenodo.16899501` · HF `hao-li/AIDev` (Li, Zhang, & Hassan, MSR 2026) | `33,596` agent PRs · `6,618` human PRs · `28,875` reviews · `2,807` repos ($\ge 100$ stars) | **Myths 1, 3, 4 & 5 (`NQ-03`, `NQ-05`, `NQ-08`, `SM-02`, `SM-04`, `RV-02`):** PR description length (`3.07x` CR), Reviewer Gini (`0.6747`), burst load (`-21.12 pp`), Bot-First `7.1x` anchoring collapse, force-push & language SZZ. |
| **TypeSafe Jev Decision-Model PRs** | `scratch/jev_pr_reviews/` | Public GitHub PRs & Bare Git across `26` adopter repositories | `6,055` PRs · `553` Jev-evaluated (`312` hydrated across `getsentry/sentry`, `craftmilldev/loopway`, `craftmilldev/sesh`) | **Myth 5 (`NQ-01`, `NQ-02`, `SM-05`):** Pre-merge author self-triage (`-24.14 pp` merge drop, `5.04x` self-closure), cold-file `OR_MH = 0.9537`, `Jev_Clean` `+0.4205` DiD complacency, `89.14%` agent advisory override. |
| **Bare-Git Tier-1 SZZ Clones** | `scratch/git_clones/` | Public GitHub (`git clone --bare --filter=blob:none`) | `300` clones · `10,410` linked merged PRs (`8,936` u14d; `7,982` u30d) | **Post-Merge Ground Truth (`NQ-02`, `NQ-04`, `NQ-06`, `NQ-07`):** Commit-attributed 14d/30d SZZ bugfixes, hard reverts, and pre-PR 30-day file hotspot controls (`pre_pr_30d_hotspot_fixes == 0`). |
| **CodeReviewBench** | `scratch/code_review_bench/` | Hugging Face `code-review-bench/code-review-bench` | `1,135` online PRs (`15` bots) · `150` Task-2 human audits | **Myth 4 Context:** Prose-bot plausibility trap (`98.67%` actionable, `92.00%` relevant, `24.00%` factually accurate). |
| **GitHub-Agentic-PR-Dataset** | `scratch/agentic_prs/` | Hugging Face `mabujadallah/GitHub-Agentic-PR-Dataset` (MSR 2026) | `334,039` PRs · `49,042` test-quality evaluations | **Myth 5 (`NQ-06`):** Cross-corpus test adaptedness triangulation (`189` matched SZZ u30 PRs). |
| **CodeReviewer (Pre-LLM Baseline)** | `scratch/codereviewer/` | ESEC/FSE 2022 (Li et al., DOI `10.1145/3540250.3549112`) | `11,013` labeled human reviews | **Myth 1 & 4 Baseline:** Pre-LLM human critique length (`116.1` mean chars vs. `968.6` bot chars = `8.3x`). |
| **GHArchive Event Stream** | `scratch/gharchive/` | `data.gharchive.org` (`2025-07-15-15.json.gz`) | `164,140` hourly GitHub events | **Myth 4 Baseline:** Bot-only approval-to-CR clearance skew (`97.2%`, `34.2:1`). |

---

## 2. Acquiring Raw Corpora on a Fresh Machine

Raw parquet and SQLite datasets (>100 MB) are excluded from Git via `.gitignore` and archived publicly on Zenodo and Hugging Face. All `36` processed canonical JSON, Markdown, and CSV evidence tables (`~4.5 MB` total) are checked directly into [`results/pr_review/`](results/pr_review/) so readers can inspect and audit results immediately without downloading raw blobs.

To download the raw public corpora and clone the Tier-1 bare-git repositories automatically (zero GitHub API tokens required):

```bash
python3 replication/scripts/00_fetch_datasets.py --all --clone-tier 1
```

---

## 3. Methodological Data Disclosures

1. **CodeRabbit Zenodo Schema (`state='closed'`):** Every row in Zenodo `10.5281/zenodo.21878471` (`99,454` PRs) records `state='closed'` without an explicit `merged` boolean. Accordingly, `merge_rate_pct` is explicitly encoded as `null` in `open_questions_nq01_nq08_results.json` and never estimated.
2. **Purified 38-Bot Catalog:** [`pipeline/config/bot_catalog.py`](pipeline/config/bot_catalog.py) enforces `TIER1_REVIEW_BOTS` (`38` verified review/SAST bots) while excluding coding-agent author self-replies (`Copilot`, `copilot-swe-agent[bot]`), CI/dependency bots, and `graphite-app[bot]` merge-queue banners in `pr_comments.parquet`.
3. **Zero Fabrication:** No random distributions, mock fixtures, or synthetic placeholders exist anywhere in the repository.
