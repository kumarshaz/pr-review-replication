---
title: "Multi-Scale Sample Size Persistence & Statistical Power Audit Report"
intent: "Audits how core MEIGS, bare-git SZZ ground-truth, and social-media findings hold across 6 concentric sample-size rings, computes exact 95% Wilson CIs and statistical power, and verifies post-expansion adequacy."
type: "study-protocol"
status: "active"
skills_applied:
  - "empirical-methodologist"
  - "skeptic-architect"
last_updated: "2026-11-22"
---

# Multi-Scale Sample Size Persistence & Statistical Power Audit (`Ring 1 N = 6,055` to `Ring 6 Published MSR 2026 Reference N = 932,791`)

**Generated UTC:** `2026-11-22T19:32:38.391263+00:00`  
**Audit Script:** `src/pipelines/p14_sample_power_audit.py`  
**Machine-Readable Table:** [`data_tables/multi_scale_sample_persistence_log.csv`](data_tables/multi_scale_sample_persistence_log.csv)

---

## 1. Concentric 6-Ring Scale Architecture (Post-Expansion Verified)

1. **Ring 6 — Global AIDev Unfiltered Population (Published MSR 2026 census reference: $N = 932,791$ PRs; local `aidev_all_repo.parquet` verified count: $116,211$ repos):** Macro agent adoption volume.
2. **Ring 5 — Full Curated $\ge 100$-Star Benchmark ($N = 33,596$ Coding-Agent PRs + $6,618$ Human Baseline PRs = $40,214$ PRs; plus $N = 76,734$ PRs across $323$ repos in `coderabbit_policy_outcomes_log.csv`).**
3. **Ring 4 & 4S — Within-Repository Matched Multi-Regime Cohorts & Bare-Git SZZ Ground Truth:** $N = 6,071$ merged PRs across $281$ shared multi-regime repos; $N = 16,319$ PRs across $810$ paired human+agent repos; and **$N = 10,410$ commit-attributed merged PRs (`8,936` uncensored 14d, `7,982` uncensored 30d)** across `300` local bare-git clones.
4. **Ring 3 — Formally Human-Reviewed Curated Subset (`Clean Unified 38-Bot Catalog`, $N = 5,997$):** `Cohort B (Human-Only)` = **$N = 4,321$** vs. `Cohort C (Tier-1 Review Bot + Human)` = **$N = 1,676$**.
5. **Ring 2 — Within-191-Shared-Repo Paired Human-Reviewed Subset ($N = 3,121$:** $N_B = 2,092$ vs. $N_C = 1,029$).
6. **Ring 1 — Broadened TypeSafe Jev Decision-Model Adopter Corpus:** **$N = 6,055$ mined PRs** (`553` Jev-evaluated PRs, `912` formal GitHub reviews, `$N = 105$` Sentry DML Human PRs, `$N = 348$` Pooled Jev Coding-Agent PRs).

---

## 2. Multi-Scale Persistence & Statistical Power Ledger (`alpha = 0.05`, Two-Sided)

| Scale Ring | Vector | Hypothesis Tested | Arm 1 ($k_1/n_1$, `%` `[95% CI]`) | Arm 2 ($k_2/n_2$, `%` `[95% CI]`) | Shift (`pp` / `%`) | $Z$ / $p$-value | Achieved Power | $N_{\text{req}}$ / Arm (80% / 90%) | Power Verdict |
| :--- | :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `Ring_2_Within_191_Shared_Repos (N=3,121)` | **`RV-02`** | Within-Repo Human Veto Suppression (Human-Only vs Bot+Human) | `Cohort_B_Shared191`: **16.11%** (337/2092) `[14.6%, 17.75%]` | `Cohort_C_Shared191`: **10.5%** (108/1029) `[8.77%, 12.52%]` | **-5.61 pp** (-34.9%) | `Z=4.216` (`p=2.48e-05`) | **99.19%** | `569` / `762` | `FULLY_POWERED (>=90%)` |
| `Ring_3A_Curated_Human_Reviewed_38Bot (N=5,997)` | **`RV-02`** | Global Curated Human Veto Suppression (Clean 38-Bot Catalog: Human-Only vs Bot+Human) | `Cohort_B_Clean38`: **17.26%** (746/4321) `[16.17%, 18.42%]` | `Cohort_C_Clean38`: **10.26%** (172/1676) `[8.9%, 11.81%]` | **-7.00 pp** (-40.6%) | `Z=6.758` (`p=1.40e-11`) | **100.0%** | `375` / `502` | `FULLY_POWERED (>=90%)` |
| `Ring_3A_Curated_Human_Reviewed (N=2,953)` | **`SM-02`** | Second-Reviewer Displacement: 2+ Humans (0 Bots) vs 1 Human + 1 AI Bot Veto Rate | `2plus_Humans_0_Bots`: **24.99%** (591/2365) `[23.29%, 26.77%]` | `1_Human_1_Bot`: **3.91%** (23/588) `[2.62%, 5.8%]` | **-21.08 pp** (-84.3%) | `Z=11.271` (`p=0.00e+00`) | **100.0%** | `38` / `50` | `FULLY_POWERED (>=90%)` |
| `Ring_3A_Curated_Human_Reviewed (N=2,138)` | **`SM-04`** | Stacked-Bot Bystander Collapse: 1 Human (0 Bots) vs 1 Human + 2+ Bots Veto Rate | `1_Human_0_Bots`: **7.92%** (155/1956) `[6.81%, 9.21%]` | `1_Human_2plus_Bots`: **2.2%** (4/182) `[0.86%, 5.51%]` | **-5.73 pp** (-72.3%) | `Z=2.816` (`p=4.86e-03`) | **94.11%** | `211` / `282` | `FULLY_POWERED (>=90%)` |
| `Ring_3A_Curated_Human_Reviewed (N=2,138)` | **`SM-04_RubberStamp`** | Stacked-Bot Rubber-Stamp Surge: 1 Human (0 Bots) vs 1 Human + 2+ Bots Rubber-Stamp Rate | `1_Human_0_Bots`: **60.28%** (1179/1956) `[58.09%, 62.42%]` | `1_Human_2plus_Bots`: **67.58%** (123/182) `[60.48%, 73.96%]` | **+7.31 pp** (+12.1%) | `Z=-1.932` (`p=5.34e-02`) | **50.23%** | `677` / `906` | `NEEDS_BROADENING (<80%)` |
| `Ring_3A_Curated_Human_Reviewed (N=5,997)` | **`SM-07`** | Intent-Oracle Paradox: Issue-Anchored (IBD=0) vs Unanchored Prompt PRs (IBD=1) Veto Rate | `Issue_Anchored_IBD0`: **18.03%** (816/4526) `[16.94%, 19.18%]` | `Intent_Deficit_IBD1`: **6.93%** (102/1471) `[5.74%, 8.35%]` | **-11.10 pp** (-61.5%) | `Z=10.267` (`p=0.00e+00`) | **100.0%** | `133` / `178` | `FULLY_POWERED (>=90%)` |
| `Ring_4A_Bot_Brain_Families (N=2,451)` | **`RV-06_14d`** | 14-Day Merged-PR Post-Merge Regression Rate: Deterministic SAST Gate vs MultiModel RAG Prose Bot | `1_Deterministic_SAST_Brain`: **15.67%** (34/217) `[11.43%, 21.1%]` | `2_MultiModel_RAG_Agentic_Brain`: **26.1%** (583/2234) `[24.32%, 27.96%]` | **+10.43 pp** (+66.6%) | `Z=-3.379` (`p=7.27e-04`) | **95.29%** | `236` / `315` | `FULLY_POWERED (>=90%)` |
| `Ring_4A_Bot_Brain_Families (N=2,451)` | **`RV-06_90d`** | 90-Day Merged-PR Post-Merge Regression Rate: Deterministic SAST Gate vs MultiModel RAG Prose Bot | `1_Deterministic_SAST_Brain`: **21.2%** (46/217) `[16.29%, 27.11%]` | `2_MultiModel_RAG_Agentic_Brain`: **52.15%** (1165/2234) `[50.08%, 54.21%]` | **+30.95 pp** (+146.0%) | `Z=-8.706` (`p=0.00e+00`) | **100.0%** | `37` / `49` | `FULLY_POWERED (>=90%)` |
| `Ring_4B_Within_281_Shared_Repos (N=6,071)` | **`RV-01_Fix14d_Within281`** | Within-281-Shared-Repo 14-Day Downstream Fix-PR Exposure: Reviewed vs Silent Gate | `Reviewed_In_Shared_Repos`: **73.92%** (1596/2159) `[72.03%, 75.73%]` | `Silent_In_Shared_Repos`: **81.88%** (3203/3912) `[80.64%, 83.05%]` | **+7.95 pp** (+10.8%) | `Z=-7.289` (`p=3.12e-13`) | **100.0%** | `425` / `568` | `FULLY_POWERED (>=90%)` |
| `Ring_4C_Paired_810_Repos (N=16,319)` | **`RV-01_PairedAcceptance`** | Within-810-Shared-Repo Merge Acceptance: Human Baseline PRs vs Coding-Agent PRs | `Human_Baseline_Paired`: **76.78%** (5044/6569) `[75.75%, 77.79%]` | `Coding_Agent_Paired`: **55.04%** (5366/9750) `[54.05%, 56.02%]` | **-21.75 pp** (-28.3%) | `Z=28.35` (`p=0.00e+00`) | **100.0%** | `73` / `98` | `FULLY_POWERED (>=90%)` |
| `Ring_4S_BareGit_SZZ_GroundTruth (N=2,844)` | **`RV-01_SZZ_14d_Reviewed_vs_Silent`** | Commit-Attributed 14d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+SilentOrSelfMerge | `SZZ_Agent+HumanOnly`: **29.66%** (350/1180) `[27.12%, 32.33%]` | `SZZ_Agent+SilentOrSelfMerge`: **40.32%** (671/1664) `[37.99%, 42.7%]` | **+10.66 pp** (+36.0%) | `Z=-5.841` (`p=5.19e-09`) | **100.0%** | `313` / `419` | `FULLY_POWERED (>=90%)` |
| `Ring_4S_BareGit_SZZ_GroundTruth (N=2,844)` | **`RV-01_SZZ_30d_Reviewed_vs_Silent`** | Commit-Attributed 30d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+SilentOrSelfMerge | `SZZ_Agent+HumanOnly`: **38.39%** (453/1180) `[35.66%, 41.2%]` | `SZZ_Agent+SilentOrSelfMerge`: **47.84%** (796/1664) `[45.44%, 50.24%]` | **+9.45 pp** (+24.6%) | `Z=-5.002` (`p=5.69e-07`) | **99.89%** | `431` / `576` | `FULLY_POWERED (>=90%)` |
| `Ring_4S_BareGit_SZZ_GroundTruth (N=1,680)` | **`RV-01_SZZ_30d_HO_vs_Bot`** | Commit-Attributed 30d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+ProseBot+Human | `SZZ_Agent+HumanOnly`: **38.39%** (453/1180) `[35.66%, 41.2%]` | `SZZ_Agent+ProseBot+Human`: **41.2%** (206/500) `[36.97%, 45.57%]` | **+2.81 pp** (+7.3%) | `Z=-1.079` (`p=2.81e-01`) | **18.96%** | `4762` / `6374` | `NEEDS_BROADENING (<80%)` |
| `Ring_4S_BareGit_SZZ_GroundTruth (N=1,680)` | **`RV-01_SZZ_Revert30d_HO_vs_Bot`** | Commit-Attributed 30d Hard Revert Rate: Agent+HumanOnly vs Agent+ProseBot+Human | `SZZ_Agent+HumanOnly`: **0.76%** (9/1180) `[0.4%, 1.44%]` | `SZZ_Agent+ProseBot+Human`: **0.6%** (3/500) `[0.2%, 1.75%]` | **-0.16 pp** (-21.3%) | `Z=0.362` (`p=7.17e-01`) | **6.59%** | `39982` / `53524` | `NEEDS_BROADENING (<80%)` |
| `Ring_4S_BareGit_SZZ_GroundTruth (N=523)` | **`RV-06_SZZ_30d_SAST_vs_ProseBot`** | Commit-Attributed 30d SZZ Bugfix Rate: Agent+DeterministicSAST vs Agent+ProseBot+Human | `SZZ_Agent+DeterministicSAST`: **65.22%** (15/23) `[44.89%, 81.19%]` | `SZZ_Agent+ProseBot+Human`: **41.2%** (206/500) `[36.97%, 45.57%]` | **-24.02 pp** (-36.8%) | `Z=2.28` (`p=2.26e-02`) | **62.55%** | `67` / `89` | `NEEDS_BROADENING (<80%)` |
| `Ring_4S_Paired_108_Repos_SZZ (N=3,947)` | **`RV-01_SZZ_30d_Human_vs_Agent`** | Within-Repo Commit-Attributed 30d SZZ Bugfix Rate: Human Baseline vs Coding-Agent PRs | `SZZ_Human_Baseline`: **43.37%** (821/1893) `[41.15%, 45.61%]` | `SZZ_Coding_Agent`: **37.39%** (768/2054) `[35.32%, 39.5%]` | **-5.98 pp** (-13.8%) | `Z=3.827` (`p=1.30e-04`) | **96.91%** | `1056` / `1413` | `FULLY_POWERED (>=90%)` |
| `Ring_4S_BareGit_SZZ_Constraints (N=4,038)` | **`RV-06_SZZ_30d_ConstraintTier`** | Commit-Attributed 30d SZZ Bugfix Rate: Low Architectural Constraints (Tier 0-1) vs High (Tier 2-3) | `Constraint_Tier_0_1`: **42.61%** (871/2044) `[40.48%, 44.77%]` | `Constraint_Tier_2_3`: **42.38%** (845/1994) `[40.22%, 44.56%]` | **-0.24 pp** (-0.6%) | `Z=0.151` (`p=8.80e-01`) | **5.26%** | `156978` / `210149` | `NEEDS_BROADENING (<80%)` |
| `Ring_4S_JevAdopters_SZZ (N=1,659)` | **`RV-01_SZZ_30d_JevRepos_Human_vs_Agent`** | Jev Adopter Repos Commit-Attributed 30d SZZ Bugfix Rate: Human Engineer vs Coding Agent (No-Bot Control) | `JevRepos_Human_NoBot`: **62.65%** (681/1087) `[59.73%, 65.48%]` | `JevRepos_Agent_NoBot`: **52.1%** (298/572) `[48.0%, 56.16%]` | **-10.55 pp** (-16.8%) | `Z=4.153` (`p=3.28e-05`) | **98.53%** | `344` / `460` | `FULLY_POWERED (>=90%)` |
| `Ring_4S_JevAdopters_SZZ_14d (N=2,195)` | **`RV-01_SZZ_14d_JevRepos_Human_vs_Agent`** | Jev Adopter Repos Commit-Attributed 14d SZZ Bugfix Rate: Human Engineer vs Coding Agent (No-Bot Control) | `JevRepos_Human_NoBot_14d`: **51.14%** (743/1453) `[48.57%, 53.7%]` | `JevRepos_Agent_NoBot_14d`: **37.74%** (280/742) `[34.32%, 41.28%]` | **-13.40 pp** (-26.2%) | `Z=5.953` (`p=2.63e-09`) | **100.0%** | `215` / `288` | `FULLY_POWERED (>=90%)` |
| `Ring_5_Full_Curated_Benchmark (N=22,624 Matched Merged)` | **`RV-07_ModeI_vs_ModeII`** | Silent Zero-Human-Review Gate Rate: Peer-Merged (Mode II) vs Operator Self-Merged (Mode I) | `Mode_II_Peer_Merged`: **39.9%** (1600/4010) `[38.39%, 41.42%]` | `Mode_I_Operator_Self_Merged`: **95.03%** (17688/18614) `[94.7%, 95.33%]` | **+55.13 pp** (+138.2%) | `Z=-89.304` (`p=0.00e+00`) | **100.0%** | `9` / `12` | `FULLY_POWERED (>=90%)` |
| `Ring_1_Jev_Sentry_Human_PRs (N=105)` | **`RV-05_SentryGate`** | getsentry/sentry Human PR Merge Rate: Jev Clean vs Jev Flagged | `Jev_Clean_Sentry`: **83.87%** (26/31) `[67.37%, 92.91%]` | `Jev_Flagged_Sentry`: **62.16%** (46/74) `[50.77%, 72.35%]` | **-21.71 pp** (-25.9%) | `Z=2.186` (`p=2.88e-02`) | **64.44%** | `64` / `85` | `NEEDS_BROADENING (<80%)` |
| `Ring_1_Jev_Pooled_Agent_PRs (N=348)` | **`SM-05_AdvisoryOverride_Merge`** | Pooled Coding-Agent PR Merge Rate Under Advisory Jev: Jev Clean vs Jev Flagged | `2_Jev_Clean_AgentPRs`: **85.55%** (148/173) `[79.54%, 90.02%]` | `1_Jev_Flagged_AgentPRs`: **89.14%** (156/175) `[83.67%, 92.94%]` | **+3.59 pp** (+4.2%) | `Z=-1.009` (`p=3.13e-01`) | **17.27%** | `1338` / `1791` | `NEEDS_BROADENING (<80%)` |
| `Ring_1_Jev_Pooled_Agent_PRs (N=348)` | **`SM-05_JevSilence`** | Pooled Coding-Agent PRs Zero-Human-Comment Fast-Track Rate: Jev Flagged vs Jev Clean | `1_Jev_Flagged_AgentPRs`: **84.57%** (148/175) `[78.48%, 89.17%]` | `2_Jev_Clean_AgentPRs`: **78.61%** (136/173) `[71.92%, 84.07%]` | **-5.96 pp** (-7.0%) | `Z=1.435` (`p=1.51e-01`) | **30.13%** | `661` / `884` | `NEEDS_BROADENING (<80%)` |
| `Ring_1_Jev_SZZ_14d_Agent_PRs (N=125)` | **`RV-05_JevAgentSZZ14d`** | Pooled Jev Coding-Agent PRs 14-Day SZZ Bugfix Rate: Jev Flagged vs Jev Clean | `1_Jev_Flagged_AgentPRs`: **40.43%** (19/47) `[27.64%, 54.66%]` | `2_Jev_Clean_AgentPRs`: **62.82%** (49/78) `[51.73%, 72.71%]` | **+22.39 pp** (+55.4%) | `Z=-2.435` (`p=1.49e-02`) | **68.72%** | `77` / `103` | `NEEDS_BROADENING (<80%)` |
| `Ring_1_Jev_SZZ_14d_Human_PRs (N=65)` | **`RV-05_JevHumanSZZ14d`** | Pooled Jev Human-Engineer PRs 14-Day SZZ Bugfix Rate: Jev Flagged vs Jev Clean | `1_Jev_Flagged_HumanPRs`: **74.55%** (41/55) `[61.7%, 84.19%]` | `2_Jev_Clean_HumanPRs`: **80.0%** (8/10) `[49.02%, 94.33%]` | **+5.45 pp** (+7.3%) | `Z=-0.368` (`p=7.13e-01`) | **6.66%** | `924` / `1237` | `NEEDS_BROADENING (<80%)` |

---

## 3. Post-Expansion Statistical Power Summary

- **Fully/Adequately Powered Hypotheses (`>= 80%` Power):** **15 / 25** tests.
- **Remaining Exploratory / Underpowered Cells (`< 80%` Power):** **10 / 25** tests.
  - `SM-04_RubberStamp` (`Ring_3A_Curated_Human_Reviewed (N=2,138)`): `60.28%` vs `67.58%` (`p = 5.34e-02`, power = **50.23%**, needs `677`/arm for 80%).
  - `RV-01_SZZ_30d_HO_vs_Bot` (`Ring_4S_BareGit_SZZ_GroundTruth (N=1,680)`): `38.39%` vs `41.2%` (`p = 2.81e-01`, power = **18.96%**, needs `4762`/arm for 80%).
  - `RV-01_SZZ_Revert30d_HO_vs_Bot` (`Ring_4S_BareGit_SZZ_GroundTruth (N=1,680)`): `0.76%` vs `0.6%` (`p = 7.17e-01`, power = **6.59%**, needs `39982`/arm for 80%).
  - `RV-06_SZZ_30d_SAST_vs_ProseBot` (`Ring_4S_BareGit_SZZ_GroundTruth (N=523)`): `65.22%` vs `41.2%` (`p = 2.26e-02`, power = **62.55%**, needs `67`/arm for 80%).
  - `RV-06_SZZ_30d_ConstraintTier` (`Ring_4S_BareGit_SZZ_Constraints (N=4,038)`): `42.61%` vs `42.38%` (`p = 8.80e-01`, power = **5.26%**, needs `156978`/arm for 80%).
  - `RV-05_SentryGate` (`Ring_1_Jev_Sentry_Human_PRs (N=105)`): `83.87%` vs `62.16%` (`p = 2.88e-02`, power = **64.44%**, needs `64`/arm for 80%).
  - `SM-05_AdvisoryOverride_Merge` (`Ring_1_Jev_Pooled_Agent_PRs (N=348)`): `85.55%` vs `89.14%` (`p = 3.13e-01`, power = **17.27%**, needs `1338`/arm for 80%).
  - `SM-05_JevSilence` (`Ring_1_Jev_Pooled_Agent_PRs (N=348)`): `84.57%` vs `78.61%` (`p = 1.51e-01`, power = **30.13%**, needs `661`/arm for 80%).
  - `RV-05_JevAgentSZZ14d` (`Ring_1_Jev_SZZ_14d_Agent_PRs (N=125)`): `40.43%` vs `62.82%` (`p = 1.49e-02`, power = **68.72%**, needs `77`/arm for 80%).
  - `RV-05_JevHumanSZZ14d` (`Ring_1_Jev_SZZ_14d_Human_PRs (N=65)`): `74.55%` vs `80.0%` (`p = 7.13e-01`, power = **6.66%**, needs `924`/arm for 80%).
