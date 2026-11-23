#!/usr/bin/env python3
"""
Pipeline p14: Multi-Scale Sample Size Broadening, Persistence & Statistical Power Audit
=====================================================================================
Audits how every core PR-review & social-media observation holds across 6 concentric sample-size
rings (Ring 1 Jev Adopter Corpus -> Ring 6 Global AIDev Population), computing exact 95%
Wilson CIs, two-proportion Z-tests, Cohen's h, achieved power, and N_req for 80%/90% power.

Includes dynamic Ring 4A (brain_family), dynamic Ring 4B/5, and Jev 14d & 30d SZZ power rows.

Outputs:
  - results/sample_size_and_power_audit_results.json
  - results/data_tables/multi_scale_sample_persistence_log.csv
  - results/SAMPLE_SIZE_EXPANSION_AND_POWER_REPORT.md (with mandatory YAML frontmatter)
"""

from __future__ import annotations

from collections import defaultdict
import csv
import datetime
import json
from pathlib import Path
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.paths import PathConfig, get_paths
from src.utils.logging_utils import setup_verbose_logger
from src.utils.stats_utils import two_prop_z_test, yaml_frontmatter


def load_json(paths: PathConfig, fname: str) -> dict[str, Any]:
    fp = paths.results_dir / fname
    if not fp.exists():
        return {}
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(paths: PathConfig, fname: str) -> list[dict[str, str]]:
    fp = paths.tables_dir / fname
    if not fp.exists():
        return []
    with open(fp, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p14_sample_power_audit",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    log.info("Starting Multi-Scale Sample Size & Statistical Power Audit (log=%s)", ts_log)

    rev_prs = load_csv(paths, "analyzed_human_reviewed_prs_log.csv")
    warns = load_csv(paths, "raw_patch_unaddressed_warnings_log.csv")
    cr_policy = load_csv(paths, "coderabbit_policy_outcomes_log.csv")
    szz_csv = load_csv(paths, "szz_defect_traceability_ledger.csv")

    msr_json = load_json(paths, "msr_aidev_results.json")
    patch_json = load_json(paths, "raw_patch_and_sociotechnical_results.json")
    jev_json = load_json(paths, "jev_vs_prose_tollgate_results.json")
    szz_json = load_json(paths, "szz_and_constraints_summary.json")

    def _i(v: Any) -> int:
        try:
            return int(float(v))
        except Exception:
            return 0

    # Cross-verify any non-Copilot inline review bots beyond the 38-bot catalog
    extra_bots_by_pr: dict[str, set[str]] = defaultdict(set)
    for w in warns:
        if w.get("reviewer_type") == "Bot" and w.get("reviewer") not in ("github-actions[bot]", "Copilot"):
            extra_bots_by_pr[str(w.get("pr_id"))].add(str(w.get("reviewer")))

    reclassified_count = 0
    for r in rev_prs:
        pid = str(r.get("pr_id"))
        existing = {x.strip() for x in str(r.get("tier1_bots_list", "")).split(";") if x.strip()}
        extra = extra_bots_by_pr.get(pid, set())
        merged_bots = sorted(existing | extra)
        if merged_bots and r.get("cohort") == "Cohort_B_Human_Only":
            reclassified_count += 1
        r["expanded_bots"] = merged_bots  # type: ignore[assignment]
        r["expanded_cohort"] = "Cohort_C_Expanded" if merged_bots else "Cohort_B_Clean_Human_Only"

    comparisons: list[dict[str, Any]] = []

    def add_comp(scale_ring: str, vector_id: str, hypothesis_label: str, arm1_label: str, k1: int, n1: int, arm2_label: str, k2: int, n2: int) -> None:
        res = two_prop_z_test(k1, n1, k2, n2)
        comparisons.append({
            "scale_ring": scale_ring,
            "vector_id": vector_id,
            "hypothesis_label": hypothesis_label,
            "arm1_label": arm1_label,
            "arm2_label": arm2_label,
            "total_n": n1 + n2,
            **res,
        })

    # Ring 2: Within-Shared-Repo Paired Human-Reviewed PRs
    repos_b = {r["repo_full_name"] for r in rev_prs if r["cohort"] == "Cohort_B_Human_Only"}
    repos_c = {r["repo_full_name"] for r in rev_prs if r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human"}
    shared_bc = repos_b & repos_c
    b_shared = [r for r in rev_prs if r["cohort"] == "Cohort_B_Human_Only" and r["repo_full_name"] in shared_bc]
    c_shared = [r for r in rev_prs if r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human" and r["repo_full_name"] in shared_bc]
    add_comp(
        f"Ring_2_Within_{len(shared_bc)}_Shared_Repos (N={len(b_shared)+len(c_shared):,})",
        "RV-02",
        "Within-Repo Human Veto Suppression (Human-Only vs Bot+Human)",
        f"Cohort_B_Shared{len(shared_bc)}", sum(1 for r in b_shared if _i(r["human_changes_req"]) > 0), len(b_shared),
        f"Cohort_C_Shared{len(shared_bc)}", sum(1 for r in c_shared if _i(r["human_changes_req"]) > 0), len(c_shared),
    )

    # Ring 3A: Full Curated Human-Reviewed Benchmark with Clean Unified 38-Bot Catalog
    b_all = [r for r in rev_prs if r["cohort"] == "Cohort_B_Human_Only"]
    c_all = [r for r in rev_prs if r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human"]
    add_comp(
        f"Ring_3A_Curated_Human_Reviewed_38Bot (N={len(rev_prs):,})",
        "RV-02",
        "Global Curated Human Veto Suppression (Clean 38-Bot Catalog: Human-Only vs Bot+Human)",
        "Cohort_B_Clean38", sum(1 for r in b_all if _i(r["human_changes_req"]) > 0), len(b_all),
        "Cohort_C_Clean38", sum(1 for r in c_all if _i(r["human_changes_req"]) > 0), len(c_all),
    )

    # Ring 3B: Cross-Table Inline Bot Sensitivity Check
    b_clean = [r for r in rev_prs if r["expanded_cohort"] == "Cohort_B_Clean_Human_Only"]
    c_exp = [r for r in rev_prs if r["expanded_cohort"] == "Cohort_C_Expanded"]
    if reclassified_count > 0:
        add_comp(
            f"Ring_3B_CrossTable_InlineBot_Check (N={len(rev_prs):,})",
            "RV-02_Expanded",
            f"Human Veto Suppression After Cross-Table Inline-Bot Check (+{reclassified_count} PRs)",
            "Cohort_B_Clean", sum(1 for r in b_clean if _i(r["human_changes_req"]) > 0), len(b_clean),
            "Cohort_C_Expanded", sum(1 for r in c_exp if _i(r["human_changes_req"]) > 0), len(c_exp),
        )

    # SM-02: Second-Reviewer Displacement
    h2_b0 = [r for r in rev_prs if _i(r["human_review_count"]) >= 2 and len([x for x in r["tier1_bots_list"].split(";") if x.strip()]) == 0]
    h1_b1 = [r for r in rev_prs if _i(r["human_review_count"]) == 1 and len([x for x in r["tier1_bots_list"].split(";") if x.strip()]) == 1]
    add_comp(
        f"Ring_3A_Curated_Human_Reviewed (N={len(h2_b0)+len(h1_b1):,})",
        "SM-02",
        "Second-Reviewer Displacement: 2+ Humans (0 Bots) vs 1 Human + 1 AI Bot Veto Rate",
        "2plus_Humans_0_Bots", sum(1 for r in h2_b0 if _i(r["human_changes_req"]) > 0), len(h2_b0),
        "1_Human_1_Bot", sum(1 for r in h1_b1 if _i(r["human_changes_req"]) > 0), len(h1_b1),
    )

    # SM-04: Stacked AI Reviewers Bystander Collapse
    h1_b0 = [r for r in rev_prs if _i(r["human_review_count"]) == 1 and len([x for x in r["tier1_bots_list"].split(";") if x.strip()]) == 0]
    h1_b2 = [r for r in rev_prs if _i(r["human_review_count"]) == 1 and len([x for x in r["tier1_bots_list"].split(";") if x.strip()]) >= 2]
    add_comp(
        f"Ring_3A_Curated_Human_Reviewed (N={len(h1_b0)+len(h1_b2):,})",
        "SM-04",
        "Stacked-Bot Bystander Collapse: 1 Human (0 Bots) vs 1 Human + 2+ Bots Veto Rate",
        "1_Human_0_Bots", sum(1 for r in h1_b0 if _i(r["human_changes_req"]) > 0), len(h1_b0),
        "1_Human_2plus_Bots", sum(1 for r in h1_b2 if _i(r["human_changes_req"]) > 0), len(h1_b2),
    )
    add_comp(
        f"Ring_3A_Curated_Human_Reviewed (N={len(h1_b0)+len(h1_b2):,})",
        "SM-04_RubberStamp",
        "Stacked-Bot Rubber-Stamp Surge: 1 Human (0 Bots) vs 1 Human + 2+ Bots Rubber-Stamp Rate",
        "1_Human_0_Bots", sum(1 for r in h1_b0 if _i(r["rubber_stamp_approval"]) == 1), len(h1_b0),
        "1_Human_2plus_Bots", sum(1 for r in h1_b2 if _i(r["rubber_stamp_approval"]) == 1), len(h1_b2),
    )

    # SM-07: Intent-Oracle Paradox
    ibd0 = [r for r in rev_prs if _i(r["intent_rationale_deficit_ibd"]) == 0]
    ibd1 = [r for r in rev_prs if _i(r["intent_rationale_deficit_ibd"]) == 1]
    add_comp(
        f"Ring_3A_Curated_Human_Reviewed (N={len(rev_prs):,})",
        "SM-07",
        "Intent-Oracle Paradox: Issue-Anchored (IBD=0) vs Unanchored Prompt PRs (IBD=1) Veto Rate",
        "Issue_Anchored_IBD0", sum(1 for r in ibd0 if _i(r["human_changes_req"]) > 0), len(ibd0),
        "Intent_Deficit_IBD1", sum(1 for r in ibd1 if _i(r["human_changes_req"]) > 0), len(ibd1),
    )

    # Ring 4A: Dynamic Deterministic SAST Brain vs MultiModel RAG Prose Brain
    brains = {b.get("brain_family"): b for b in patch_json.get("review_bot_brain_family_impact", [])}
    b_sast = brains.get("1_Deterministic_SAST_Brain", {})
    b_rag = brains.get("2_MultiModel_RAG_Agentic_Brain", {})
    n_sast = _i(b_sast.get("merged_prs", 0))
    n_rag = _i(b_rag.get("merged_prs", 0))
    if n_sast > 0 and n_rag > 0:
        k_sast_14 = int(round(float(b_sast.get("post_merge_reg_14d_pct", 0.0) or 0.0) * n_sast / 100.0))
        k_rag_14 = int(round(float(b_rag.get("post_merge_reg_14d_pct", 0.0) or 0.0) * n_rag / 100.0))
        k_sast_90 = int(round(float(b_sast.get("post_merge_reg_90d_pct", 0.0) or 0.0) * n_sast / 100.0))
        k_rag_90 = int(round(float(b_rag.get("post_merge_reg_90d_pct", 0.0) or 0.0) * n_rag / 100.0))
        add_comp(
            f"Ring_4A_Bot_Brain_Families (N={n_sast+n_rag:,})",
            "RV-06_14d",
            "14-Day Merged-PR Post-Merge Regression Rate: Deterministic SAST Gate vs MultiModel RAG Prose Bot",
            "1_Deterministic_SAST_Brain", k_sast_14, n_sast,
            "2_MultiModel_RAG_Agentic_Brain", k_rag_14, n_rag,
        )
        add_comp(
            f"Ring_4A_Bot_Brain_Families (N={n_sast+n_rag:,})",
            "RV-06_90d",
            "90-Day Merged-PR Post-Merge Regression Rate: Deterministic SAST Gate vs MultiModel RAG Prose Bot",
            "1_Deterministic_SAST_Brain", k_sast_90, n_sast,
            "2_MultiModel_RAG_Agentic_Brain", k_rag_90, n_rag,
        )

    # Ring 4B: Dynamic Within-Shared-Repo Matched Control
    within_shared = patch_json.get("normalized_post_merge_hazard_analysis", {}).get("within_shared_repo_matched_control", [])
    ws_rev = next((x for x in within_shared if x.get("cohort") == "Reviewed_In_Shared_Repos"), {})
    ws_sil = next((x for x in within_shared if x.get("cohort") == "Silent_In_Shared_Repos"), {})
    ws_n_rev = _i(ws_rev.get("merged_prs", 0))
    ws_n_sil = _i(ws_sil.get("merged_prs", 0))
    ws_repos = _i(ws_rev.get("shared_repos", 0))
    if ws_n_rev > 0 and ws_n_sil > 0:
        k_rev_fix14 = int(round(float(ws_rev.get("fix_14d_pct", 0.0)) * ws_n_rev / 100.0))
        k_sil_fix14 = int(round(float(ws_sil.get("fix_14d_pct", 0.0)) * ws_n_sil / 100.0))
        add_comp(
            f"Ring_4B_Within_{ws_repos}_Shared_Repos (N={ws_n_rev+ws_n_sil:,})",
            "RV-01_Fix14d_Within281",
            f"Within-{ws_repos}-Shared-Repo 14-Day Downstream Fix-PR Exposure: Reviewed vs Silent Gate",
            "Reviewed_In_Shared_Repos", k_rev_fix14, ws_n_rev,
            "Silent_In_Shared_Repos", k_sil_fix14, ws_n_sil,
        )

    # Ring 4C: Paired Shared-Repo Human vs Agent Merge Acceptance
    paired_ctrl = msr_json.get("paired_control_summary", {})
    hu_tot_810 = _i(paired_ctrl.get("human_prs_total", 0))
    hu_mrg_810 = _i(paired_ctrl.get("human_prs_merged", 0))
    ag_tot_810 = _i(paired_ctrl.get("agent_prs_total", 0))
    ag_mrg_810 = _i(paired_ctrl.get("agent_prs_merged", 0))
    if hu_tot_810 > 0 and ag_tot_810 > 0:
        add_comp(
            f"Ring_4C_Paired_{paired_ctrl.get('shared_repos_count', 0)}_Repos (N={hu_tot_810+ag_tot_810:,})",
            "RV-01_PairedAcceptance",
            f"Within-{paired_ctrl.get('shared_repos_count', 0)}-Shared-Repo Merge Acceptance: Human Baseline PRs vs Coding-Agent PRs",
            "Human_Baseline_Paired", hu_mrg_810, hu_tot_810,
            "Coding_Agent_Paired", ag_mrg_810, ag_tot_810,
        )

    # Ring 4S: Commit-Attributed Bare-Git SZZ Ground-Truth Power Tests (14d & 30d)
    szz_u14 = [r for r in szz_csv if _i(r.get("uncensored_14d")) == 1]
    szz_u30 = [r for r in szz_csv if _i(r.get("uncensored_30d")) == 1]
    if szz_u30:
        szz_aidev = [r for r in szz_u30 if r.get("corpus") == "AIDev"]
        szz_hu_base = [r for r in szz_u30 if r.get("corpus") == "AIDev_HumanBaseline"]
        szz_ho = [r for r in szz_aidev if r.get("review_topology") == "Agent+HumanOnly"]
        szz_pb = [r for r in szz_aidev if r.get("review_topology") == "Agent+ProseBot+Human"]
        szz_sast = [r for r in szz_aidev if r.get("review_topology") == "Agent+DeterministicSAST"]
        szz_sil = [r for r in szz_aidev if r.get("review_topology") == "Agent+SilentOrSelfMerge"]
        if szz_ho and szz_sil:
            add_comp(
                f"Ring_4S_BareGit_SZZ_GroundTruth (N={len(szz_ho)+len(szz_sil):,})",
                "RV-01_SZZ_14d_Reviewed_vs_Silent",
                "Commit-Attributed 14d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+SilentOrSelfMerge",
                "SZZ_Agent+HumanOnly", sum(_i(r["szz_bugfix_14d"]) for r in szz_ho), len(szz_ho),
                "SZZ_Agent+SilentOrSelfMerge", sum(_i(r["szz_bugfix_14d"]) for r in szz_sil), len(szz_sil),
            )
            add_comp(
                f"Ring_4S_BareGit_SZZ_GroundTruth (N={len(szz_ho)+len(szz_sil):,})",
                "RV-01_SZZ_30d_Reviewed_vs_Silent",
                "Commit-Attributed 30d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+SilentOrSelfMerge",
                "SZZ_Agent+HumanOnly", sum(_i(r["szz_bugfix_30d"]) for r in szz_ho), len(szz_ho),
                "SZZ_Agent+SilentOrSelfMerge", sum(_i(r["szz_bugfix_30d"]) for r in szz_sil), len(szz_sil),
            )
        if szz_ho and szz_pb:
            add_comp(
                f"Ring_4S_BareGit_SZZ_GroundTruth (N={len(szz_ho)+len(szz_pb):,})",
                "RV-01_SZZ_30d_HO_vs_Bot",
                "Commit-Attributed 30d SZZ Bugfix Rate: Agent+HumanOnly vs Agent+ProseBot+Human",
                "SZZ_Agent+HumanOnly", sum(_i(r["szz_bugfix_30d"]) for r in szz_ho), len(szz_ho),
                "SZZ_Agent+ProseBot+Human", sum(_i(r["szz_bugfix_30d"]) for r in szz_pb), len(szz_pb),
            )
            add_comp(
                f"Ring_4S_BareGit_SZZ_GroundTruth (N={len(szz_ho)+len(szz_pb):,})",
                "RV-01_SZZ_Revert30d_HO_vs_Bot",
                "Commit-Attributed 30d Hard Revert Rate: Agent+HumanOnly vs Agent+ProseBot+Human",
                "SZZ_Agent+HumanOnly", sum(_i(r["reverted_30d"]) for r in szz_ho), len(szz_ho),
                "SZZ_Agent+ProseBot+Human", sum(_i(r["reverted_30d"]) for r in szz_pb), len(szz_pb),
            )
        if szz_sast and szz_pb:
            add_comp(
                f"Ring_4S_BareGit_SZZ_GroundTruth (N={len(szz_sast)+len(szz_pb):,})",
                "RV-06_SZZ_30d_SAST_vs_ProseBot",
                "Commit-Attributed 30d SZZ Bugfix Rate: Agent+DeterministicSAST vs Agent+ProseBot+Human",
                "SZZ_Agent+DeterministicSAST", sum(_i(r["szz_bugfix_30d"]) for r in szz_sast), len(szz_sast),
                "SZZ_Agent+ProseBot+Human", sum(_i(r["szz_bugfix_30d"]) for r in szz_pb), len(szz_pb),
            )
        if szz_hu_base and szz_aidev:
            shared_szz_repos = {r["repo_full_name"] for r in szz_hu_base} & {r["repo_full_name"] for r in szz_aidev}
            hu_sh = [r for r in szz_hu_base if r["repo_full_name"] in shared_szz_repos]
            ag_sh = [r for r in szz_aidev if r["repo_full_name"] in shared_szz_repos]
            if hu_sh and ag_sh:
                add_comp(
                    f"Ring_4S_Paired_{len(shared_szz_repos)}_Repos_SZZ (N={len(hu_sh)+len(ag_sh):,})",
                    "RV-01_SZZ_30d_Human_vs_Agent",
                    "Within-Repo Commit-Attributed 30d SZZ Bugfix Rate: Human Baseline vs Coding-Agent PRs",
                    "SZZ_Human_Baseline", sum(_i(r["szz_bugfix_30d"]) for r in hu_sh), len(hu_sh),
                    "SZZ_Coding_Agent", sum(_i(r["szz_bugfix_30d"]) for r in ag_sh), len(ag_sh),
                )
        t_low = [r for r in szz_aidev if _i(r.get("constraint_tier")) <= 1]
        t_high = [r for r in szz_aidev if _i(r.get("constraint_tier")) >= 2]
        if t_low and t_high:
            add_comp(
                f"Ring_4S_BareGit_SZZ_Constraints (N={len(t_low)+len(t_high):,})",
                "RV-06_SZZ_30d_ConstraintTier",
                "Commit-Attributed 30d SZZ Bugfix Rate: Low Architectural Constraints (Tier 0-1) vs High (Tier 2-3)",
                "Constraint_Tier_0_1", sum(_i(r["szz_bugfix_30d"]) for r in t_low), len(t_low),
                "Constraint_Tier_2_3", sum(_i(r["szz_bugfix_30d"]) for r in t_high), len(t_high),
            )
        szz_jev_hu_30 = [r for r in szz_u30 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Human_Engineer__No_Bot_Control"]
        szz_jev_ag_30 = [r for r in szz_u30 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__No_Bot_Control"]
        if szz_jev_hu_30 and szz_jev_ag_30:
            add_comp(
                f"Ring_4S_JevAdopters_SZZ (N={len(szz_jev_hu_30)+len(szz_jev_ag_30):,})",
                "RV-01_SZZ_30d_JevRepos_Human_vs_Agent",
                "Jev Adopter Repos Commit-Attributed 30d SZZ Bugfix Rate: Human Engineer vs Coding Agent (No-Bot Control)",
                "JevRepos_Human_NoBot", sum(_i(r["szz_bugfix_30d"]) for r in szz_jev_hu_30), len(szz_jev_hu_30),
                "JevRepos_Agent_NoBot", sum(_i(r["szz_bugfix_30d"]) for r in szz_jev_ag_30), len(szz_jev_ag_30),
            )

    if szz_u14:
        szz_jev_hu_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Human_Engineer__No_Bot_Control"]
        szz_jev_ag_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__No_Bot_Control"]
        if szz_jev_hu_14 and szz_jev_ag_14:
            add_comp(
                f"Ring_4S_JevAdopters_SZZ_14d (N={len(szz_jev_hu_14)+len(szz_jev_ag_14):,})",
                "RV-01_SZZ_14d_JevRepos_Human_vs_Agent",
                "Jev Adopter Repos Commit-Attributed 14d SZZ Bugfix Rate: Human Engineer vs Coding Agent (No-Bot Control)",
                "JevRepos_Human_NoBot_14d", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_hu_14), len(szz_jev_hu_14),
                "JevRepos_Agent_NoBot_14d", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_ag_14), len(szz_jev_ag_14),
            )

    # Ring 5: Full Curated Benchmark Mode I vs Mode II
    exec_strat = msr_json.get("execution_mode_and_task_stratification", {})
    em_rows = exec_strat.get("execution_modes", [])
    m2_n_tot = sum(_i(e.get("n_prs")) for e in em_rows if e.get("execution_mode") == "Peer-Merged (Mode II)")
    m2_k_sil = sum(int(round(float(e.get("silent_gate_pct", 0.0)) * _i(e.get("n_prs")) / 100.0)) for e in em_rows if e.get("execution_mode") == "Peer-Merged (Mode II)")
    m1_n_tot = sum(_i(e.get("n_prs")) for e in em_rows if e.get("execution_mode") == "Self-Merged (Mode I)")
    m1_k_sil = sum(int(round(float(e.get("silent_gate_pct", 0.0)) * _i(e.get("n_prs")) / 100.0)) for e in em_rows if e.get("execution_mode") == "Self-Merged (Mode I)")
    if m2_n_tot > 0 and m1_n_tot > 0:
        add_comp(
            f"Ring_5_Full_Curated_Benchmark (N={m1_n_tot+m2_n_tot:,} Matched Merged)",
            "RV-07_ModeI_vs_ModeII",
            "Silent Zero-Human-Review Gate Rate: Peer-Merged (Mode II) vs Operator Self-Merged (Mode I)",
            "Mode_II_Peer_Merged", m2_k_sil, m2_n_tot,
            "Mode_I_Operator_Self_Merged", m1_k_sil, m1_n_tot,
        )

    # Ring 1: TypeSafe Jev Decision-Model Adopter Corpus (including Jev 14d & 30d SZZ power rows)
    jev_scale = jev_json.get("mined_corpus_scale", {})
    jev_eval = jev_json.get("axis1_and_axis2_2x2_evaluation", {})
    sentry_sens = jev_eval.get("sentry_dml_agent_vs_human_sensitivity", {})
    hu_sent = sentry_sens.get("Human_Engineer", {})
    all_jev_2x2 = jev_eval.get("all_jev_active_repos_2x2", [])

    def _find_jev(origin: str, regime: str) -> dict[str, Any]:
        for x in all_jev_2x2:
            if x.get("author_origin") == origin and x.get("gate_regime") == regime:
                return x
        return {}

    ag_flag = _find_jev("Coding_Agent", "1_Jev_Flagged")
    ag_clean = _find_jev("Coding_Agent", "2_Jev_Clean")

    s_cl_n = _i(hu_sent.get("clean_n", 0))
    s_fl_n = _i(hu_sent.get("flagged_n", 0))
    if s_cl_n > 0 and s_fl_n > 0:
        s_cl_m = int(round(float(hu_sent.get("clean_merge_rate_pct", 0.0)) * s_cl_n / 100.0))
        s_fl_m = int(round(float(hu_sent.get("flagged_merge_rate_pct", 0.0)) * s_fl_n / 100.0))
        add_comp(
            f"Ring_1_Jev_Sentry_Human_PRs (N={s_cl_n+s_fl_n})",
            "RV-05_SentryGate",
            "getsentry/sentry Human PR Merge Rate: Jev Clean vs Jev Flagged",
            "Jev_Clean_Sentry", s_cl_m, s_cl_n,
            "Jev_Flagged_Sentry", s_fl_m, s_fl_n,
        )

    af_n = _i(ag_flag.get("prs_total", 0))
    ac_n = _i(ag_clean.get("prs_total", 0))
    af_m = _i(ag_flag.get("merged_prs", 0))
    ac_m = _i(ag_clean.get("merged_prs", 0))
    if af_n > 0 and ac_n > 0:
        add_comp(
            f"Ring_1_Jev_Pooled_Agent_PRs (N={af_n+ac_n})",
            "SM-05_AdvisoryOverride_Merge",
            "Pooled Coding-Agent PR Merge Rate Under Advisory Jev: Jev Clean vs Jev Flagged",
            "2_Jev_Clean_AgentPRs", ac_m, ac_n,
            "1_Jev_Flagged_AgentPRs", af_m, af_n,
        )
        af_zero_comm = int(round((100.0 - float(ag_flag.get("pct_with_human_comm", 0.0))) * af_n / 100.0))
        ac_zero_comm = int(round((100.0 - float(ag_clean.get("pct_with_human_comm", 0.0))) * ac_n / 100.0))
        add_comp(
            f"Ring_1_Jev_Pooled_Agent_PRs (N={af_n+ac_n})",
            "SM-05_JevSilence",
            "Pooled Coding-Agent PRs Zero-Human-Comment Fast-Track Rate: Jev Flagged vs Jev Clean",
            "1_Jev_Flagged_AgentPRs", af_zero_comm, af_n,
            "2_Jev_Clean_AgentPRs", ac_zero_comm, ac_n,
        )

    # Jev 14d SZZ Power Rows (Agent & Human Flagged vs Clean)
    if szz_u14:
        szz_jev_ag_fl_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__Jev_Flagged"]
        szz_jev_ag_cl_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__Jev_Clean"]
        if szz_jev_ag_fl_14 and szz_jev_ag_cl_14:
            add_comp(
                f"Ring_1_Jev_SZZ_14d_Agent_PRs (N={len(szz_jev_ag_fl_14)+len(szz_jev_ag_cl_14)})",
                "RV-05_JevAgentSZZ14d",
                "Pooled Jev Coding-Agent PRs 14-Day SZZ Bugfix Rate: Jev Flagged vs Jev Clean",
                "1_Jev_Flagged_AgentPRs", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_ag_fl_14), len(szz_jev_ag_fl_14),
                "2_Jev_Clean_AgentPRs", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_ag_cl_14), len(szz_jev_ag_cl_14),
            )
        szz_jev_hu_fl_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Human_Engineer__Jev_Flagged"]
        szz_jev_hu_cl_14 = [r for r in szz_u14 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Human_Engineer__Jev_Clean"]
        if szz_jev_hu_fl_14 and szz_jev_hu_cl_14:
            add_comp(
                f"Ring_1_Jev_SZZ_14d_Human_PRs (N={len(szz_jev_hu_fl_14)+len(szz_jev_hu_cl_14)})",
                "RV-05_JevHumanSZZ14d",
                "Pooled Jev Human-Engineer PRs 14-Day SZZ Bugfix Rate: Jev Flagged vs Jev Clean",
                "1_Jev_Flagged_HumanPRs", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_hu_fl_14), len(szz_jev_hu_fl_14),
                "2_Jev_Clean_HumanPRs", sum(_i(r["szz_bugfix_14d"]) for r in szz_jev_hu_cl_14), len(szz_jev_hu_cl_14),
            )

    # Jev 30d SZZ Power Row (when uncensored 30d rows accumulate)
    szz_jev_ag_fl_30 = [r for r in szz_u30 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__Jev_Flagged"]
    szz_jev_ag_cl_30 = [r for r in szz_u30 if r.get("corpus") == "Jev_Mined" and r.get("review_topology") == "Coding_Agent__Jev_Clean"]
    if szz_jev_ag_fl_30 and szz_jev_ag_cl_30:
        add_comp(
            f"Ring_1_Jev_SZZ_30d_Agent_PRs (N={len(szz_jev_ag_fl_30)+len(szz_jev_ag_cl_30)})",
            "RV-05_JevAgentSZZ30d",
            "Pooled Jev Coding-Agent PRs 30-Day SZZ Bugfix Rate: Jev Flagged vs Jev Clean",
            "1_Jev_Flagged_AgentPRs", sum(_i(r["szz_bugfix_30d"]) for r in szz_jev_ag_fl_30), len(szz_jev_ag_fl_30),
            "2_Jev_Clean_AgentPRs", sum(_i(r["szz_bugfix_30d"]) for r in szz_jev_ag_cl_30), len(szz_jev_ag_cl_30),
        )

    out_json = paths.results_dir / "sample_size_and_power_audit_results.json"
    out_csv = paths.tables_dir / "multi_scale_sample_persistence_log.csv"
    out_md = paths.results_dir / "SAMPLE_SIZE_EXPANSION_AND_POWER_REPORT.md"

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "scale_ring", "vector_id", "hypothesis_label", "arm1_label", "arm2_label",
            "total_n", "n1", "k1", "p1_pct", "ci1_95_pct", "n2", "k2", "p2_pct", "ci2_95_pct",
            "diff_pp", "relative_shift_pct", "z_stat", "p_value", "cohens_h",
            "achieved_power_pct", "n_per_arm_for_80pct_power", "n_per_arm_for_90pct_power", "power_status",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for c in comparisons:
            row_out = dict(c)
            row_out["ci1_95_pct"] = f"[{c['ci1_95_pct'][0]}%, {c['ci1_95_pct'][1]}%]"
            row_out["ci2_95_pct"] = f"[{c['ci2_95_pct'][0]}%, {c['ci2_95_pct'][1]}%]"
            row_out["p_value"] = f"{c['p_value']:.3e}"
            w.writerow(row_out)

    cr_pol_n = sum(_i(r.get("prs")) for r in cr_policy)
    cr_pol_repos = sum(_i(r.get("repos")) for r in cr_policy)
    aid_macro = msr_json.get("macro_corpus_summary", {})
    aid_cur_ag_n = _i(aid_macro.get("agentic_prs_total", 0))
    aid_cur_hu_n = _i(aid_macro.get("human_baseline_prs_total", 0))
    curated_aidev_n = aid_cur_ag_n + aid_cur_hu_n

    all_repo_pq = paths.scratch_dir / "aidev" / "aidev_all_repo.parquet"
    local_all_repos_n = 0
    if all_repo_pq.exists():
        import duckdb
        con = duckdb.connect()
        try:
            local_all_repos_n = int(con.execute(f"SELECT COUNT(*) FROM read_parquet('{all_repo_pq}')").fetchone()[0])
        finally:
            con.close()

    summary_json = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reclassified_inline_bot_prs_from_cohort_b_to_c": reclassified_count,
        "concentric_scale_rings": {
            "Ring_1_Jev_Adopter_Corpus": {
                "current_n": _i(jev_scale.get("prs_total", 0)),
                "jev_signal_distinct_prs": _i(jev_scale.get("jev_signal_distinct_prs", 0)),
                "sentry_human_dml_n": s_cl_n + s_fl_n,
                "agent_jev_prs_n": af_n + ac_n,
                "formal_reviews_n": _i(jev_scale.get("formal_reviews_total", 0)),
            },
            "Ring_2_Within_Shared_Repos": {"shared_repos": len(shared_bc), "current_n": len(b_shared) + len(c_shared)},
            "Ring_3_Curated_Human_Reviewed_38Bot": {
                "current_n": len(rev_prs),
                "cohort_b_clean38": len(b_all),
                "cohort_c_clean38": len(c_all),
                "cross_table_extra_reclassified": reclassified_count,
            },
            "Ring_4_Within_281_and_810_Shared_Repos": {
                "within_281_merged_n": ws_n_rev + ws_n_sil,
                "paired_810_n": hu_tot_810 + ag_tot_810,
                "szz_linked_merged_prs": len(szz_csv),
                "szz_uncensored_14d_prs": len(szz_u14),
                "szz_uncensored_30d_prs": len(szz_u30),
                "szz_cloned_repos": _i(szz_json.get("cloned_repos_scanned", 0)),
            },
            "Ring_5_Full_Curated_and_CodeRabbit_Policy": {"curated_aidev_n": curated_aidev_n, "coderabbit_policy_n": cr_pol_n, "coderabbit_policy_repos": cr_pol_repos},
            "Ring_6_Global_AIDev_Firehose": {
                "published_aidev_msr2026_reference_prs": 932791,
                "local_aidev_all_repo_verified_count": local_all_repos_n,
                "note": "Published MSR 2026 census reference (local aidev_all_repo.parquet verified count computed dynamically)",
            },
        },
        "power_and_persistence_comparisons": comparisons,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2)

    r1_total_n = summary_json["concentric_scale_rings"]["Ring_1_Jev_Adopter_Corpus"]["current_n"]
    frontmatter = yaml_frontmatter(
        title="Multi-Scale Sample Size Persistence & Statistical Power Audit Report",
        intent="Audits how core PR-review, bare-git SZZ ground-truth, and social-media findings hold across 6 concentric sample-size rings, computes exact 95% Wilson CIs and statistical power, and verifies post-expansion adequacy.",
        doc_type="study-protocol",
        status="active",
        skills=["empirical-methodologist", "skeptic-architect"],
    )

    md = [
        frontmatter.rstrip("\n"),
        "",
        f"# Multi-Scale Sample Size Persistence & Statistical Power Audit (`Ring 1 N = {r1_total_n:,}` to `Ring 6 Published MSR 2026 Reference N = 932,791`)",
        "",
        f"**Generated UTC:** `{summary_json['execution_timestamp_utc']}`  ",
        "**Audit Script:** `src/pipelines/p14_sample_power_audit.py`  ",
        "**Machine-Readable Table:** [`data_tables/multi_scale_sample_persistence_log.csv`](data_tables/multi_scale_sample_persistence_log.csv)",
        "",
        "---",
        "",
        "## 1. Concentric 6-Ring Scale Architecture (Post-Expansion Verified)",
        "",
        f"1. **Ring 6 — Global AIDev Unfiltered Population (Published MSR 2026 census reference: $N = 932,791$ PRs; local `aidev_all_repo.parquet` verified count: ${local_all_repos_n:,}$ repos):** Macro agent adoption volume.",
        f"2. **Ring 5 — Full Curated $\\ge 100$-Star Benchmark ($N = {aid_cur_ag_n:,}$ Coding-Agent PRs + ${aid_cur_hu_n:,}$ Human Baseline PRs = ${curated_aidev_n:,}$ PRs; plus $N = {cr_pol_n:,}$ PRs across ${cr_pol_repos}$ repos in `coderabbit_policy_outcomes_log.csv`).**",
        f"3. **Ring 4 & 4S — Within-Repository Matched Multi-Regime Cohorts & Bare-Git SZZ Ground Truth:** $N = {ws_n_rev+ws_n_sil:,}$ merged PRs across ${ws_repos}$ shared multi-regime repos; $N = {hu_tot_810+ag_tot_810:,}$ PRs across ${paired_ctrl.get('shared_repos_count', 0)}$ paired human+agent repos; and **$N = {len(szz_csv):,}$ commit-attributed merged PRs (`{len(szz_u14):,}` uncensored 14d, `{len(szz_u30):,}` uncensored 30d)** across `{summary_json['concentric_scale_rings']['Ring_4_Within_281_and_810_Shared_Repos']['szz_cloned_repos']}` local bare-git clones.",
        f"4. **Ring 3 — Formally Human-Reviewed Curated Subset (`Clean Unified 38-Bot Catalog`, $N = {len(rev_prs):,}$):** `Cohort B (Human-Only)` = **$N = {len(b_all):,}$** vs. `Cohort C (Tier-1 Review Bot + Human)` = **$N = {len(c_all):,}$**.",
        f"5. **Ring 2 — Within-{len(shared_bc)}-Shared-Repo Paired Human-Reviewed Subset ($N = {len(b_shared)+len(c_shared):,}$:** $N_B = {len(b_shared):,}$ vs. $N_C = {len(c_shared):,}$).",
        f"6. **Ring 1 — Broadened TypeSafe Jev Decision-Model Adopter Corpus:** **$N = {r1_total_n:,}$ mined PRs** (`{summary_json['concentric_scale_rings']['Ring_1_Jev_Adopter_Corpus']['jev_signal_distinct_prs']:,}` Jev-evaluated PRs, `{summary_json['concentric_scale_rings']['Ring_1_Jev_Adopter_Corpus']['formal_reviews_n']:,}` formal GitHub reviews, `$N = {s_cl_n+s_fl_n}$` Sentry DML Human PRs, `$N = {af_n+ac_n}$` Pooled Jev Coding-Agent PRs).",
        "",
        "---",
        "",
        "## 2. Multi-Scale Persistence & Statistical Power Ledger (`alpha = 0.05`, Two-Sided)",
        "",
        "| Scale Ring | Vector | Hypothesis Tested | Arm 1 ($k_1/n_1$, `%` `[95% CI]`) | Arm 2 ($k_2/n_2$, `%` `[95% CI]`) | Shift (`pp` / `%`) | $Z$ / $p$-value | Achieved Power | $N_{\\text{req}}$ / Arm (80% / 90%) | Power Verdict |",
        "| :--- | :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for c in comparisons:
        md.append(
            f"| `{c['scale_ring']}` | **`{c['vector_id']}`** | {c['hypothesis_label']} | "
            f"`{c['arm1_label']}`: **{c['p1_pct']}%** ({c['k1']}/{c['n1']}) `[{c['ci1_95_pct'][0]}%, {c['ci1_95_pct'][1]}%]` | "
            f"`{c['arm2_label']}`: **{c['p2_pct']}%** ({c['k2']}/{c['n2']}) `[{c['ci2_95_pct'][0]}%, {c['ci2_95_pct'][1]}%]` | "
            f"**{c['diff_pp']:+.2f} pp** ({c['relative_shift_pct']:+.1f}%) | "
            f"`Z={c['z_stat']}` (`p={c['p_value']:.2e}`) | **{c['achieved_power_pct']}%** | "
            f"`{c['n_per_arm_for_80pct_power']}` / `{c['n_per_arm_for_90pct_power']}` | `{c['power_status']}` |"
        )

    powered = [c for c in comparisons if c["achieved_power_pct"] >= 80.0]
    underpowered = [c for c in comparisons if c["achieved_power_pct"] < 80.0]
    md.extend([
        "",
        "---",
        "",
        "## 3. Post-Expansion Statistical Power Summary",
        "",
        f"- **Fully/Adequately Powered Hypotheses (`>= 80%` Power):** **{len(powered)} / {len(comparisons)}** tests.",
        f"- **Remaining Exploratory / Underpowered Cells (`< 80%` Power):** **{len(underpowered)} / {len(comparisons)}** tests.",
    ])
    for c in underpowered:
        md.append(
            f"  - `{c['vector_id']}` (`{c['scale_ring']}`): `{c['p1_pct']}%` vs `{c['p2_pct']}%` (`p = {c['p_value']:.2e}`, power = **{c['achieved_power_pct']}%**, needs `{c['n_per_arm_for_80pct_power']}`/arm for 80%)."
        )
    md.append("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    log.info("Wrote %s, %s, and %s (%d comparisons, %d powered >=80%%)",
             out_json, out_csv, out_md, len(comparisons), len(powered))


if __name__ == "__main__":
    main()
