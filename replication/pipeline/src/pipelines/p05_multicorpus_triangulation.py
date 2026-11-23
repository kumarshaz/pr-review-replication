#!/usr/bin/env python3
"""
Pipeline p05: Multi-Corpus Empirical Triangulation Analysis
===========================================================
Dynamically discovers and executes all dataset handlers in `src/handlers/`,
strictly partitions coding-agent PR corpora from predominantly human GHArchive
firehoses, computes dynamic DevGPT/CodAGE paired joins, reads empirical SZZ
survival from `szz_and_constraints_summary.json`, and excludes CodAGE from
`pooled_silent_gate_prs` (no review columns).

Outputs:
  - results/multi_dataset_triangulation_results.json
  - results/data_tables/multi_dataset_summary_log.csv
"""

from __future__ import annotations

import csv
import datetime
import json
from pathlib import Path
import sys
from typing import Any

import duckdb

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.paths import PathConfig, get_paths
from src.handlers import get_all_dataset_handlers
from src.utils.logging_utils import setup_verbose_logger


def _load_step_json(paths: PathConfig, filename: str) -> dict[str, Any]:
    p = paths.results_dir / filename
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def compute_triangulated_mixed_cohort(
    datasets: dict[str, Any],
    handlers: list[Any],
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
) -> dict[str, Any]:
    """Synthesizes unified cross-corpus triangulation without hardcoded metric literals."""
    msr_json = _load_step_json(paths, "msr_aidev_results.json")
    patch_json = _load_step_json(paths, "raw_patch_and_sociotechnical_results.json")

    # 1. Dynamic PR Acceptance Pooling (coding-agent corpora vs GHArchive firehose)
    pr_handlers = [h for h in handlers if "pr_acceptance" in h.telemetry_capabilities]
    total_agent_prs = 0
    total_agent_merged = 0
    rates_list: list[float] = []
    contributing_pr_breakdown: list[dict[str, Any]] = []
    firehose_total_prs = 0
    firehose_merged_prs = 0
    firehose_breakdown: list[dict[str, Any]] = []

    for h in pr_handlers:
        ds_id = h.dataset_id
        if ds_id not in datasets:
            continue
        ds = datasets[ds_id]
        n = ds.get("sample_size_n")
        m = ds.get("merged_count")
        r = ds.get("merge_rate_pct")

        if n is None and "agent_sample_prs" in ds:
            n = ds["agent_sample_prs"].get("n")
            m = ds["agent_sample_prs"].get("merged_n")
            r = ds["agent_sample_prs"].get("merge_rate_pct")
        elif n is None and "sample_events_n" in ds:
            n = ds.get("sample_events_n")
            m = ds.get("merged_count")
            r = ds.get("macro_merge_rate_pct")

        if n is not None and m is not None:
            calc_rate = round(m * 100.0 / n, 2) if n > 0 else 0.0
            rate_to_record = float(r) if r is not None else calc_rate
            entry = {
                "dataset_id": ds_id,
                "dataset_name": h.dataset_name,
                "sample_size_n": n,
                "merged_count": m,
                "merge_rate_pct": rate_to_record,
            }
            if ds.get("is_all_github_firehose_human_plus_bot"):
                firehose_total_prs += n
                firehose_merged_prs += m
                firehose_breakdown.append(entry)
            else:
                total_agent_prs += n
                total_agent_merged += m
                rates_list.append(rate_to_record)
                contributing_pr_breakdown.append(entry)

    pooled_merge_rate = round(total_agent_merged * 100.0 / total_agent_prs, 2) if total_agent_prs > 0 else 0.0
    min_pr_rate = min(rates_list) if rates_list else 0.0
    max_pr_rate = max(rates_list) if rates_list else 0.0
    firehose_merge_rate = round(firehose_merged_prs * 100.0 / firehose_total_prs, 2) if firehose_total_prs > 0 else 0.0

    d1 = datasets.get("dataset_1_aidev_full", {})
    human_base = d1.get("human_baseline_prs", {})
    human_control_n = int(human_base.get("n", 0))
    human_control_merged = int(human_base.get("merged_n", 0))
    human_control_rate = float(human_base.get("merge_rate_pct", 0.0))

    pooled_pr_acceptance = {
        "total_agent_prs": total_agent_prs,
        "total_agent_merged": total_agent_merged,
        "pooled_merge_rate_pct": pooled_merge_rate,
        "min_rate_pct": min_pr_rate,
        "max_rate_pct": max_pr_rate,
        "human_control_n": human_control_n,
        "human_control_merged": human_control_merged,
        "human_control_merge_rate_pct": human_control_rate,
        "contributing_datasets_count": len(contributing_pr_breakdown),
        "breakdown": contributing_pr_breakdown,
        "macro_github_firehose_pr_acceptance": {
            "note": "Predominantly human all-GitHub GHArchive PR decisions tracked separately from coding-agent corpora.",
            "total_firehose_prs": firehose_total_prs,
            "total_firehose_merged": firehose_merged_prs,
            "pooled_firehose_merge_rate_pct": firehose_merge_rate,
            "breakdown": firehose_breakdown,
        },
    }

    # 2. Execution-Mode Stratified Review Latency Pooling
    lat_handlers = [h for h in handlers if "review_latency" in h.telemetry_capabilities]
    total_prs_with_latency = 0
    turnaround_mins_list: list[float] = []
    latency_breakdown: list[dict[str, Any]] = []

    for h in lat_handlers:
        ds_id = h.dataset_id
        if ds_id not in datasets:
            continue
        ds = datasets[ds_id]
        mins = ds.get("median_turnaround_minutes")
        n = ds.get("sample_size_n")
        if mins is None and "agent_sample_prs" in ds:
            hours = ds["agent_sample_prs"].get("median_merge_hours", 0.0)
            mins = round(hours * 60.0, 1)
            n = ds["agent_sample_prs"].get("n", 0)
        if mins is not None and n is not None:
            total_prs_with_latency += n
            turnaround_mins_list.append(mins)
            latency_breakdown.append({
                "dataset_id": ds_id,
                "dataset_name": h.dataset_name,
                "sample_size_n": n,
                "median_turnaround_minutes": mins,
            })

    min_lat_mins = min(turnaround_mins_list) if turnaround_mins_list else 0.0
    max_lat_mins = max(turnaround_mins_list) if turnaround_mins_list else 0.0
    human_med_hours = float(human_base.get("median_merge_hours", 0.0))
    human_med_mins = round(human_med_hours * 60.0, 2)

    exec_strat = msr_json.get("execution_mode_and_task_stratification", {})
    mode_rows = exec_strat.get("execution_modes", [])
    mode_map = {(m.get("execution_mode"), m.get("agent_family")): m for m in mode_rows}
    mode_i_codex = mode_map.get(("Self-Merged (Mode I)", "Codex"), {})
    mode_i_non_codex = mode_map.get(("Self-Merged (Mode I)", "Non-Codex"), {})
    mode_ii_non_codex = mode_map.get(("Peer-Merged (Mode II)", "Non-Codex"), {})
    mode_ii_codex = mode_map.get(("Peer-Merged (Mode II)", "Codex"), {})

    mode_i_codex_mins = float(mode_i_codex.get("median_merge_minutes", 0.0))
    mode_ii_non_codex_mins = float(mode_ii_non_codex.get("median_merge_minutes", 0.0))
    peer_speedup_ratio = round(human_med_mins / mode_ii_non_codex_mins, 2) if mode_ii_non_codex_mins > 0 else 0.0
    mode_i_speedup_ratio = round(human_med_mins / mode_i_codex_mins, 1) if mode_i_codex_mins > 0 else 0.0

    pooled_review_latency = {
        "total_prs_with_latency": total_prs_with_latency,
        "primary_agent_median_minutes": mode_ii_non_codex_mins,
        "mode_ii_peer_reviewed_non_codex_median_minutes": mode_ii_non_codex_mins,
        "mode_ii_peer_reviewed_non_codex_n": int(mode_ii_non_codex.get("n_prs", 0)),
        "mode_ii_peer_reviewed_codex_median_minutes": float(mode_ii_codex.get("median_merge_minutes", 0.0)),
        "mode_ii_peer_reviewed_codex_n": int(mode_ii_codex.get("n_prs", 0)),
        "mode_i_self_merged_codex_median_minutes": mode_i_codex_mins,
        "mode_i_self_merged_codex_n": int(mode_i_codex.get("n_prs", 0)),
        "mode_i_self_merged_non_codex_median_minutes": float(mode_i_non_codex.get("median_merge_minutes", 0.0)),
        "mode_i_self_merged_non_codex_n": int(mode_i_non_codex.get("n_prs", 0)),
        "peer_reviewed_speedup_vs_human_ratio": peer_speedup_ratio,
        "mode_i_solo_sandbox_speedup_ratio": mode_i_speedup_ratio,
        "min_latency_minutes": min_lat_mins,
        "max_latency_minutes": max_lat_mins,
        "spectrum_summary": f"[{min_lat_mins:.1f} min, {max_lat_mins:.1f} min]",
        "human_control_median_hours": human_med_hours,
        "human_control_n": human_control_n,
        "breakdown": latency_breakdown,
    }

    # 3. Clean Merge Conflicts & Semantic/Test Escape Pooling
    d3 = datasets.get("dataset_3_agenticflict", {})
    af_raw_prs = int(d3.get("total_simulated_prs", 0))
    af_eval_prs = int(d3.get("total_evaluated_prs", d3.get("evaluated_prs", af_raw_prs)))
    af_excl_prs = int(d3.get("excluded_null_rows", d3.get("excluded_unavailable_prs", 0)))
    af_conflicts = int(d3.get("total_conflicts", 0))
    af_eval_rate = float(d3.get("macro_conflict_rate_pct", round(af_conflicts * 100.0 / af_eval_prs, 2) if af_eval_prs else 0.0))
    af_curated = d3.get("curated_100plus_stars_acceleration", [])

    d14 = datasets.get("dataset_14_agentic_prs_mabujadallah", {})
    d14_tq = d14.get("test_quality_agent_vs_human", [])
    d14_agent_tq = next((x for x in d14_tq if x.get("is_agent") is True), {})
    d14_human_tq = next((x for x in d14_tq if x.get("is_agent") is False), {})

    pooled_git_conflicts = {
        "total_prs_evaluated": af_eval_prs,
        "excluded_unavailable_prs": af_excl_prs,
        "raw_total_prs": af_raw_prs,
        "total_conflicts": af_conflicts,
        "pooled_conflict_rate_pct": af_eval_rate,
        "curated_100plus_star_rates_pct": [x.get("conflict_rate_pct") for x in af_curated],
        "semantic_test_escape_triangulation": {
            "agentic_prs_test_quality_n": int(d14.get("test_quality_evaluated_prs", 0)),
            "agent_test_eval_n": int(d14_agent_tq.get("n", 0)),
            "agent_test_adapted_pct": float(d14_agent_tq.get("adapted_pct", 0.0)),
            "human_test_adapted_pct": float(d14_human_tq.get("adapted_pct", 0.0)),
            "agentic_prs_zero_review_join": d14.get("test_quality_zero_review_join", []),
            "aidev_unaddressed_security_bug_bot": patch_json.get("raw_code_patch_analysis", {}).get("unaddressed_warnings_merged_as_is_by_actor", []),
        },
        "simulated_cohort": {"evaluated_prs": af_eval_prs, "raw_prs": af_raw_prs, "conflicts": af_conflicts, "evaluated_rate_pct": af_eval_rate},
    }

    # 4. Dynamic Multi-Turn Fix Churn Pooling
    d4 = datasets.get("dataset_4_devgpt", {})
    dev_fix = d4.get("fix_churn", {})
    dev_prs_cnt = int(dev_fix.get("pr_count", 0))
    dev_avg_commits = float(dev_fix.get("avg_commits_per_pr", 0.0))

    cohorts_json = msr_json.get("human_reviewed_cohorts", {})
    comparisons_json = cohorts_json.get("comparisons", {})
    commit_comp = comparisons_json.get("commit_churn_per_pr", {})
    aid_cohort_c_n = int(cohorts_json.get("cohort_c_tier1_bot_plus_human_n", 0))
    aid_cohort_b_n = int(cohorts_json.get("cohort_b_human_only_n", 0))
    aid_cohort_c_commits = float(commit_comp.get("cohort_c_tier1_bot_plus_human_mean", 0.0))
    aid_cohort_b_commits = float(commit_comp.get("cohort_b_human_only_mean", 0.0))

    d14_n = int(d14.get("sample_size_n", 0))
    d14_add = float(d14.get("avg_additions", 0.0))
    d14_del = float(d14.get("avg_deletions", 0.0))
    d14_files = float(d14.get("avg_changed_files", 0.0))
    af_churn_lines = float(d3.get("avg_conflict_lines", 0.0))

    commit_churn_prs_evaluated = aid_cohort_c_n + dev_prs_cnt
    weighted_commits_sum = (aid_cohort_c_n * aid_cohort_c_commits) + (dev_prs_cnt * dev_avg_commits)
    pooled_avg_commits = round(weighted_commits_sum / commit_churn_prs_evaluated, 2) if commit_churn_prs_evaluated > 0 else aid_cohort_c_commits
    churn_delta_pct = round(((pooled_avg_commits - aid_cohort_b_commits) / aid_cohort_b_commits) * 100.0, 1) if aid_cohort_b_commits > 0 else 0.0

    pooled_fix_churn = {
        "total_prs_evaluated": commit_churn_prs_evaluated,
        "macro_diff_spread_prs_evaluated": d14_n,
        "pooled_agent_commits_per_pr": pooled_avg_commits,
        "human_control_commits_per_pr": aid_cohort_b_commits,
        "human_control_n": aid_cohort_b_n,
        "delta_vs_human_control_pct": churn_delta_pct,
        "aidev_reviewed_cohort": {"prs": aid_cohort_c_n, "avg_commits": aid_cohort_c_commits},
        "aidev_commit_distribution_all": exec_strat.get("commit_distribution", []),
        "devgpt_cohort": {"prs": dev_prs_cnt, "avg_commits": dev_avg_commits},
        "agentic_prs_macro_churn": {
            "prs": d14_n,
            "avg_additions": d14_add,
            "avg_deletions": d14_del,
            "avg_changed_files": d14_files,
        },
        "agentic_prs_merged_vs_rejected_blast_radius": d14.get("merged_vs_rejected_blast_radius", []),
        "agenticflict_simulated_churn_lines": af_churn_lines,
    }

    # 5. Dynamic Defect Survival Pooling (reads empirical SZZ survival from szz_and_constraints_summary.json)
    dev_defect = d4.get("defect_survival", {})
    dev_closed_issues = int(dev_defect.get("closed_issues", 0))
    dev_med_days = float(dev_defect.get("median_resolution_days", 0.0))
    dev_tot_issues = int(dev_defect.get("total_issues", 0))

    patch_logs = patch_json.get("generated_audit_logs", {})
    aid_audit_rows_n = int(patch_logs.get("post_merge_failures_and_reverts_count", 0))
    aid_explicit_reverts_n = int(patch_logs.get("explicit_revert_prs_count", 0))
    aid_genuine_failure_prs_n = int(patch_logs.get("genuine_post_merge_failure_comments_distinct_prs", 0))
    aid_related_issues_n = int(msr_json.get("input_parquet_manifest", {}).get("related_issue.parquet", {}).get("row_count", 0))

    szz_json = _load_step_json(paths, "szz_and_constraints_summary.json")
    szz_surv = szz_json.get("empirical_survival_time_days", {})
    szz_aidev_fix_med = szz_surv.get("aidev_szz_bugfix_median_days")
    szz_aidev_fix_n = int(szz_surv.get("aidev_szz_bugfix_n", 0))
    szz_aidev_rev_med = szz_surv.get("aidev_hard_revert_median_days")
    szz_aidev_rev_n = int(szz_surv.get("aidev_hard_revert_n", 0))

    pm_csv = paths.tables_dir / "post_merge_failures_and_reverts_log.csv"
    pm_comment_med_days = None
    pm_comment_pos_n = 0
    if pm_csv.exists():
        pm_res = con.execute(f"""
            SELECT
                COUNT(*),
                ROUND(MEDIAN(EPOCH(TRY_CAST(incident_timestamp AS TIMESTAMP) - TRY_CAST(merged_at AS TIMESTAMP)) / 86400.0), 2)
            FROM read_csv_auto('{pm_csv}')
            WHERE incident_type = 'Post_Merge_Failure_Comment'
              AND TRY_CAST(incident_timestamp AS TIMESTAMP) >= TRY_CAST(merged_at AS TIMESTAMP)
        """).fetchone()
        if pm_res and pm_res[0]:
            pm_comment_pos_n = int(pm_res[0])
            pm_comment_med_days = float(pm_res[1]) if pm_res[1] is not None else None

    primary_surv_days = (
        float(szz_aidev_fix_med)
        if szz_aidev_fix_med is not None
        else (pm_comment_med_days if pm_comment_med_days is not None else dev_med_days)
    )
    primary_surv_source = (
        f"Commit-attributed AIDev SZZ bugfix median (N={szz_aidev_fix_n:,})"
        if szz_aidev_fix_med is not None
        else (f"AIDev post-merge failure comment median (N={pm_comment_pos_n})" if pm_comment_med_days is not None else "DevGPT issue resolution median")
    )

    total_issues_and_regressions = aid_audit_rows_n + aid_related_issues_n + dev_tot_issues

    pooled_defect_survival = {
        "total_issue_chains_and_regressions": total_issues_and_regressions,
        "post_merge_regressions_n": aid_audit_rows_n,
        "explicit_revert_prs_n": aid_explicit_reverts_n,
        "genuine_post_merge_failure_comment_prs_n": aid_genuine_failure_prs_n,
        "aidev_related_issues_n": aid_related_issues_n,
        "regression_median_survival_days": primary_surv_days,
        "regression_median_survival_source": primary_surv_source,
        "szz_aidev_bugfix_median_days": szz_aidev_fix_med,
        "szz_aidev_bugfix_n": szz_aidev_fix_n,
        "szz_aidev_hard_revert_median_days": szz_aidev_rev_med,
        "szz_aidev_hard_revert_n": szz_aidev_rev_n,
        "post_merge_comment_median_days": pm_comment_med_days,
        "post_merge_comment_positive_n": pm_comment_pos_n,
        "devgpt_closed_issues_n": dev_closed_issues,
        "devgpt_median_resolution_days": dev_med_days,
        "survival_window_spectrum": f"[{min(dev_med_days, primary_surv_days):.2f} days, {max(dev_med_days, primary_surv_days):.2f} days]",
    }

    # 6. Dynamic Macro Stream & Review Events Volume Pooling
    d8 = datasets.get("dataset_8_gharchive_telemetry", {})
    d11 = datasets.get("dataset_11_gharchive_3day_stream", {})
    d13 = datasets.get("dataset_13_gharchive_3month_stream", {})
    d9 = datasets.get("dataset_9_coderabbit_oss_activities", {})

    gha_hourly_events = int(d8.get("total_events_in_hour", 0))
    gha_3day_events = int(d11.get("total_events_3days", 0))
    gha_3month_events = int(d13.get("total_events_3months", 0))
    total_stream_events = gha_hourly_events + gha_3day_events + gha_3month_events

    cr_prs = int(d9.get("total_pull_requests", 0))
    cr_avg_comm = float(d9.get("avg_comments_per_pr", 0.0))
    total_review_stream_volume = (
        d8.get("pull_request_review_events", {}).get("total", 0)
        + d8.get("pull_request_review_comments", {}).get("total", 0)
        + d11.get("review_events", 0)
        + d11.get("inline_comment_events", 0)
        + d13.get("review_events", 0)
        + d13.get("inline_comment_events", 0)
    )

    pooled_review_events_volume = {
        "total_macro_stream_events": total_stream_events,
        "total_stream_review_events": total_review_stream_volume,
        "gharchive_3month_sampling_note": d13.get("sampling_heterogeneity_note", ""),
        "coderabbit_total_prs": cr_prs,
        "coderabbit_avg_comments_per_pr": cr_avg_comm,
        "coderabbit_policy_outcomes": d9.get("policy_outcomes", []),
        "agentic_prs_monitored": d14_n,
        "agentic_prs_avg_comments": d14.get("avg_comments_per_pr", 0.0),
    }

    # 7. Dynamic Cross-Corpus Paired Intra-Repo Matched Control (DevGPT & CodAGE joined to AIDev)
    aidev_paired = msr_json.get("paired_control_summary", {})
    aid_paired_agent_n = int(aidev_paired.get("agent_prs_total", 0))
    aid_paired_agent_m = int(aidev_paired.get("agent_prs_merged", 0))
    aid_paired_hu_n = int(aidev_paired.get("human_prs_total", 0))
    aid_paired_hu_m = int(aidev_paired.get("human_prs_merged", 0))
    aid_paired_repos = int(aidev_paired.get("shared_repos_count", 0))
    aid_paired_penalty = float(aidev_paired.get("paired_merge_penalty_pp", 0.0))

    scratch_aidev = paths.scratch_dir / "aidev"
    hu_by_repo: dict[str, tuple[int, int]] = {}
    hu_pq = scratch_aidev / "human_pull_request.parquet"
    repo_pq = scratch_aidev / "repository.parquet"
    if hu_pq.exists() and repo_pq.exists():
        for rname, tot, mrg in con.execute(f"""
            SELECT LOWER(r.full_name), COUNT(*), SUM(CASE WHEN h.merged_at IS NOT NULL THEN 1 ELSE 0 END)
            FROM read_parquet('{hu_pq}') h
            JOIN read_parquet('{repo_pq}') r ON h.repo_url = r.url
            GROUP BY 1
        """).fetchall():
            hu_by_repo[rname] = (int(tot), int(mrg))

    def _compute_corpus_paired(shared_repo_prs: list[dict[str, Any]]) -> dict[str, Any]:
        sh_repos = 0
        ag_n = ag_m = hu_n = hu_m = 0
        for row in shared_repo_prs or []:
            rn = str(row.get("repo_name", "")).lower()
            if rn in hu_by_repo:
                sh_repos += 1
                ag_n += int(row.get("total_prs", 0))
                ag_m += int(row.get("merged_prs", 0))
                hn, hm = hu_by_repo[rn]
                hu_n += hn
                hu_m += hm
        ag_r = round(100.0 * ag_m / ag_n, 2) if ag_n else 0.0
        hu_r = round(100.0 * hu_m / hu_n, 2) if hu_n else 0.0
        pen = round(ag_r - hu_r, 2) if (ag_n and hu_n) else 0.0
        return {
            "shared_repos": sh_repos,
            "agent_prs": ag_n,
            "agent_merged": ag_m,
            "human_prs": hu_n,
            "human_merged": hu_m,
            "penalty_pp": pen,
        }

    dev_paired_calc = _compute_corpus_paired(d4.get("shared_repo_prs", []))
    d10 = datasets.get("dataset_10_codage_multi_agent_stream", {})
    cod_paired_calc = _compute_corpus_paired(d10.get("shared_repo_prs", []))

    paired_agent_n = aid_paired_agent_n + dev_paired_calc["agent_prs"] + cod_paired_calc["agent_prs"]
    paired_agent_merged = aid_paired_agent_m + dev_paired_calc["agent_merged"] + cod_paired_calc["agent_merged"]
    paired_agent_rate = round(paired_agent_merged * 100.0 / paired_agent_n, 2) if paired_agent_n else 0.0
    paired_hu_n = aid_paired_hu_n
    paired_hu_merged = aid_paired_hu_m
    paired_hu_rate = round(paired_hu_merged * 100.0 / paired_hu_n, 2) if paired_hu_n else 0.0
    pooled_paired_penalty = round(paired_hu_rate - paired_agent_rate, 2)

    pooled_paired_control = {
        "shared_repos_count": aid_paired_repos,
        "pooled_agent_prs": paired_agent_n,
        "pooled_agent_merged": paired_agent_merged,
        "pooled_agent_merge_rate_pct": paired_agent_rate,
        "human_control_prs": paired_hu_n,
        "human_control_merged": paired_hu_merged,
        "human_control_merge_rate_pct": paired_hu_rate,
        "pooled_merge_penalty_pp": pooled_paired_penalty,
        "chi2_stat": float(aidev_paired.get("chi2_stat", 0.0)),
        "odds_ratio": float(aidev_paired.get("odds_ratio", 0.0)),
        "paired_task_type_penalties": exec_strat.get("paired_task_type_penalties", []),
        "paired_language_penalties": exec_strat.get("paired_language_penalties", []),
        "breakdown_by_corpus": {
            "aidev": {"shared_repos": aid_paired_repos, "agent_prs": aid_paired_agent_n, "agent_merged": aid_paired_agent_m, "penalty_pp": -aid_paired_penalty},
            "devgpt": dev_paired_calc,
            "codage": cod_paired_calc,
        },
    }

    # 8. Dynamic Reviewer Fatigue & Comment Density Pooling
    d6 = datasets.get("dataset_6_pre_llm_reviews", {})
    cr_human_comment_chars = float(d6.get("pre_llm_github_reviews", {}).get("avg_comment_chars", 0.0))
    cr_human_tasks = int(d6.get("pre_llm_github_reviews", {}).get("n_samples", 0))
    aidev_reviewed_prs = int(msr_json.get("macro_corpus_summary", {}).get("agentic_prs_with_formal_human_review", 0))
    aidev_char_decay = float(comparisons_json.get("human_review_body_chars", {}).get("relative_shift_pct", 0.0))
    aidev_inline_decay = float(comparisons_json.get("human_inline_comments_per_pr", {}).get("relative_shift_pct", 0.0))
    coderabbit_prs = cr_prs
    coderabbit_avg_comments = cr_avg_comm
    total_reviews_and_prs_fatigue = cr_human_tasks + aidev_reviewed_prs + coderabbit_prs + d14_n

    pooled_reviewer_fatigue = {
        "total_reviews_and_prs_evaluated": total_reviews_and_prs_fatigue,
        "aidev_reviewed_prs": aidev_reviewed_prs,
        "aidev_char_decay_pct": aidev_char_decay,
        "aidev_inline_decay_pct": aidev_inline_decay,
        "coderabbit_total_prs": coderabbit_prs,
        "coderabbit_avg_comments_per_pr": coderabbit_avg_comments,
        "codereviewer_human_tasks": cr_human_tasks,
        "codereviewer_avg_comment_chars": cr_human_comment_chars,
        "agentic_prs_total": d14_n,
        "agentic_prs_avg_comments": d14.get("avg_comments_per_pr", 0.0),
    }

    # 9. Dynamic Supervisory Latency Collapse & Silent Gate Pooling (excludes CodAGE)
    d14_unrev_cnt = int(d14.get("unreviewed_merge_count", 0))
    d14_unrev_pct = float(d14.get("unreviewed_merge_pct", 0.0))
    aid_macro = msr_json.get("macro_corpus_summary", {})
    aid_total_prs = int(aid_macro.get("agentic_prs_total", 0))
    aid_silent_prs = aid_total_prs - aidev_reviewed_prs
    aid_silent_pct = float(aid_macro.get("agentic_prs_bypassing_formal_human_review_pct", 0.0))
    d10_n = int(d10.get("sample_size_n", 0))
    pooled_silent_prs = aid_silent_prs + d14_unrev_cnt
    d12 = datasets.get("dataset_12_live_codebase_pr_cohort", {})

    pooled_supervisory_collapse = {
        "total_agent_prs_latency_monitored": total_prs_with_latency,
        "latency_collapse_ratio": peer_speedup_ratio,
        "mode_i_solo_sandbox_speedup_ratio": mode_i_speedup_ratio,
        "primary_median_turnaround_minutes": mode_ii_non_codex_mins,
        "mode_i_self_merged_codex_median_minutes": mode_i_codex_mins,
        "mode_ii_peer_merged_non_codex_median_minutes": mode_ii_non_codex_mins,
        "human_control_median_hours": human_med_hours,
        "silent_gate_bypass_aidev_pct": aid_silent_pct,
        "codage_review_telemetry_available": False,
        "silent_gate_bypass_agentic_prs_pct": d14_unrev_pct,
        "aidev_mode_i_self_merged_count": int(exec_strat.get("mode_i_self_merged_total", 0)),
        "aidev_mode_ii_peer_merged_count": int(exec_strat.get("mode_ii_peer_merged_total", 0)),
        "pooled_silent_gate_prs": pooled_silent_prs,
        "live_prs_sampled": int(d12.get("sample_size_n", 0)),
        "live_median_turnaround_minutes": float(d12.get("median_turnaround_minutes", 0.0)),
    }

    # 10. Dynamic Conversation Turns & Developer Prompt Typologies Pooling
    d15 = datasets.get("dataset_15_codechat_conversations", {})
    d4_threads = int(sum(e.get("count", 0) for e in d4.get("sharing_links_by_entity", [])))
    if d4_threads == 0:
        d4_threads = int(d4.get("total_sharing_links", 0))
    devgpt_threads = d4_threads
    devgpt_turns = int(d4.get("conversation_turn_metrics", {}).get("total_turns", 0))
    codechat_convs = int(d15.get("total_conversations", 0))
    codechat_turns = int(d15.get("total_turns", 0))

    pooled_conversation_turns = {
        "total_conversational_threads": devgpt_threads + codechat_convs,
        "total_conversational_turns": devgpt_turns + codechat_turns,
        "devgpt": {"threads": devgpt_threads, "turns": devgpt_turns},
        "codechat": {
            "dialogues": codechat_convs,
            "turns": codechat_turns,
            "avg_turns": d15.get("avg_turns_per_conversation", 0.0),
            "human_prompt_len": d15.get("avg_human_prompt_length_chars", 0.0),
            "assistant_resp_len": d15.get("avg_assistant_response_length_chars", 0.0),
        },
    }

    # 11. Dynamic Cross-Module AST Churn & Architectural Spread Pooling
    d7 = datasets.get("dataset_7_swebench_and_polybench", {})
    d7_poly = d7.get("swe_polybench", {})
    poly_n = int(d7_poly.get("n_tasks", 0))
    poly_pct = float(d7_poly.get("cross_cutting_ast_pct", 0.0))
    if not d7_poly:
        poly_n = int(sum(r.get("n_tasks", r.get("tasks", 0)) for r in d7.get("swe_polybench_multilang", [])))
        if poly_pct == 0.0:
            exp_json = _load_step_json(paths, "exploratory_summary.json")
            poly_churn = exp_json.get("swe_polybench_churn", [])
            tot_exp_tasks = sum(int(x.get("tasks", 0)) for x in poly_churn)
            if tot_exp_tasks > 0:
                poly_pct = round(
                    sum(float(x.get("cross_cutting_pct", 0.0)) * int(x.get("tasks", 0)) for x in poly_churn) / tot_exp_tasks,
                    2,
                )
    af_avg_files = float(d3.get("avg_conflict_files", 0.0))
    pooled_cross_module_ast_churn = {
        "total_prs_and_tasks_evaluated": poly_n + af_eval_prs + d14_n,
        "swe_polybench_cross_cutting_pct": poly_pct,
        "agenticflict_avg_conflict_files": af_avg_files,
        "agentic_prs_avg_changed_files": d14_files,
    }

    # 12. Dynamic Boundary & IaC Configuration Mutations Pooling
    aid_cfg_mutations = int(msr_json.get("generated_audit_logs", {}).get("operator_config_pr_path_rows_count", 0))
    pooled_boundary_mutations = {
        "aidev_operator_config_mutations": aid_cfg_mutations,
        "aidev_total_prs": int(d1.get("sample_size_n", aid_total_prs)),
        "coderabbit_verified_repo_configs": int(d9.get("yaml_configs_parsed", 0)),
        "live_prs_sampled": int(d12.get("sample_size_n", 0)),
    }

    # 13. Macro Corpus PR and Event Totals
    total_macro_prs = (
        int(d1.get("sample_size_n", 0))
        + cr_prs
        + d10_n
        + af_eval_prs
        + int(d4.get("sample_size_n", 0))
        + int(d8.get("sample_size_n", 0))
        + int(d11.get("sample_size_n", 0))
        + int(d12.get("sample_size_n", 0))
        + int(d13.get("sample_size_n", 0))
        + d14_n
        + codechat_convs
    )

    macro_corpus_summary = {
        "total_prs_analyzed": total_macro_prs,
        "total_corpora_triangulated": len(datasets),
        "active_handlers_count": len(handlers),
    }

    return {
        "pooled_pr_acceptance": pooled_pr_acceptance,
        "pooled_review_latency": pooled_review_latency,
        "pooled_git_conflicts": pooled_git_conflicts,
        "pooled_fix_churn": pooled_fix_churn,
        "pooled_defect_survival": pooled_defect_survival,
        "pooled_review_events_volume": pooled_review_events_volume,
        "pooled_paired_control": pooled_paired_control,
        "pooled_reviewer_fatigue": pooled_reviewer_fatigue,
        "pooled_supervisory_collapse": pooled_supervisory_collapse,
        "pooled_conversation_turns": pooled_conversation_turns,
        "pooled_cross_module_ast_churn": pooled_cross_module_ast_churn,
        "pooled_boundary_mutations": pooled_boundary_mutations,
        "macro_corpus_summary": macro_corpus_summary,
    }


def run_analysis() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p05_multicorpus_triangulation",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    log.info("Starting Dynamic Multi-Dataset Triangulation Analysis (log=%s)", ts_log)

    con = duckdb.connect()
    handlers = get_all_dataset_handlers(paths=paths)
    log.info("Discovered %d active dataset handlers in src/handlers/", len(handlers))

    results: dict[str, Any] = {
        "metadata": {
            "analysis_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "execution_log": str(ts_log),
            "datasets_analyzed_count": len(handlers),
        },
        "datasets": {},
    }

    summary_rows: list[list[Any]] = []
    for idx, handler in enumerate(handlers, 1):
        log.info("--- [Dataset %d/%d] Analyzing %s (%s) ---", idx, len(handlers), handler.dataset_name, handler.dataset_id)
        try:
            handler_res = handler.execute(con)
            results["datasets"][handler.dataset_id] = handler_res
            summary_row = [idx, handler.dataset_name] + handler.get_summary_row(handler_res)
            summary_rows.append(summary_row)
            log.info("Successfully processed %s", handler.dataset_id)
        except Exception as e:
            log.error("Error executing handler for %s: %s", handler.dataset_id, e, exc_info=True)
            raise

    log.info("Computing synthesized cross-corpus triangulation and mixed cohort metrics...")
    results["triangulated_mixed_cohort"] = compute_triangulated_mixed_cohort(
        results["datasets"], handlers, con, paths
    )
    log.info(
        "Pooled PR Acceptance: %d PRs across %d datasets, pooled rate: %.2f%%",
        results["triangulated_mixed_cohort"]["pooled_pr_acceptance"]["total_agent_prs"],
        results["triangulated_mixed_cohort"]["pooled_pr_acceptance"]["contributing_datasets_count"],
        results["triangulated_mixed_cohort"]["pooled_pr_acceptance"]["pooled_merge_rate_pct"],
    )

    output_json = paths.results_dir / "multi_dataset_triangulation_results.json"
    output_csv = paths.tables_dir / "multi_dataset_summary_log.csv"

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    log.info("Wrote JSON results to %s (bytes=%d)", output_json, output_json.stat().st_size)

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset_index", "dataset_name", "primary_entity", "sample_size_n", "key_metric_1", "key_metric_2", "lemon_market_implication"])
        for row in summary_rows:
            writer.writerow(row)
    log.info("Wrote summary CSV to %s (bytes=%d)", output_csv, output_csv.stat().st_size)
    log.info("Dynamic Multi-Dataset Triangulation complete across all %d datasets!", len(handlers))


if __name__ == "__main__":
    run_analysis()
