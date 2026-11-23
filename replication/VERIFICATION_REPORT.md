---
title: "PR Review Myths & Playbooks: Open-Science Verification Certificate & SHA-256 Ledger"
intent: "Permanent audit certificate documenting the independent verification suite results, zero-leakage and zero-fabrication audits, and SHA-256 checksums for all 36 canonical Track-3 replication artifacts."
type: "peer-review"
status: "active"
last_updated: "2026-11-22"
---

# Five Viral AI Code-Review Myths (`pr-review-replication`) — Open-Science Verification Certificate

- **Verification Command:** `python3 replication/run_replication.py`
- **Independent Challenge Assertions:** **81 / 81 PASS (`0` failed — `VERDICT: APPROVE`)**
- **Raw Parquet DuckDB Audit Mode:** `FULL_RAW_AND_CANONICAL`
- **Empirical Traceability:** `99,454` CodeRabbit OSS PRs (`87,899` fixed-cohort across `362` repos), `33,596` AIDev agent PRs + `6,618` human baselines, `28,875` formal reviews across `2,491` distinct human reviewers, `6,055` mined TypeSafe Jev PRs (`312` hydrated), `150` `CodeReviewBench` human audits, and `10,410` commit-attributed SZZ merged PRs across `300` local bare-git clones (`0` `k60d` boundary leaks).
- **Verified Five-Myth Claims (`BH-FDR q < 0.05`):**
  - **Myth 1 Reversed (`NQ-03`):** `<100`-char (`60.76%` stamp / `7.17%` CR) vs. `3,000+`-char (`32.78%` stamp / `22.02%` CR, **`3.07x`**, `q = 1e-6`, Power `100%`).
  - **Myth 2 Refuted (`NQ-08`):** CodeRabbit flatlines at `4.20–4.34` comments/PR past Day 181 (`zero_comment_pct < 0.20%`) while bug labels climb `3.13% -> 5.86%` (`merge_rate_pct` explicitly disclosed as `null`).
  - **Myth 3 Refuted & Reframed (`NQ-08`):** High-burst (`5+`/24h) cuts stamping `-21.12 pp` (`44.05% -> 22.93%`); true crisis is **`Gini = 0.6747`** (`91.8%` on `6y+` veterans at `6.39%` CR vs. `2–6y` at `13.64%` CR).
  - **Myth 4 Refuted (`NQ-05`, `SM-02`, `SM-04`):** `Bot_First` collapses human CR **`7.1x`** (`26.74% -> 3.76%`, `p = 2.29e-13`, Power `100%`) and compresses merge `4.20x` (`160.3m -> 38.2m`); `2+` stacked bots drop CR to `2.20%` (`N = 182`).
  - **Myth 5 Nuanced (`NQ-01/02/04/06/07`):** Jev pre-merge self-triage `-24.14 pp` (`5.04x` self-close, Power `99.97%`), cold-file SZZ null (`OR_MH = 0.9537`), `Jev_Clean` DiD `+0.4205` (`7x` complacency), `89.14%` agent advisory override, post-review force-push `+21.01 pp` 30d SZZ (`p = 0.0046`), cold-file tests `-5.47 pp` (`p = 0.0107`), and `Managed_OO` `56.16%` vs. Human `25.00%` 30d SZZ.
- **Integrity & Boundary Hygiene:** Zero synthetic/fabricated markers across `replication/**/*.py`; zero local `/home/` path or private workspace leakage across `paper/` and `replication/results/pr_review/`.

---

## Canonical SHA-256 Artifact Checksum Ledger (`36` Track-3 Artifacts)

| # | Relative Artifact Path (`replication/results/pr_review/`) | Bytes | SHA-256 |
| :-: | :--- | ---: | :--- |
| 1 | `JEV_JUDGMENT_AND_SZZ_REPORT.md` | 6,292 | `e87df5e2bc3c88e56f152c16760c99327f1ff48dbad2c2d0ca4d927b175f7471` |
| 2 | `OPEN_QUESTIONS_NQ01_NQ08_REPORT.md` | 3,187 | `e82170bdbf98994ad4571f31442aa48a818151dd49a554e88d70d520783ce832` |
| 3 | `SAMPLE_SIZE_EXPANSION_AND_POWER_REPORT.md` | 14,474 | `637ad03423cf8c7592932a22596108b08d11bc8997b43f9f84ceaa3beb38909b` |
| 4 | `empirical_results_summary.json` | 26,283 | `d9c39bd5c81b87b1cbb980928127e7e825ea92049e65df88c9a335b59b751870` |
| 5 | `jev_judgment_and_szz_outcomes.json` | 100,196 | `b0548a4d0451ee7422260c8a3352000531e3af39f4d9df85e22a290bd3e87693` |
| 6 | `jev_offline_reparse_audit.json` | 6,505 | `176bfe20580e7b4af94fee10ddee4e2fa9e44395cd3b5768a8aa320f0e81b4ec` |
| 7 | `jev_vs_prose_tollgate_results.json` | 24,367 | `d530736aa370700dc63115a202d796975ca49003ecdaae61fbcd77c49442f3db` |
| 8 | `msr_aidev_results.json` | 20,169 | `c4b6333ee2f0193e2d9b1164649b6d1403d10143c5d25d5e90a4e73adb09e61d` |
| 9 | `multi_dataset_triangulation_results.json` | 289,083 | `07672e37582d97a10638eb5be67ec1b95824ff45ad32456dcb96cd2bb8186ef0` |
| 10 | `open_questions_nq01_nq08_results.json` | 204,961 | `10a3b122ae758489eb01c1bb39d88cccb66d0356594cc6e97eea066ac847ae93` |
| 11 | `open_vectors_rv01_rv10_results.json` | 49,336 | `61f0665f5127e80a0a11d21a7f71410922cdbf4a58fec7608b8813325f4b166d` |
| 12 | `raw_patch_and_sociotechnical_results.json` | 26,245 | `5c00b5b93e2cbad9a7b18a95f4c6a061bdee4431ab6edd6b77157be7a161a76f` |
| 13 | `sample_size_and_power_audit_results.json` | 23,478 | `df0ecb0aa4eeca688aaac05a72a30bee635f34d60d6ef6f9a1d12c7c973ad3ca` |
| 14 | `szz_and_constraints_summary.json` | 100,271 | `71cd9d326c94131ea8ca67e2a2aa4cc80a6143ac1cab79ed6d667ebabf7719df` |
| 15 | `data_tables/analyzed_human_reviewed_prs_log.csv` | 980,460 | `87ba289459ff9d689101f9a0705d273cb7d14bce5e8e34e940ae776af10c70f7` |
| 16 | `data_tables/analyzed_repositories_log.csv` | 300,781 | `2f4b304866df76e85321c3106854f4151b48ff6ad162c261a1eb70d3057f7858` |
| 17 | `data_tables/code_review_bench_15tools_log.csv` | 1,924 | `78cccfb40e35bc0324bceca9a49451bbcaa7450e64a1ce2e4aeed8aa13c7b1bd` |
| 18 | `data_tables/coderabbit_policy_outcomes_log.csv` | 524 | `4e9e90a87e2b8cd4fb7200168e5edac4cec37a0d1e5a0eaad2717dffc5c1a3ae` |
| 19 | `data_tables/human_veto_overrides_and_dismissals_log.csv` | 48,386 | `fcfbfd02dc5fb947460d2094a72b3b2d58f83570e795ec933d421cbe48f63c72` |
| 20 | `data_tables/jev_2x2_tollgate_effectiveness_log.csv` | 1,639 | `a2dfe08be6e8dc577b267cc7caad6acbf39cd069da805dc5cf90babb7926eec2` |
| 21 | `data_tables/jev_decision_model_tollgate_log.csv` | 2,110 | `f55306765d3c2491c41952297ade0cebabbb9f9b891d696bdf6b75c9ccd8a07c` |
| 22 | `data_tables/jev_szz_within_repo_outcomes_log.csv` | 8,033 | `28a0af469c23e7d84c6fb7b7a79dd8a838061627ca07531a00a83a8b422b8764` |
| 23 | `data_tables/jev_top_rules_and_commit_followthrough_log.csv` | 2,446 | `be0773945460ce8c7fb67b5dfef70c7304aa4c6575cfdab871b89206ab4a37e5` |
| 24 | `data_tables/jev_verbosity_vs_human_judgment_log.csv` | 729 | `1ae97b3b62522cd0654d1fbbab42496676fc73562ee6838976afd3eff662dfcc` |
| 25 | `data_tables/multi_dataset_summary_log.csv` | 5,754 | `77f70bf5d78a70560cfed8c53aaf99b33c67bda34b9133889b6e77c5359d227c` |
| 26 | `data_tables/multi_scale_sample_persistence_log.csv` | 8,603 | `8550df7b803ef9bf9e65b17954b56f2372c90e00b35cc8bb7acd56de9746b2b9` |
| 27 | `data_tables/nq03_pr_description_bloat_log.csv` | 1,170 | `1eb756d72a92e56b8142d202f1db648e99f49647d04eb54b4cf4da2da1c05341` |
| 28 | `data_tables/nq04_pingpong_rework_szz_log.csv` | 2,944 | `a7c54cf83769fa19fdc869ad32095c37bb7749d8eeb6c3b16e62ea2407283742` |
| 29 | `data_tables/nq05_review_speed_bimodality_log.csv` | 1,133 | `9e5d0765fe0d47f9facea392e215dbce4601a98f914fa19bfb7a9f9981febc19` |
| 30 | `data_tables/nq06_assertion_theater_szz_log.csv` | 3,506 | `c26f66f803cb2d9223c6125670296ae4bf1031fa72af3666690d8d7c846d3a17` |
| 31 | `data_tables/nq07_language_turnover_szz_log.csv` | 4,925 | `2eea7e955739d2846a9b77aa5c3acce1be928ed84971977df72cb95366841f5e` |
| 32 | `data_tables/nq08_queue_burst_and_fatigue_log.csv` | 1,954 | `aa690f06167b4b18f8597df5a696519c15f17dda3d4974d85f1033ab1afc63f1` |
| 33 | `data_tables/open_vectors_scorecard_log.csv` | 1,647 | `21c06b32550e25576906a53ce731fa77f17557f2e9ce2cdc2fa1c875f53a0999` |
| 34 | `data_tables/raw_dataset_inventory_log.csv` | 2,505 | `4b2c57c7af33f082f8940ffc4a312d750b3e005652f193629abece53a7b7adde` |
| 35 | `data_tables/review_bot_reputation_and_brain_log.csv` | 1,576 | `a3549892b663632a6e6aa60c7ef79dadf5c4747d7e2443d074d25798997f508a` |
| 36 | `data_tables/szz_defect_traceability_ledger.csv` | 2,455,927 | `ee2e977d911ea4c74952bc5c8d86551967cbad709ae116286d895de419d5d5c3` |
