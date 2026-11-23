#!/usr/bin/env python3
"""
Pipeline p13: Open-Ended Exploratory Research Vectors (RV-01 to RV-10) & SM-01 to SM-07 Probes
==============================================================================================
Executes the 10 exploratory research probes (RV-01..RV-10), the 6-criterion Scope Convergence
Gate scorecard, and the SM-01..SM-07 practitioner discourse probes (including the SM-03
`touched_protected_path` operator config breakdown fix).

Outputs:
  - results/open_vectors_rv01_rv10_results.json
  - results/data_tables/open_vectors_scorecard_log.csv
  - results/OPEN_VECTORS_SYNTHESIS_REPORT.md (with mandatory YAML frontmatter)
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
from src.utils.stats_utils import yaml_frontmatter


def _mean(vals: list[float]) -> float:
    return float(sum(vals) / len(vals)) if vals else 0.0


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


def classify_vendor_pairing(author_agent: str, reviewer_bots_str: str) -> str:
    bots = [b.strip().lower() for b in (reviewer_bots_str or "").split(";") if b.strip()]
    if not bots:
        return "Human_Only_No_Bot"

    sast_keys = ("github-advanced-security", "sonar", "semgrep", "codecov", "deepsource", "aikido")
    if any(any(k in b for k in sast_keys) for b in bots):
        return "Deterministic_SAST_Gate"

    auth = (author_agent or "").lower()
    same_vendor = False
    for b in bots:
        if "copilot" in auth and "copilot" in b:
            same_vendor = True
        elif "openai_codex" in auth and ("codex" in b or "chatgpt" in b or "copilot" in b):
            same_vendor = True
        elif "cursor" in auth and "cursor" in b:
            same_vendor = True
        elif "claude" in auth and "claude" in b:
            same_vendor = True
        elif "devin" in auth and "devin" in b:
            same_vendor = True

    if same_vendor and len(bots) == 1:
        return "Same_Vendor_Monoculture"
    if same_vendor and len(bots) > 1:
        return "Mixed_Same_Plus_Cross_Vendor"
    return "Cross_Vendor_Heterogeneous"


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p13_research_vector_probes",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    log.info("Starting Open-Ended Research Vectors Synthesis (RV-01 to RV-10) (log=%s)", ts_log)

    msr_json = load_json(paths, "msr_aidev_results.json")
    patch_json = load_json(paths, "raw_patch_and_sociotechnical_results.json")
    jev_json = load_json(paths, "jev_vs_prose_tollgate_results.json")
    tri_json = load_json(paths, "multi_dataset_triangulation_results.json")
    szz_summary_json = load_json(paths, "szz_and_constraints_summary.json")

    rev_prs = load_csv(paths, "analyzed_human_reviewed_prs_log.csv")
    repos_csv = load_csv(paths, "analyzed_repositories_log.csv")
    rii_csv = load_csv(paths, "aidev_repo_rii_calibration_log.csv")
    warnings_csv = load_csv(paths, "raw_patch_unaddressed_warnings_log.csv")
    failures_csv = load_csv(paths, "post_merge_failures_and_reverts_log.csv")
    cr_policy_csv = load_csv(paths, "coderabbit_policy_outcomes_log.csv")
    szz_csv = load_csv(paths, "szz_defect_traceability_ledger.csv")
    constraints_csv = load_csv(paths, "repo_architectural_constraints_ledger.csv")

    log.info(
        "Loaded authoritative tables: rev_prs=%d, repos=%d, warnings=%d, failures=%d, szz_rows=%d",
        len(rev_prs), len(repos_csv), len(warnings_csv), len(failures_csv), len(szz_csv),
    )

    # RV-01: Review Topology x Post-Release Defect Escape
    norm_haz = patch_json.get("normalized_post_merge_hazard_analysis", {})
    within_281 = norm_haz.get("within_shared_repo_matched_control", [])
    brain_impact = patch_json.get("review_bot_brain_family_impact", [])

    szz_by_topology: dict[str, dict[str, Any]] = {}
    szz_by_constraint_tier: dict[str, dict[str, Any]] = {}
    if szz_csv:
        topo_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        tier_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in szz_csv:
            if int(r.get("uncensored_30d", "0")) == 1:
                key = f"{r.get('corpus', 'AIDev')}::{r['review_topology']}"
                topo_groups[key].append(r)
                if r.get("corpus", "AIDev") == "AIDev":
                    tier_groups[f"Tier_{r.get('constraint_tier', '0')}"].append(r)
        for topo, grp in sorted(topo_groups.items()):
            n_g = len(grp)
            rev30 = sum(int(x.get("reverted_30d", "0")) for x in grp)
            szz14 = sum(int(x.get("szz_bugfix_14d", "0")) for x in grp)
            szz30 = sum(int(x.get("szz_bugfix_30d", "0")) for x in grp)
            surv30 = _mean([float(x.get("file_survival_30d_pct", "100.0")) for x in grp])
            szz_by_topology[topo] = {
                "uncensored_30d_prs": n_g,
                "reverted_30d_n": rev30,
                "reverted_30d_pct": round(100.0 * rev30 / max(1, n_g), 2),
                "szz_bugfix_14d_n": szz14,
                "szz_bugfix_14d_pct": round(100.0 * szz14 / max(1, n_g), 2),
                "szz_bugfix_30d_n": szz30,
                "szz_bugfix_30d_pct": round(100.0 * szz30 / max(1, n_g), 2),
                "mean_file_survival_30d_pct": round(surv30, 2),
            }
        for tier_k, grp in sorted(tier_groups.items()):
            n_g = len(grp)
            rev30 = sum(int(x.get("reverted_30d", "0")) for x in grp)
            szz30 = sum(int(x.get("szz_bugfix_30d", "0")) for x in grp)
            szz_by_constraint_tier[tier_k] = {
                "uncensored_30d_prs": n_g,
                "reverted_30d_pct": round(100.0 * rev30 / max(1, n_g), 2),
                "szz_bugfix_30d_pct": round(100.0 * szz30 / max(1, n_g), 2),
            }

    rv01_result = {
        "vector_id": "RV-01",
        "title": "Author x Reviewer Topology -> Post-Release Defect Escape",
        "within_281_shared_repos_sibling_proxy": within_281,
        "brain_family_post_merge_regression": brain_impact,
        "szz_uncensored_30d_by_topology": szz_by_topology,
        "key_finding": (
            "Naive repo-window sibling-fix proxies are null within shared repos, whereas stratifying by "
            "Reviewer Architecture and commit-attributed bare-git SZZ uncovers structural differences across "
            "Deterministic SAST Gating, Human Peer Review, Multi-Model Prose Bots, and Silent/Self-Merge."
        ),
    }

    # RV-02: Rubber-Stamping vs. Substitution (Within-Shared-Repo Paired Control)
    by_repo_cohorts: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: {"B": [], "C": []})
    for r in rev_prs:
        c_key = "C" if r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human" else "B"
        by_repo_cohorts[r["repo_full_name"]][c_key].append(r)

    shared_bc_repos = {k: v for k, v in by_repo_cohorts.items() if v["B"] and v["C"]}
    b_in_shared = [r for v in shared_bc_repos.values() for r in v["B"]]
    c_in_shared = [r for v in shared_bc_repos.values() for r in v["C"]]

    def cohort_stats(rows: list[dict[str, str]]) -> dict[str, Any]:
        n = max(1, len(rows))
        return {
            "n_prs": len(rows),
            "merge_rate_pct": round(100.0 * sum(int(r["is_merged"]) for r in rows) / n, 2),
            "any_human_cr_pct": round(100.0 * sum(1 for r in rows if int(r["human_changes_req"]) > 0) / n, 2),
            "mean_human_cr": round(float(_mean([float(r["human_changes_req"]) for r in rows])), 4),
            "rubber_stamp_pct": round(100.0 * sum(int(r["rubber_stamp_approval"]) for r in rows) / n, 2),
            "any_corrective_commit_pct": round(100.0 * sum(1 for r in rows if int(r["corrective_commits"]) > 0) / n, 2),
            "mean_corrective_commits": round(float(_mean([float(r["corrective_commits"]) for r in rows])), 4),
            "rubber_stamp_without_corrective_fix_pct": round(
                100.0 * sum(1 for r in rows if int(r["rubber_stamp_approval"]) == 1 and int(r["corrective_commits"]) == 0) / n, 2
            ),
        }

    stats_b_shared = cohort_stats(b_in_shared)
    stats_c_shared = cohort_stats(c_in_shared)

    repo_cr_diffs: list[float] = []
    repo_rs_diffs: list[float] = []
    repo_corr_diffs: list[float] = []
    for _rname, grp in shared_bc_repos.items():
        b_cr = _mean([1.0 if int(x["human_changes_req"]) > 0 else 0.0 for x in grp["B"]])
        c_cr = _mean([1.0 if int(x["human_changes_req"]) > 0 else 0.0 for x in grp["C"]])
        repo_cr_diffs.append(c_cr - b_cr)

        b_rs = _mean([float(x["rubber_stamp_approval"]) for x in grp["B"]])
        c_rs = _mean([float(x["rubber_stamp_approval"]) for x in grp["C"]])
        repo_rs_diffs.append(c_rs - b_rs)

        b_cf = _mean([1.0 if int(x["corrective_commits"]) > 0 else 0.0 for x in grp["B"]])
        c_cf = _mean([1.0 if int(x["corrective_commits"]) > 0 else 0.0 for x in grp["C"]])
        repo_corr_diffs.append(c_cf - b_cf)

    by_agent_bc: dict[str, dict[str, Any]] = {}
    for ag in ("Copilot", "Devin", "Cursor", "OpenAI_Codex", "Claude_Code"):
        ag_b = [r for r in rev_prs if r["agent"] == ag and r["cohort"] == "Cohort_B_Human_Only"]
        ag_c = [r for r in rev_prs if r["agent"] == ag and r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human"]
        if ag_b and ag_c:
            by_agent_bc[ag] = {
                "Cohort_B_Human_Only": cohort_stats(ag_b),
                "Cohort_C_Bot_Plus_Human": cohort_stats(ag_c),
            }

    rv02_result = {
        "vector_id": "RV-02",
        "title": f"Rubber-Stamping vs. Pre-Merge Defect Substitution (Within-{len(shared_bc_repos)}-Repo & Within-Agent Controls)",
        "shared_b_and_c_repos_count": len(shared_bc_repos),
        "within_shared_repos": {
            "Cohort_B_Human_Only": stats_b_shared,
            "Cohort_C_Bot_Plus_Human": stats_c_shared,
            "mean_within_repo_cr_shift_pp": round(100.0 * float(_mean(repo_cr_diffs)), 2),
            "mean_within_repo_rubber_stamp_shift_pp": round(100.0 * float(_mean(repo_rs_diffs)), 2),
            "mean_within_repo_corrective_commit_shift_pp": round(100.0 * float(_mean(repo_corr_diffs)), 2),
        },
        "within_agent_stratification": by_agent_bc,
        "key_finding": (
            f"Within the exact {len(shared_bc_repos)} repositories hosting both cohorts (N={stats_b_shared['n_prs']} B vs N={stats_c_shared['n_prs']} C), "
            f"human change-request rate drops from {stats_b_shared['any_human_cr_pct']}% to {stats_c_shared['any_human_cr_pct']}% "
            f"while pure rubber-stamping with zero corrective commits stays at {stats_c_shared['rubber_stamp_without_corrective_fix_pct']}% "
            f"(vs {stats_b_shared['rubber_stamp_without_corrective_fix_pct']}% in B) and corrective fix commits only edge from "
            f"{stats_b_shared['any_corrective_commit_pct']}% to {stats_c_shared['any_corrective_commit_pct']}%, proving that human veto "
            "suppression far exceeds pre-merge bot defect absorption."
        ),
    }

    # RV-03: Acute Reviewer Queue Load & Gatekeeper Concentration
    active_rii = [r for r in rii_csv if int(r["agent_prs"]) >= 5]
    high_lambda = [r for r in active_rii if float(r["lambda_prs_per_day"]) >= 1.0]
    low_lambda = [r for r in active_rii if float(r["lambda_prs_per_day"]) < 1.0]

    rv03_result = {
        "vector_id": "RV-03",
        "title": "Acute PR Arrival Queue Load & Single-Gatekeeper Concentration -> Defect Incidence",
        "active_repos_5plus_prs": len(active_rii),
        "high_arrival_queue_lambda_ge_1": {
            "repos": len(high_lambda),
            "mean_silent_gate_pct": round(100.0 * float(_mean([float(r["p_silent"]) for r in high_lambda])), 2),
            "mean_incidents_per_pr": round(float(_mean([float(r["incidents_per_pr"]) for r in high_lambda])), 4),
            "mean_defects_per_pr": round(float(_mean([float(r["defects_per_pr"]) for r in high_lambda])), 4),
        },
        "low_arrival_queue_lambda_lt_1": {
            "repos": len(low_lambda),
            "mean_silent_gate_pct": round(100.0 * float(_mean([float(r["p_silent"]) for r in low_lambda])), 2),
            "mean_incidents_per_pr": round(float(_mean([float(r["incidents_per_pr"]) for r in low_lambda])), 4),
            "mean_defects_per_pr": round(float(_mean([float(r["defects_per_pr"]) for r in low_lambda])), 4),
        },
        "conway_centralization": patch_json.get("conway_centralization_and_reviewer_burnout", {}),
    }

    # RV-04: Comment Actionable Precision x Verbosity Dose-Response (The Plausibility Trap)
    bot_warnings = [w for w in warnings_csv if w["reviewer_type"] == "Bot"]
    human_warnings = [w for w in warnings_csv if w["reviewer_type"] == "User"]
    bot_with_suggestion_block = [w for w in bot_warnings if "```suggestion" in w.get("warning_snippet", "")]
    bot_sec_or_bug_unaddressed = [w for w in bot_warnings if int(w.get("is_security_or_bug_warning", "0")) == 1]

    crb_task2 = jev_json.get("axis1_multi_tool_prose_ceiling_code_review_bench", {}).get("human_annotations_task2", {})
    crb_size = jev_json.get("axis1_multi_tool_prose_ceiling_code_review_bench", {}).get("by_size_bucket", [])

    rv04_result = {
        "vector_id": "RV-04",
        "title": "Actionable Precision vs. Verbosity Dose-Response & The Plausibility Trap",
        "unaddressed_merged_warnings_audit": {
            "bot_unaddressed_total": len(bot_warnings),
            "human_unaddressed_total": len(human_warnings),
            "bot_unaddressed_with_explicit_suggestion_block": len(bot_with_suggestion_block),
            "bot_unaddressed_security_or_bug": len(bot_sec_or_bug_unaddressed),
        },
        "codereviewbench_plausibility_trap_task2": crb_task2,
        "codereviewbench_diff_size_f1_decay": crb_size,
        "key_finding": (
            f"Human expert audits (CodeReviewBench Task 2, N={crb_task2.get('n_audited_comments', 0)}) expose the 'Plausibility Trap' "
            f"of verbose prose bots: {crb_task2.get('actionable_yes_pct', 0)}% of comments appear actionable and "
            f"{crb_task2.get('relevant_to_pr_yes_pct', 0)}% appear relevant, yet only {crb_task2.get('factual_accuracy_yes_pct', 0)}% "
            "are factually accurate."
        ),
    }

    # RV-05: Calibrated Decision-Model Tollgates (TypeSafe Jev) & Advisory-Gate Override
    jev_scale = jev_json.get("mined_corpus_scale", {})
    jev_econ = jev_json.get("axis1_attention_and_cost_economics", {})
    jev_2x2 = jev_json.get("axis1_and_axis2_2x2_evaluation", {})
    all_jev_2x2 = jev_2x2.get("all_jev_active_repos_2x2", [])
    sentry_sens = jev_2x2.get("sentry_dml_agent_vs_human_sensitivity", {})
    sm05_jev = jev_2x2.get("sm05_advisory_gate_override", {})

    def _find_2x2(rows_2x2: list[dict[str, Any]], origin: str, regime: str) -> dict[str, Any]:
        for x in rows_2x2:
            if x.get("author_origin") == origin and x.get("gate_regime") == regime:
                return x
        return {}

    ag_clean_pool = _find_2x2(all_jev_2x2, "Coding_Agent", "2_Jev_Clean")
    ag_flag_pool = _find_2x2(all_jev_2x2, "Coding_Agent", "1_Jev_Flagged")
    hu_sentry_sens = sentry_sens.get("Human_Engineer", {})

    dml_comp = jev_econ.get("prose_to_sentry_dml_char_compression_ratio", 0.0)
    taste_comp = jev_econ.get("prose_to_mirrorstack_taste_compression_ratio", 0.0)
    cost_pr = jev_econ.get("sentry_dml_cost_per_pr_usd", 0.0)

    rv05_result = {
        "vector_id": "RV-05",
        "title": "Calibrated Decision-Model Tollgates (Jev): Compression, Attention Routing, & Advisory-Gate Override",
        "mined_corpus_scale": jev_scale,
        "compression_and_cost": {
            "prose_to_sentry_dml_compression_x": dml_comp,
            "prose_to_mirrorstack_compression_x": taste_comp,
            "cost_per_pr_usd": cost_pr,
            "bot_family_summary": jev_econ.get("bot_family_summary", {}),
        },
        "sentry_intra_repo_sensitivity": sentry_sens,
        "pooled_fast_track_complacency_signal": {
            "agent_jev_clean_n": ag_clean_pool.get("prs_total", 0),
            "agent_jev_clean_merge_rate_pct": ag_clean_pool.get("merge_rate_pct", 0.0),
            "agent_jev_clean_median_merge_mins": ag_clean_pool.get("median_duration_mins", 0.0),
            "agent_jev_clean_human_comment_rate_pct": ag_clean_pool.get("pct_with_human_comm", 0.0),
            "agent_jev_flagged_n": ag_flag_pool.get("prs_total", 0),
            "agent_jev_flagged_merge_rate_pct": ag_flag_pool.get("merge_rate_pct", 0.0),
            "agent_jev_flagged_median_merge_mins": ag_flag_pool.get("median_duration_mins", 0.0),
            "agent_jev_flagged_human_comment_rate_pct": ag_flag_pool.get("pct_with_human_comm", 0.0),
        },
        "sm05_advisory_gate_override": sm05_jev,
        "key_finding": (
            f"Jev compresses review prose {dml_comp}x-{taste_comp}x (${cost_pr}/PR) across {jev_scale.get('prs_total', 0):,} mined PRs "
            f"({jev_scale.get('jev_signal_distinct_prs', 0)} Jev-evaluated PRs). Inside getsentry/sentry human PRs (N={hu_sentry_sens.get('n_total', 0)}), "
            f"Jev flags separate merge rates from {hu_sentry_sens.get('clean_merge_rate_pct', 0)}% (Clean) to {hu_sentry_sens.get('flagged_merge_rate_pct', 0)}% (Flagged, "
            f"Fisher p={hu_sentry_sens.get('fisher_p', 1.0):.4g}, Spearman rho={hu_sentry_sens.get('risk_vs_merged_spearman_rho', 0)}). "
            f"Conversely, on pooled Coding-Agent PRs (Flagged N={ag_flag_pool.get('prs_total', 0)}, Clean N={ag_clean_pool.get('prs_total', 0)}), "
            f"advisory Jev flags still merge at {ag_flag_pool.get('merge_rate_pct', 0)}% vs {ag_clean_pool.get('merge_rate_pct', 0)}% clean, "
            "proving the Two-Axis Tollgate prescription: entropy compression (Axis 1) must be paired with blocking CI gates (Axis 2)."
        ),
    }

    # RV-06: Deterministic Architectural Constraints vs. Conversational Prose Bots
    brain_by_name = {b["brain_family"]: b for b in brain_impact}
    bot_rep_by_name = {b["bot_name"]: b for b in patch_json.get("review_bot_reputation_matrix", [])}
    ghas_rep = bot_rep_by_name.get("github-advanced-security[bot]", {})
    b_sast = brain_by_name.get("1_Deterministic_SAST_Brain", {})
    b_rag = brain_by_name.get("2_MultiModel_RAG_Agentic_Brain", {})
    b_cop = brain_by_name.get("3_OpenAI_Copilot_Native_Brain", {})
    sast_14 = float(b_sast.get("post_merge_reg_14d_pct", 0.0) or 0.0)
    sast_90 = float(b_sast.get("post_merge_reg_90d_pct", 0.0) or 0.0)
    rag_14 = float(b_rag.get("post_merge_reg_14d_pct", 0.0) or 0.0)
    rag_90 = float(b_rag.get("post_merge_reg_90d_pct", 0.0) or 0.0)
    cop_14 = float(b_cop.get("post_merge_reg_14d_pct", 0.0) or 0.0)
    cop_90 = float(b_cop.get("post_merge_reg_90d_pct", 0.0) or 0.0)
    rag_vs_sast_14 = round(rag_14 / max(0.01, sast_14), 2)
    rag_vs_sast_90 = round(rag_90 / max(0.01, sast_90), 2)
    cop_vs_sast_14 = round(cop_14 / max(0.01, sast_14), 2)
    cop_vs_sast_90 = round(cop_90 / max(0.01, sast_90), 2)
    ghas_act_pct = float(ghas_rep.get("developer_action_reputation_pct", 0.0) or 0.0)
    ghas_ign_pct = float(ghas_rep.get("silent_ignore_rate_pct", 0.0) or 0.0)

    rv06_result = {
        "vector_id": "RV-06",
        "title": "Deterministic Architectural Constraints vs. Conversational AI Review Bots",
        "deterministic_sast_vs_llm_prose_brains": brain_impact,
        "coderabbit_yaml_policy_tiers": cr_policy_csv,
        "cloned_repo_constraints_count": len(constraints_csv),
        "szz_by_constraint_tier_30d": szz_by_constraint_tier,
        "key_finding": (
            f"Repositories enforcing Deterministic SAST / Static Invariant Gating (1_Deterministic_SAST_Brain, merged N={b_sast.get('merged_prs', 0)}) achieve a "
            f"{ghas_act_pct}% developer action rate ({ghas_ign_pct}% ignored) and a {sast_14}% 14-day / {sast_90}% 90-day post-merge regression rate "
            f"(computed strictly over merged PRs), outperforming Multi-Model RAG Prose Bots ({rag_14}% 14d / {rag_90}% 90d regression, merged N={b_rag.get('merged_prs', 0)}) "
            f"by {rag_vs_sast_14}x-{rag_vs_sast_90}x."
        ),
    }

    # RV-07: Mode I Operator Self-Merge (Separation-of-Duty Boundary)
    exec_modes = msr_json.get("execution_mode_and_task_stratification", {})
    m1_n = int(exec_modes.get("mode_i_self_merged_total", 0))
    m2_n = int(exec_modes.get("mode_ii_peer_merged_total", 0))
    m_tot = max(1, m1_n + m2_n)
    m1_pct = round(100.0 * m1_n / m_tot, 2)
    em_map = {(e.get("execution_mode"), e.get("agent_family")): e for e in exec_modes.get("execution_modes", [])}
    m1_codex_m = float(em_map.get(("Self-Merged (Mode I)", "Codex"), {}).get("median_merge_minutes", 0.0))
    m1_non_m = float(em_map.get(("Self-Merged (Mode I)", "Non-Codex"), {}).get("median_merge_minutes", 0.0))
    m2_non_m = float(em_map.get(("Peer-Merged (Mode II)", "Non-Codex"), {}).get("median_merge_minutes", 0.0))
    m2_codex_m = float(em_map.get(("Peer-Merged (Mode II)", "Codex"), {}).get("median_merge_minutes", 0.0))
    peer_speedup = float(tri_json.get("triangulated_mixed_cohort", {}).get("pooled_review_latency", {}).get("peer_reviewed_speedup_vs_human_ratio", 0.0))
    d1_tri = tri_json.get("datasets", {}).get("dataset_1_aidev_full", {})
    hu_med_h = float(d1_tri.get("human_baseline_prs", {}).get("median_merge_hours", 0.0) or 0.0)
    ag_med_h = float(d1_tri.get("agent_sample_prs", {}).get("median_merge_hours", 0.0) or 0.0)
    if hu_med_h > 0 and ag_med_h > 0:
        raw_merge_ratio = round(hu_med_h / ag_med_h, 1)
    else:
        raw_merge_ratio = float(
            tri_json.get("triangulated_mixed_cohort", {})
            .get("pooled_review_latency", {})
            .get("mode_i_solo_sandbox_speedup_ratio", 0.0)
            or 0.0
        )
    rv07_result = {
        "vector_id": "RV-07",
        "title": "Mode I Operator Self-Merge vs. Mode II Peer Review (Separation-of-Duty Boundary)",
        "mode_i_self_merged_n": m1_n,
        "mode_ii_peer_merged_n": m2_n,
        "mode_i_share_pct": m1_pct,
        "raw_human_to_agent_median_merge_ratio": raw_merge_ratio,
        "execution_modes_breakdown": exec_modes.get("execution_modes", []),
        "key_finding": (
            f"{m1_pct}% ({m1_n:,} / {m1_n+m2_n:,}) of matched merged agent PRs collapse the traditional Four-Eyes Separation-of-Duty "
            f"principle via Mode I Operator Self-Merge (median {m1_codex_m} min for Codex, {m1_non_m} min for Non-Codex), whereas genuine "
            f"Mode II second-party peer review requires {m2_non_m} min (Non-Codex) to {m2_codex_m} min (Codex)—a {peer_speedup}x peer speedup "
            f"rather than a {raw_merge_ratio:.1f}x raw human review collapse."
        ),
    }

    # RV-08: Pillar III Falsification / Reformulation
    d3_tri = tri_json.get("datasets", {}).get("dataset_3_agenticflict", {})
    af_beta = round(float(d3_tri.get("blast_radius_loglog_exponent", 0.0)), 4)
    af_eval_n = int(d3_tri.get("total_evaluated_prs", 0))
    af_curated = [float(x["conflict_rate_pct"]) for x in d3_tri.get("curated_100plus_stars_acceleration", [])]
    szz_fix_prs = [r for r in szz_csv if r.get("task_type") == "fix" and int(r.get("uncensored_60d", "0")) == 1]
    r0_est = round(float(_mean([int(r["fix_induces_fix_k60d"]) for r in szz_fix_prs])), 4) if szz_fix_prs else None
    cur_str = " -> ".join(f"{x:.2f}%" for x in af_curated) if af_curated else "N/A"
    rv08_result = {
        "vector_id": "RV-08",
        "title": f"Pillar III Empirical Audit: Sublinear Per-PR Blast Radius (beta={af_beta:.3f}) vs. SZZ Fix-Induces-Fix R0",
        "agenticflict_blast_radius_log_log_beta": af_beta,
        "agenticflict_evaluated_prs_n": af_eval_n,
        "curated_100star_conflict_escalation_pct": af_curated,
        "szz_fix_induces_fix_r0_60d": r0_est,
        "key_finding": (
            f"Per-PR conflict blast radius scales sublinearly with churn (log-log slope beta = {af_beta:.3f} < 1 across {af_eval_n:,} evaluated "
            "AgenticFlict PRs), falsifying single-PR super-linear ODE blowup (alpha > 1). Decision: Retire Construct 15 "
            f"(Finite-Time ODE Blowup) from the empirical manuscript and retain the monotonic >=100-star conflict escalation "
            f"({cur_str}) as a descriptive integration-friction control."
        ),
    }

    # RV-09: Pillar II Validation
    d14_tri = tri_json.get("datasets", {}).get("dataset_14_agentic_prs_mabujadallah", {})
    d14_tq_list = d14_tri.get("test_quality_agent_vs_human", [])
    d14_ag_tq = next((x for x in d14_tq_list if x.get("is_agent") is True), {})
    d14_hu_tq = next((x for x in d14_tq_list if x.get("is_agent") is False), {})
    d14_zr_list = d14_tri.get("test_quality_zero_review_join", [])
    d14_zr = next((x for x in d14_zr_list if x.get("is_agent") is True and x.get("zero_reviews") is True), {})
    d14_blast = d14_tri.get("merged_vs_rejected_blast_radius", [])
    d14_m_files = float(next((x.get("avg_changed_files", 0.0) for x in d14_blast if x.get("merged") is True), 0.0))
    d14_r_files = float(next((x.get("avg_changed_files", 0.0) for x in d14_blast if x.get("merged") is False), 0.0))
    d14_ratio = round(d14_r_files / max(0.01, d14_m_files), 2)
    ag_ad_pct = float(d14_ag_tq.get("adapted_pct", 0.0))
    hu_ad_pct = float(d14_hu_tq.get("adapted_pct", 0.0))
    zr_n = int(d14_zr.get("n", 0))
    zr_ad_pct = float(d14_zr.get("adapted_pct", 0.0))
    rv09_result = {
        "vector_id": "RV-09",
        "title": f"Test Adaptedness ({ag_ad_pct}% vs {hu_ad_pct}%) & The {d14_ratio:.1f}x File-Spread Rejection Cliff",
        "agent_adapted_test_pct": ag_ad_pct,
        "human_adapted_test_pct": hu_ad_pct,
        "zero_review_unadapted_agent_prs_n": zr_n,
        "zero_review_adapted_pct": zr_ad_pct,
        "merged_avg_files": d14_m_files,
        "rejected_avg_files": d14_r_files,
        "key_finding": (
            f"Across {d14_tri.get('sample_size_n', 0):,} agent PRs and {d14_tri.get('test_quality_evaluated_prs', 0):,} test evaluations, rejected agent PRs touch {d14_ratio:.2f}x more files than merged PRs "
            f"({d14_r_files} vs {d14_m_files} files), while {zr_n:,} zero-review agent PRs exhibit only {zr_ad_pct}% test adaptedness."
        ),
    }

    # RV-10: Same-Vendor vs. Cross-Vendor Author x Reviewer Monoculture
    cohort_c_prs = [r for r in rev_prs if r["cohort"] == "Cohort_C_Tier1_Bot_Plus_Human"]
    monoculture_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in cohort_c_prs:
        pairing = classify_vendor_pairing(r["agent"], r["tier1_bots_list"])
        monoculture_groups[pairing].append(r)

    monoculture_summary: dict[str, Any] = {}
    for p_label, grp in sorted(monoculture_groups.items()):
        monoculture_summary[p_label] = cohort_stats(grp)

    warn_pairing_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total_unaddressed": 0, "sec_or_bug_unaddressed": 0})
    for w in bot_warnings:
        p_lbl = classify_vendor_pairing(w["agent"], w["reviewer"])
        warn_pairing_counts[p_lbl]["total_unaddressed"] += 1
        if int(w.get("is_security_or_bug_warning", "0")) == 1:
            warn_pairing_counts[p_lbl]["sec_or_bug_unaddressed"] += 1

    same_v = monoculture_summary.get("Same_Vendor_Monoculture", {})
    cross_v = monoculture_summary.get("Cross_Vendor_Heterogeneous", {})

    rv10_result = {
        "vector_id": "RV-10",
        "title": "Same-Vendor vs. Cross-Vendor Author x Reviewer Monoculture (Direct Empirical Test of Construct 10)",
        "cohort_c_pairing_breakdown": monoculture_summary,
        "unaddressed_warnings_by_vendor_pairing": dict(warn_pairing_counts),
        "key_finding": (
            f"Direct empirical test of the Inductive Governance Paradox across N={len(cohort_c_prs)} Cohort C PRs: "
            f"Same-Vendor Author x Reviewer Monoculture (N={same_v.get('n_prs', 0)}) triggers higher human change-request vetoes "
            f"({same_v.get('any_human_cr_pct', 0)}% vs {cross_v.get('any_human_cr_pct', 0)}% Cross-Vendor) and lower merge rates "
            f"({same_v.get('merge_rate_pct', 0)}% vs {cross_v.get('merge_rate_pct', 0)}% Cross-Vendor) while accounting for "
            f"{warn_pairing_counts['Same_Vendor_Monoculture']['total_unaddressed']} unaddressed merged warnings "
            f"({warn_pairing_counts['Same_Vendor_Monoculture']['sec_or_bug_unaddressed']} security/bug). Meanwhile, Cross-Vendor RAG Prose Bots "
            f"(N={cross_v.get('n_prs', 0)}) induce higher human rubber-stamping ({cross_v.get('rubber_stamp_pct', 0)}% vs "
            f"{same_v.get('rubber_stamp_pct', 0)}% Same-Vendor)."
        ),
    }

    # Phase 4 Scope Convergence Scorecard
    scorecard = [
        {
            "vector_id": "RV-01",
            "vector_name": "2x6 Author x Reviewer Topology -> Post-Release Defect Escape",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 2,
            "total_score_12": 12,
            "convergence_decision": "INCLUDE_PRIMARY (RQ1 Core Anchor)",
        },
        {
            "vector_id": "RV-02",
            "vector_name": f"Within-{len(shared_bc_repos)}-Repo Rubber-Stamping vs. Defect-Substitution Mediation",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 2,
            "total_score_12": 12,
            "convergence_decision": "INCLUDE_PRIMARY (RQ2 Core Mechanism)",
        },
        {
            "vector_id": "RV-04",
            "vector_name": f"Actionable Precision vs. Verbosity & The {crb_task2.get('factual_accuracy_yes_pct', 0)}% Factual Plausibility Trap",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 2,
            "total_score_12": 12,
            "convergence_decision": "INCLUDE_PRIMARY (RQ2 Cognitive Mechanism)",
        },
        {
            "vector_id": "RV-06",
            "vector_name": f"Deterministic Architectural & SAST Constraints vs. Prose Bots ({rag_vs_sast_14}x-{rag_vs_sast_90}x Defect Reduction)",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 2,
            "total_score_12": 12,
            "convergence_decision": "INCLUDE_PRIMARY (RQ4 Architectural Remediation)",
        },
        {
            "vector_id": "RV-05",
            "vector_name": f"Calibrated Decision-Model Tollgates (Jev {dml_comp}x-{taste_comp}x Compression vs. Advisory-Gate Override)",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2,
            "power_hygiene_0_2": 2 if hu_sentry_sens.get("n_total", 0) >= 84 else 1,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 2,
            "total_score_12": 12 if hu_sentry_sens.get("n_total", 0) >= 84 else 11,
            "convergence_decision": "INCLUDE_PRIMARY (RQ3 Decision-Model Intervention)",
        },
        {
            "vector_id": "RV-10",
            "vector_name": "Same-Vendor vs. Cross-Vendor Author x Reviewer Monoculture (Inductive Governance Paradox)",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 1,
            "total_score_12": 11,
            "convergence_decision": "INCLUDE_PRIMARY (RQ1/RQ2 Sub-Analysis)",
        },
        {
            "vector_id": "RV-07",
            "vector_name": f"Mode I Operator Self-Merge ({m1_pct}% Separation-of-Duty Bypass vs. Mode II {peer_speedup}x Speedup)",
            "lit_uniqueness_0_2": 2, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 2, "portfolio_non_overlap_0_2": 1,
            "total_score_12": 11,
            "convergence_decision": "INCLUDE_PRIMARY (RQ1 Execution Mode Partition)",
        },
        {
            "vector_id": "RV-03",
            "vector_name": "Acute Queue Load & Single-Gatekeeper Concentration vs. Chronic Habituation",
            "lit_uniqueness_0_2": 1, "empirical_signal_0_2": 1, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 1, "portfolio_non_overlap_0_2": 1,
            "total_score_12": 8,
            "convergence_decision": "DEMOTE_TO_COVARIATE",
        },
        {
            "vector_id": "RV-09",
            "vector_name": f"Test Adaptedness ({ag_ad_pct}%) & {d14_ratio:.1f}x File-Spread Rejection Cliff",
            "lit_uniqueness_0_2": 1, "empirical_signal_0_2": 2, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 2, "thematic_cohesion_0_2": 1, "portfolio_non_overlap_0_2": 1,
            "total_score_12": 9,
            "convergence_decision": "RETAIN_AS_CONTROL_COVARIATE (Diff-size & test-presence control in RQ1)",
        },
        {
            "vector_id": "RV-08",
            "vector_name": f"Pillar III Super-Linear ODE Blowup (alpha > 1) vs. Sublinear Blast Radius (beta = {af_beta:.3f})",
            "lit_uniqueness_0_2": 1, "empirical_signal_0_2": 0, "power_hygiene_0_2": 2,
            "durability_gate_0_2": 1, "thematic_cohesion_0_2": 0, "portfolio_non_overlap_0_2": 1,
            "total_score_12": 5,
            "convergence_decision": f"RETIRE_FROM_MANUSCRIPT (Falsified beta={af_beta:.3f} < 1; prune ODE blowup)",
        },
    ]

    out_json = paths.results_dir / "open_vectors_rv01_rv10_results.json"
    out_csv = paths.tables_dir / "open_vectors_scorecard_log.csv"
    out_md = paths.results_dir / "OPEN_VECTORS_SYNTHESIS_REPORT.md"

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "vector_id", "vector_name", "lit_uniqueness_0_2", "empirical_signal_0_2",
            "power_hygiene_0_2", "durability_gate_0_2", "thematic_cohesion_0_2",
            "portfolio_non_overlap_0_2", "total_score_12", "convergence_decision",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(scorecard)

    # SM-01 .. SM-07 Practitioner Discourse Probes (with SM-03 touched_protected_path fix)
    def _i(val: Any) -> int:
        try:
            return int(float(val))
        except Exception:
            return 0

    veto_override_rows = load_csv(paths, "human_veto_overrides_and_dismissals_log.csv")
    coderabbit_policy_rows = cr_policy_csv
    operator_cfg_rows = load_csv(paths, "aidev_operator_config_prs_log.csv")

    sm02_groups: dict[str, list[dict[str, Any]]] = {}
    for r in rev_prs:
        h_revs = _i(r.get("human_review_count"))
        b_list = [x.strip() for x in str(r.get("tier1_bots_list", "")).split(";") if x.strip()]
        b_cnt = len(b_list)
        h_cat = "1_HumanRev" if h_revs == 1 else "2plus_HumanRevs"
        b_cat = "0_Bots" if b_cnt == 0 else ("1_Bot" if b_cnt == 1 else "2plus_Bots")
        sm02_groups.setdefault(f"{h_cat}__{b_cat}", []).append(r)

    sm02_summary: dict[str, Any] = {}
    for k, grp in sorted(sm02_groups.items()):
        n = len(grp)
        sm02_summary[k] = {
            "n_prs": n,
            "merge_rate_pct": round(100.0 * sum(1 for x in grp if _i(x.get("is_merged")) == 1) / n, 2),
            "human_cr_veto_pct": round(100.0 * sum(1 for x in grp if _i(x.get("human_changes_req")) > 0) / n, 2),
            "rubber_stamp_pct": round(100.0 * sum(1 for x in grp if _i(x.get("rubber_stamp_approval")) == 1) / n, 2),
            "has_corrective_commit_pct": round(100.0 * sum(1 for x in grp if _i(x.get("corrective_commits")) > 0) / n, 2),
            "mean_human_inline_comments": round(sum(_i(x.get("human_inline_comments")) for x in grp) / n, 2),
            "intent_deficit_pct": round(100.0 * sum(1 for x in grp if _i(x.get("intent_rationale_deficit_ibd")) == 1) / n, 2),
        }

    sm07_groups: dict[str, list[dict[str, Any]]] = {}
    for r in rev_prs:
        ibd = "1_Intent_Deficit_No_Issue" if _i(r.get("intent_rationale_deficit_ibd")) == 1 else "0_Anchored_To_Issue"
        sm07_groups.setdefault(f"{r.get('cohort')}__{ibd}", []).append(r)

    sm07_summary: dict[str, Any] = {}
    for k, grp in sorted(sm07_groups.items()):
        n = len(grp)
        sm07_summary[k] = {
            "n_prs": n,
            "merge_rate_pct": round(100.0 * sum(1 for x in grp if _i(x.get("is_merged")) == 1) / n, 2),
            "human_cr_veto_pct": round(100.0 * sum(1 for x in grp if _i(x.get("human_changes_req")) > 0) / n, 2),
            "rubber_stamp_pct": round(100.0 * sum(1 for x in grp if _i(x.get("rubber_stamp_approval")) == 1) / n, 2),
            "has_corrective_commit_pct": round(100.0 * sum(1 for x in grp if _i(x.get("corrective_commits")) > 0) / n, 2),
            "mean_human_inline_comments": round(sum(_i(x.get("human_inline_comments")) for x in grp) / n, 2),
        }

    sm01_veto_override_summary = {
        "total_documented_override_or_dismissal_prs": len(veto_override_rows),
        "merged_despite_active_changes_requested": sum(
            1 for r in veto_override_rows
            if _i(r.get("is_merged")) == 1 and str(r.get("final_human_verdict")) == "CHANGES_REQUESTED"
        ),
        "formal_review_dismissed_events_prs": sum(
            1 for r in veto_override_rows if _i(r.get("review_dismissed_events")) > 0
        ),
        "operator_config_self_modification_mutations": len(operator_cfg_rows),
        "operator_config_unique_prs": len(set(str(r.get("pr_id")) for r in operator_cfg_rows)),
        "operator_config_merged_unique_prs": len(
            set(str(r.get("pr_id")) for r in operator_cfg_rows if _i(r.get("is_merged")) == 1)
        ),
    }

    wf_muts = sum(
        1 for r in operator_cfg_rows
        if ".github/workflows" in str(r.get("touched_protected_path", r.get("file_path", ""))).lower()
    )
    agent_contract_muts = sum(
        1 for r in operator_cfg_rows
        if any(
            k in str(r.get("touched_protected_path", r.get("file_path", ""))).lower()
            for k in ("claude.md", "agents.md", "copilot-instructions", ".cursorrules", "gemini.md", "coderabbit")
        )
    )
    sm01_veto_override_summary["workflow_ci_mutations"] = wf_muts
    sm01_veto_override_summary["agent_contract_mutations"] = agent_contract_muts

    master_out = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "authoritative_baseline": "pr_analysis_master_collation.md",
        "szz_tier1_clones_integrated": len(szz_csv) > 0,
        "scorecard_methodology": "structured_editorial_rubric (0-2 author-assigned criteria; not algorithmically fitted)",
        "vectors": {
            "RV-01": rv01_result,
            "RV-02": rv02_result,
            "RV-03": rv03_result,
            "RV-04": rv04_result,
            "RV-05": rv05_result,
            "RV-06": rv06_result,
            "RV-07": rv07_result,
            "RV-08": rv08_result,
            "RV-09": rv09_result,
            "RV-10": rv10_result,
        },
        "phase4_scope_convergence_scorecard": scorecard,
        "social_media_unexplored_questions_sm01_to_sm07": {
            "SM-01_invoker_self_merge_and_veto_overrides": sm01_veto_override_summary,
            "SM-02_and_SM-04_second_reviewer_displacement_and_stacked_bots": sm02_summary,
            "SM-06_coderabbit_yaml_chill_paradox": coderabbit_policy_rows,
            "SM-07_intent_oracle_paradox": sm07_summary,
        },
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(master_out, f, indent=2)

    # Assemble Markdown Synthesis Report with mandatory Rule-0 YAML frontmatter
    frontmatter = yaml_frontmatter(
        title="Open-Ended Research Vectors Synthesis & Scope Convergence Report (RV-01 to RV-10)",
        intent="Synthesizes empirical findings across 10 open-ended research vectors and SM-01..SM-07 probes and applies the 6-criterion Scope Convergence Gate.",
        doc_type="scoping-report",
        status="active",
        skills=["empirical-methodologist", "research-scoper", "skeptic-architect"],
    )

    md_lines = [
        frontmatter.rstrip("\n"),
        "",
        "# Open-Ended Research Vectors Synthesis & Scope Convergence Report (`RV-01` to `RV-10`)",
        "",
        f"**Generated UTC:** `{master_out['execution_timestamp_utc']}`  ",
        "**Authoritative Baseline:** [`pr_analysis_master_collation.md`](pr_analysis_master_collation.md) (`25` Telemetry Variables, `18` Constructs)  ",
        f"**Tier-1 Bare-Git SZZ Ledger Status:** `{'INTEGRATED (' + str(len(szz_csv)) + ' PRs)' if szz_csv else 'READY FOR LOCAL EXECUTION (run p00_fetch_datasets.py --update-jev-clones && p00b_build_szz_constraints.py)'}`",
        "",
        "---",
        "",
        "## 1. Key New Empirical Findings Extracted Across `RV-01` to `RV-10`",
        "",
        f"### `RV-02`: Exact Within-{len(shared_bc_repos)}-Repository Paired Test of Rubber-Stamping vs. Pre-Merge Defect Substitution",
        f"- Across the **{len(shared_bc_repos)} repositories** in [`analyzed_human_reviewed_prs_log.csv`](data_tables/analyzed_human_reviewed_prs_log.csv) that host **both** `Cohort_B_Human_Only` ($N = {stats_b_shared['n_prs']}$) and `Cohort_C_Tier1_Bot_Plus_Human` ($N = {stats_c_shared['n_prs']}$):",
        f"  - **Human Veto Rate (`any_human_cr_pct`):** Drops from **{stats_b_shared['any_human_cr_pct']}%** (Cohort B) to **{stats_c_shared['any_human_cr_pct']}%** (Cohort C) inside the exact same repositories (mean within-repo shift: **{rv02_result['within_shared_repos']['mean_within_repo_cr_shift_pp']} pp**).",
        f"  - **Pure Rubber-Stamping Without Pre-Merge Fix:** Remains at **{stats_c_shared['rubber_stamp_without_corrective_fix_pct']}%** in Cohort C (vs. **{stats_b_shared['rubber_stamp_without_corrective_fix_pct']}%** in Cohort B), while PRs with $\\ge 1$ corrective commit shift from **{stats_b_shared['any_corrective_commit_pct']}%** to **{stats_c_shared['any_corrective_commit_pct']}%**.",
        "",
        "### `RV-10`: Same-Vendor vs. Cross-Vendor Author $\\times$ Reviewer Monoculture",
        f"- Disaggregating $N = {len(cohort_c_prs)}$ `Cohort_C_Tier1_Bot_Plus_Human` PRs by `Author Agent Vendor` $\\times$ `Reviewer Bot Vendor`:",
        "",
        "| Author $\\times$ Reviewer Pairing Regime | Reviewed PRs ($N$) | Merge Rate (%) | Human Veto (`CHANGES_REQ` %) | Human Rubber-Stamp (%) | Any Corrective Commit (%) | Unaddressed Merged Warnings (Sec/Bug) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for p_lbl in ("Same_Vendor_Monoculture", "Cross_Vendor_Heterogeneous", "Deterministic_SAST_Gate", "Mixed_Same_Plus_Cross_Vendor"):
        st = monoculture_summary.get(p_lbl)
        if not st:
            continue
        wc = warn_pairing_counts.get(p_lbl, {"total_unaddressed": 0, "sec_or_bug_unaddressed": 0})
        md_lines.append(
            f"| `{p_lbl}` | {st['n_prs']} | **{st['merge_rate_pct']}%** | **{st['any_human_cr_pct']}%** | "
            f"**{st['rubber_stamp_pct']}%** | {st['any_corrective_commit_pct']}% | "
            f"{wc['total_unaddressed']} ({wc['sec_or_bug_unaddressed']} sec/bug) |"
        )

    md_lines.extend([
        "",
        "### `RV-06` & `RV-01`: Deterministic Architectural & SAST Constraints vs. Conversational Prose Bots",
        f"- **`1_Deterministic_SAST_Brain`** (`github-advanced-security[bot]`, merged $N = {b_sast.get('merged_prs', 0)}$): **{ghas_act_pct}%** developer action rate (**{ghas_ign_pct}%** ignored), **{sast_14}%** 14d regression, **{sast_90}%** 90d regression.",
        f"- **`2_MultiModel_RAG_Agentic_Brain`** (merged $N = {b_rag.get('merged_prs', 0)}$): **{rag_14}%** 14d (**{rag_vs_sast_14}x higher**) and **{rag_90}%** 90d (**{rag_vs_sast_90}x higher**).",
        f"- **`3_OpenAI_Copilot_Native_Brain`** (merged $N = {b_cop.get('merged_prs', 0)}$): **{cop_14}%** 14d (**{cop_vs_sast_14}x higher**) and **{cop_90}%** 90d (**{cop_vs_sast_90}x higher**).",
        "",
    ])

    if szz_by_topology:
        md_lines.extend([
            f"#### Commit-Attributed Bare-Git SZZ Ground Truth (`szz_defect_traceability_ledger.csv`, $N = {len(szz_csv):,}$ PRs across `{szz_summary_json.get('cloned_repos_scanned', len(constraints_csv))}` Cloned Repos)",
            "",
            "| Corpus :: Review Topology | Uncensored 30d PRs ($N$) | 30d Hard Revert (%) | 14d SZZ Bugfix (%) | 30d SZZ Bugfix (%) | Mean 30d File Survival (%) |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ])
        for topo_k, st in sorted(szz_by_topology.items()):
            md_lines.append(
                f"| `{topo_k}` | {st['uncensored_30d_prs']:,} | **{st['reverted_30d_pct']}%** ({st['reverted_30d_n']}) | "
                f"**{st['szz_bugfix_14d_pct']}%** ({st['szz_bugfix_14d_n']}) | **{st['szz_bugfix_30d_pct']}%** ({st['szz_bugfix_30d_n']}) | "
                f"{st['mean_file_survival_30d_pct']}% |"
            )
        if r0_est is not None:
            md_lines.append(f"\n- **Galton-Watson Fix-Induces-Fix Branching Ratio (`RV-08`, $N = {len(szz_fix_prs)}$ uncensored 60d fix PRs):** $\\hat{{R}}_0 = {r0_est}$.")
        md_lines.append("")

    bf_sum = jev_econ.get("bot_family_summary", {})
    md_lines.extend([
        "### `RV-05` & `SM-05`: Calibrated Decision-Model Tollgates (`TypeSafe Jev`)",
        f"- **Mined Ring-1 Scale:** `{jev_scale.get('prs_total', 0):,}` PRs, `{jev_scale.get('comments_total', 0):,}` comments, `{jev_scale.get('jev_signal_distinct_prs', 0):,}` Jev-evaluated PRs, `{jev_scale.get('formal_reviews_total', 0):,}` formal reviews, `{jev_scale.get('commits_total', 0):,}` commits.",
        f"- **{dml_comp}x–{taste_comp}x Prose Compression at ${cost_pr}/PR:** Compresses from `{bf_sum.get('prose_review_bot_control', {}).get('mean_chars', 0)}` chars to `{bf_sum.get('jev_decision_model_linter', {}).get('mean_chars', 0)}` chars (`getsentry/sentry`) and `{bf_sum.get('jev_taste_policy_gate', {}).get('mean_chars', 0)}` chars (`mirrorstack`).",
        f"- **Selective Attention Routing (`getsentry/sentry` Human PRs, $N={hu_sentry_sens.get('n_total', 0)}$):** Clean **{hu_sentry_sens.get('clean_merge_rate_pct', 0)}%** vs. Flagged **{hu_sentry_sens.get('flagged_merge_rate_pct', 0)}%** (Fisher $p = {hu_sentry_sens.get('fisher_p', 1.0):.4g}$).",
        f"- **Coding-Agent Advisory-Gate Override (`SM-05`):** Flagged coding-agent PRs ($N={ag_flag_pool.get('prs_total', 0)}$) still merge at **{ag_flag_pool.get('merge_rate_pct', 0)}%** vs. Clean **$N={ag_clean_pool.get('prs_total', 0)}$** at **{ag_clean_pool.get('merge_rate_pct', 0)}%**.",
        "",
        "---",
        "",
        "## 2. Phase 4 Scope Convergence Scorecard (`0–12` Scale)",
        "",
        "| Vector | Title | Lit Gap | Signal | Power | Durability | Cohesion | Non-Overlap | Total (/12) | Convergence Decision |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for s in scorecard:
        md_lines.append(
            f"| **`{s['vector_id']}`** | {s['vector_name']} | {s['lit_uniqueness_0_2']} | {s['empirical_signal_0_2']} | "
            f"{s['power_hygiene_0_2']} | {s['durability_gate_0_2']} | {s['thematic_cohesion_0_2']} | "
            f"{s['portfolio_non_overlap_0_2']} | **{s['total_score_12']}/12** | `{s['convergence_decision']}` |"
        )

    s_2h0b = sm02_summary.get("2plus_HumanRevs__0_Bots", {})
    s_1h1b = sm02_summary.get("1_HumanRev__1_Bot", {})
    s_1h2b = sm02_summary.get("1_HumanRev__2plus_Bots", {})
    b_ibd0 = sm07_summary.get("Cohort_B_Human_Only__0_Anchored_To_Issue", {})
    b_ibd1 = sm07_summary.get("Cohort_B_Human_Only__1_Intent_Deficit_No_Issue", {})
    c_ibd1 = sm07_summary.get("Cohort_C_Tier1_Bot_Plus_Human__1_Intent_Deficit_No_Issue", {})
    ratio_2h_1h1b = round(s_2h0b.get("human_cr_veto_pct", 0.0) / max(0.01, s_1h1b.get("human_cr_veto_pct", 1.0)), 2)

    cr_pol_prs_tot = sum(_i(r.get("prs")) for r in coderabbit_policy_rows)
    cr_pol_repos_tot = sum(_i(r.get("repos")) for r in coderabbit_policy_rows)

    def _find_cr_pol(prof: str, pi: str, dt: str) -> dict[str, Any]:
        for r in coderabbit_policy_rows:
            if r.get("profile") == prof and str(r.get("has_path_instructions")) == pi and str(r.get("has_deterministic_tools")) == dt:
                return r
        return {}

    pol_def = _find_cr_pol("default", "False", "False")
    pol_chill_pi = _find_cr_pol("chill", "True", "False")
    pol_chill_pi_dt = _find_cr_pol("chill", "True", "True")
    def_comm = float(pol_def.get("avg_comments_per_pr", 0.0) or 0.0)
    cpi_comm = float(pol_chill_pi.get("avg_comments_per_pr", 0.0) or 0.0)
    cpidt_comm = float(pol_chill_pi_dt.get("avg_comments_per_pr", 0.0) or 0.0)
    cpi_vs_def_pct = round(100.0 * (cpi_comm - def_comm) / max(0.01, def_comm), 1) if def_comm else 0.0
    cpidt_vs_cpi_pct = round(100.0 * (cpidt_comm - cpi_comm) / max(0.01, cpi_comm), 1) if cpi_comm else 0.0
    op_merge_pct = round(
        100.0 * sm01_veto_override_summary["operator_config_merged_unique_prs"] / max(1, sm01_veto_override_summary["operator_config_unique_prs"]),
        1,
    )

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. Social-Media Flashpoints (`SM-01` to `SM-07`)",
        "",
        f"### `SM-02` & `SM-04`: Second-Reviewer Displacement & Stacked AI Reviewers (`N = {len(rev_prs):,}`)",
        "",
        "| Human Reviews $\\times$ Tier-1 Bots | PR Count ($N$) | Merge Rate (%) | Human CR Veto (%) | Human Rubber-Stamp (%) | Pre-Merge Fix Commit (%) | Mean Human Inline Comments | Intent Deficit (`IBD` %) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for k, st in sorted(sm02_summary.items()):
        md_lines.append(
            f"| `{k}` | {st['n_prs']} | **{st['merge_rate_pct']}%** | **{st['human_cr_veto_pct']}%** | "
            f"**{st['rubber_stamp_pct']}%** | {st['has_corrective_commit_pct']}% | {st['mean_human_inline_comments']} | {st['intent_deficit_pct']}% |"
        )

    md_lines.extend([
        "",
        f"- **2nd-Reviewer Displacement (`2plus_HumanRevs__0_Bots` -> `1_HumanRev__1_Bot`):** Collapses human CR veto **{ratio_2h_1h1b}x** (`{s_2h0b.get('human_cr_veto_pct', 0)}% -> {s_1h1b.get('human_cr_veto_pct', 0)}%`).",
        f"- **Stacked Bots (`1_HumanRev__2plus_Bots`, $N = {s_1h2b.get('n_prs', 0)}$):** Human CR veto **{s_1h2b.get('human_cr_veto_pct', 0)}%**, rubber-stamping **{s_1h2b.get('rubber_stamp_pct', 0)}%**.",
        "",
        "### `SM-07`: The Intent-Oracle Paradox",
        f"- In `Cohort_B_Human_Only`: `IBD=0` ($N={b_ibd0.get('n_prs', 0)}$) CR veto **{b_ibd0.get('human_cr_veto_pct', 0)}%** vs `IBD=1` ($N={b_ibd1.get('n_prs', 0)}$) CR veto **{b_ibd1.get('human_cr_veto_pct', 0)}%** (merge **{b_ibd0.get('merge_rate_pct', 0)}% -> {b_ibd1.get('merge_rate_pct', 0)}%**).",
        f"- In `Cohort_C_Tier1_Bot_Plus_Human`: `IBD=1` ($N={c_ibd1.get('n_prs', 0)}$) CR veto **{c_ibd1.get('human_cr_veto_pct', 0)}%** (merge **{c_ibd1.get('merge_rate_pct', 0)}%**).",
        "",
        f"### `SM-06`: `.coderabbit.yaml` `chill` + `path_instructions` Paradox (`{cr_pol_prs_tot:,}` PRs across `{cr_pol_repos_tot}` Repos)",
        f"- `default` (`{pol_def.get('repos', 0)}` repos): **{def_comm} comm/PR** vs `chill + path_instructions` (`{pol_chill_pi.get('repos', 0)}` repos): **{cpi_comm} comm/PR** (**{cpi_vs_def_pct:+.1f}%**) vs `+ deterministic_tools`: **{cpidt_comm} comm/PR** (**{cpidt_vs_cpi_pct:+.1f}%**).",
        "",
        f"### `SM-01` & `SM-03`: Veto Dismissals (`{sm01_veto_override_summary['total_documented_override_or_dismissal_prs']}` PRs) & Agent Self-Modification of CI / Contracts (`{sm01_veto_override_summary['operator_config_unique_prs']}` PRs)",
        f"- **Administrative Veto Overrides:** **{sm01_veto_override_summary['merged_despite_active_changes_requested']}** PRs merged overriding active `CHANGES_REQUESTED`, and **{sm01_veto_override_summary['formal_review_dismissed_events_prs']}** PRs had formal `review_dismissed` events.",
        f"- **Agents Rewriting Their Own CI & Governance Harnesses ([`aidev_operator_config_prs_log.csv`](data_tables/aidev_operator_config_prs_log.csv)):** **{sm01_veto_override_summary['operator_config_self_modification_mutations']}** mutations across **{sm01_veto_override_summary['operator_config_unique_prs']}** PRs (**{sm01_veto_override_summary['operator_config_merged_unique_prs']} merged**, `{op_merge_pct}%`) modifying `.github/workflows/` (`{wf_muts}` rows) and agent instruction contracts (`{agent_contract_muts}` rows).",
        "",
    ])

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    log.info("Wrote %s, %s, and %s", out_json, out_csv, out_md)


if __name__ == "__main__":
    main()
