#!/usr/bin/env python3
"""
Pipeline p12: Two-Axis Evaluation of Production Jev Decision-Model Tollgates vs. Prose Bots
===========================================================================================
Grounded 100% in real mined repository telemetry (zero synthetic data / zero paid API inference):
  - Mined Production Jev PR Corpus (prefers `results/jev_bot_signals_reparsed.parquet` if
    present from `p00_reparse_jev_offline.py`, falling back to
    `scratch/jev_pr_reviews/jev_bot_signals_and_comments.parquet`).
  - Code Review Bench (`scratch/code_review_bench/`).
  - Qodo PR-Review-Bench (`scratch/qodo_pr_review_bench/`).

Outputs:
  - results/jev_vs_prose_tollgate_results.json
  - results/data_tables/jev_2x2_tollgate_effectiveness_log.csv
  - results/data_tables/jev_top_rules_and_commit_followthrough_log.csv
"""

from __future__ import annotations

from collections import Counter
import csv
import datetime
import json
from pathlib import Path
import sys
from typing import Any

import duckdb
import numpy as np
from scipy import stats

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.bot_catalog import JEV_EXTRA_BOT_LOGINS, sql_in_list
from config.paths import get_paths
from src.utils.logging_utils import setup_verbose_logger
from src.utils.stats_utils import fisher_exact_2x2


def _clean_author_origin_sql(origin_col: str = "p.author_origin", login_col: str = "p.author_login") -> str:
    """Reclassify bot-operated Human_Engineer logins cleanly out of Human_Engineer slices."""
    jev_extra_sql = sql_in_list(b.lower() for b in JEV_EXTRA_BOT_LOGINS)
    bot_cond = (
        f"(LOWER(COALESCE({login_col}, '')) LIKE '%-bot' "
        f"OR LOWER(COALESCE({login_col}, '')) LIKE '%[bot]' "
        f"OR LOWER(COALESCE({login_col}, '')) IN ({jev_extra_sql}))"
    )
    return (
        f"CASE "
        f"WHEN LOWER(COALESCE({login_col}, '')) = 'all-hands-bot' THEN 'Coding_Agent' "
        f"WHEN {origin_col} = 'Human_Engineer' AND {bot_cond} THEN 'Automation_Bot' "
        f"ELSE {origin_col} END"
    )


def _human_actor_filter_sql(login_col: str) -> str:
    """SQL predicate excluding -bot, [bot], and JEV_EXTRA_BOT_LOGINS accounts."""
    jev_extra_sql = sql_in_list(b.lower() for b in JEV_EXTRA_BOT_LOGINS)
    return (
        f"LOWER(COALESCE({login_col}, '')) NOT LIKE '%-bot' "
        f"AND LOWER(COALESCE({login_col}, '')) NOT LIKE '%[bot]' "
        f"AND LOWER(COALESCE({login_col}, '')) NOT IN ({jev_extra_sql})"
    )


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p12_jev_vs_prose_tollgates",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    log.info("Starting 2-Axis Mined Jev Tollgate vs. Prose Review Bot Analysis (log=%s)", ts_log)

    jev_dir = paths.scratch_dir / "jev_pr_reviews"
    crb_dir = paths.scratch_dir / "code_review_bench"

    f_prs = jev_dir / "jev_pull_requests.parquet"
    reparsed_comms = paths.results_dir / "jev_bot_signals_reparsed.parquet"
    raw_comms = jev_dir / "jev_bot_signals_and_comments.parquet"
    if reparsed_comms.exists():
        f_comms = reparsed_comms
        log.info("Using offline-reparsed Jev signals parquet: %s", f_comms)
    else:
        f_comms = raw_comms
        log.info("Using raw mined Jev signals parquet: %s", f_comms)

    f_revs = jev_dir / "jev_formal_reviews.parquet"
    f_commits = jev_dir / "jev_git_commits.parquet"
    f_crb_online = crb_dir / "online_sample.parquet"
    f_crb_t2 = crb_dir / "human_annotations_task2.parquet"

    for req_p in (f_prs, f_comms, f_commits, f_crb_online):
        if not req_p.exists():
            raise FileNotFoundError(f"CRITICAL: Missing required mined parquet file: {req_p}")

    con = duckdb.connect()
    corpus_totals = con.execute(f"""
        SELECT
            (SELECT COUNT(*) FROM read_parquet('{f_prs}')) AS prs_total,
            (SELECT COUNT(*) FROM read_parquet('{f_comms}')) AS comments_total,
            (SELECT COUNT(*) FROM read_parquet('{f_comms}') WHERE is_jev_signal) AS jev_signal_comments,
            (SELECT COUNT(DISTINCT repo_full_name || '#' || CAST(pr_number AS VARCHAR)) FROM read_parquet('{f_comms}') WHERE is_jev_signal) AS jev_signal_distinct_prs,
            (SELECT COUNT(*) FROM read_parquet('{f_commits}')) AS commits_total
    """).fetchone()
    formal_reviews_total = (
        int(con.execute(f"SELECT COUNT(*) FROM read_parquet('{f_revs}')").fetchone()[0])
        if f_revs.exists() else 0
    )

    # AXIS 1A: Attention Footprint, Compression & Cost Economics Across Gate Types
    fam_rows = con.execute(f"""
        SELECT
            bot_family,
            COUNT(*) AS comment_rows,
            COUNT(DISTINCT repo_full_name || '#' || CAST(pr_number AS VARCHAR)) AS distinct_prs,
            ROUND(AVG(comment_chars), 1) AS mean_chars,
            ROUND(MEDIAN(comment_chars), 1) AS median_chars,
            ROUND(AVG(risk_score_normalized), 4) AS mean_risk_score,
            SUM(calls_count) AS total_calls,
            SUM(input_tokens) AS total_tokens,
            ROUND(SUM(cost_usd), 4) AS total_cost_usd
        FROM read_parquet('{f_comms}')
        GROUP BY bot_family
        ORDER BY comment_rows DESC
    """).fetchall()
    fam_summary = {
        r[0]: {
            "comment_rows": int(r[1]),
            "distinct_prs": int(r[2]),
            "mean_chars": float(r[3]),
            "median_chars": float(r[4]),
            "mean_risk_score": float(r[5]) if r[5] is not None else None,
            "total_calls": int(r[6]),
            "total_input_tokens": int(r[7]),
            "total_cost_usd": float(r[8]),
        }
        for r in fam_rows
    }

    dml_chars = fam_summary.get("jev_decision_model_linter", {}).get("mean_chars", 1.0)
    mirrorstack_taste_row = con.execute(f"""
        SELECT ROUND(AVG(comment_chars), 1)
        FROM read_parquet('{f_comms}')
        WHERE repo_full_name = 'mirrorstack-ai/mirrorstack-cli'
          AND bot_family = 'jev_taste_policy_gate'
    """).fetchone()
    taste_chars = (
        float(mirrorstack_taste_row[0])
        if mirrorstack_taste_row and mirrorstack_taste_row[0] is not None
        else fam_summary.get("jev_taste_policy_gate", {}).get("mean_chars", 1.0)
    )
    prose_chars = fam_summary.get("prose_review_bot_control", {}).get("mean_chars", 1.0)
    dml_n = max(1, fam_summary.get("jev_decision_model_linter", {}).get("comment_rows", 1))
    dml_cost_per_pr = round(fam_summary.get("jev_decision_model_linter", {}).get("total_cost_usd", 0.0) / dml_n, 4)
    dml_tokens_per_pr = round(fam_summary.get("jev_decision_model_linter", {}).get("total_input_tokens", 0) / dml_n, 1)
    dml_calls_per_pr = round(fam_summary.get("jev_decision_model_linter", {}).get("total_calls", 0) / dml_n, 1)

    log.info(
        "Axis 1A Economics: ProseBots=%.1f chars | Jev DML=%.1f chars (%.2fx compression) | $%.4f/PR (%.1f calls, %.0f tokens) | Jev TasteGate=%.1f chars (%.2fx)",
        prose_chars, dml_chars, prose_chars / max(1.0, dml_chars), dml_cost_per_pr, dml_calls_per_pr, dml_tokens_per_pr,
        taste_chars, prose_chars / max(1.0, taste_chars),
    )

    clean_origin = _clean_author_origin_sql("p.author_origin", "p.author_login")
    human_comm_filter = _human_actor_filter_sql("c.author_login")
    human_rev_filter = _human_actor_filter_sql("reviewer_login")

    # AXIS 1B: Sentry DML Rule Taxonomy & Commit Follow-Through Compliance
    raw_dml = con.execute(f"""
        SELECT
            c.repo_full_name, c.pr_number, c.created_at AS comment_ts,
            c.overall_verdict, c.alerts_count, c.risk_score_normalized, c.rule_alerts_json,
            c.calls_count, c.input_tokens, c.cost_usd,
            {clean_origin} AS author_origin, p.is_merged, p.html_url
        FROM read_parquet('{f_comms}') c
        JOIN read_parquet('{f_prs}') p
          ON c.repo_full_name = p.repo_full_name AND c.pr_number = p.pr_number
        WHERE c.bot_family = 'jev_decision_model_linter'
    """).fetchall()

    rule_counter: Counter[str] = Counter()
    rule_probs: dict[str, list[float]] = {}
    rule_merged: dict[str, list[int]] = {}
    for row in raw_dml:
        alerts = json.loads(row[6]) if row[6] else []
        for a in alerts:
            rn = a.get("rule_name", "unknown")
            rule_counter[rn] += 1
            rule_probs.setdefault(rn, []).append(float(a.get("prob", 0.0)))
            rule_merged.setdefault(rn, []).append(1 if row[11] else 0)

    top_rules = [
        {
            "rule_name": rn,
            "occurrences": int(cnt),
            "mean_prob": round(float(np.mean(rule_probs[rn])), 3),
            "pr_merge_rate_pct": round(100.0 * float(np.mean(rule_merged[rn])), 1),
        }
        for rn, cnt in rule_counter.most_common(15)
    ]

    followthrough_rows = con.execute(f"""
        WITH dml_prs AS (
            SELECT
                c.repo_full_name, c.pr_number,
                MIN(try_cast(c.created_at AS TIMESTAMPTZ)) AS first_jev_ts,
                MAX(c.alerts_count) AS max_alerts,
                {clean_origin} AS author_origin, p.is_merged, p.html_url
            FROM read_parquet('{f_comms}') c
            JOIN read_parquet('{f_prs}') p
              ON c.repo_full_name = p.repo_full_name AND c.pr_number = p.pr_number
            WHERE c.bot_family = 'jev_decision_model_linter'
            GROUP BY 1, 2, 5, 6, 7
        ),
        joined_cm AS (
            SELECT
                d.repo_full_name, d.pr_number, d.author_origin, d.is_merged, d.html_url,
                CASE WHEN d.max_alerts > 0 THEN 'Flagged_Rule_Warning' ELSE 'Clean_No_Warning' END AS j_tier,
                COUNT(cm.sha) AS total_commits,
                SUM(CASE WHEN try_cast(cm.committed_at AS TIMESTAMPTZ) > d.first_jev_ts THEN 1 ELSE 0 END) AS commits_after_jev
            FROM dml_prs d
            JOIN read_parquet('{f_commits}') cm
              ON d.repo_full_name = cm.repo_full_name AND d.pr_number = CAST(cm.pr_number AS BIGINT)
            GROUP BY 1, 2, 3, 4, 5, 6
        )
        SELECT
            j_tier,
            author_origin,
            COUNT(*) AS prs_with_commit_timeline,
            ROUND(AVG(total_commits), 2) AS avg_total_commits,
            ROUND(AVG(commits_after_jev), 2) AS avg_commits_after_jev,
            ROUND(100.0 * AVG(CASE WHEN commits_after_jev > 0 THEN 1.0 ELSE 0.0 END), 2) AS pct_with_post_jev_followup_commit,
            ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct
        FROM joined_cm
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).fetchall()

    followthrough_list = [
        {
            "verdict_tier": r[0],
            "author_origin": r[1],
            "prs_with_commit_timeline": int(r[2]),
            "avg_total_commits": float(r[3]),
            "avg_commits_after_jev": float(r[4]),
            "pct_with_post_jev_followup_commit": float(r[5]),
            "merge_rate_pct": float(r[6]),
        }
        for r in followthrough_rows
    ]

    mirrorstack_breakdown = con.execute(f"""
        SELECT
            CASE
                WHEN lower(body_excerpt) LIKE '%needs a human%' THEN 'Escalated_Needs_Human'
                WHEN overall_verdict = 'PASS' THEN 'Auto_Passed_Clean'
                WHEN overall_verdict = 'FAIL' THEN 'Blocked_Fail'
                ELSE 'Other_Decision'
            END AS gate_outcome,
            COUNT(*) AS comment_cnt,
            COUNT(DISTINCT repo_full_name || '#' || CAST(pr_number AS VARCHAR)) AS prs_cnt,
            ROUND(AVG(comment_chars), 1) AS avg_chars
        FROM read_parquet('{f_comms}')
        WHERE repo_full_name = 'mirrorstack-ai/mirrorstack-cli'
          AND bot_family = 'jev_taste_policy_gate'
        GROUP BY 1 ORDER BY comment_cnt DESC
    """).fetchall()

    # AXIS 1C & AXIS 2: 2x2 Intra-Repo Factorial Matrix (Review Gate x Author Origin)
    def run_2x2_query(where_clause: str, scope_label: str) -> list[dict[str, Any]]:
        rows = con.execute(f"""
            WITH p_sig AS (
                SELECT
                    p.repo_full_name,
                    p.pr_number,
                    {clean_origin} AS author_origin,
                    p.is_merged,
                    p.state,
                    date_diff('minute', try_cast(p.created_at AS TIMESTAMPTZ),
                              try_cast(coalesce(nullif(p.merged_at,''), nullif(p.closed_at,'')) AS TIMESTAMPTZ)) AS dur_mins,
                    MAX(CASE WHEN c.is_jev_signal THEN 1 ELSE 0 END) AS has_jev,
                    MAX(CASE WHEN c.is_jev_signal AND c.alerts_count > 0 THEN 1 ELSE 0 END) AS jev_flagged,
                    MAX(CASE WHEN c.bot_family = 'prose_review_bot_control' THEN 1 ELSE 0 END) AS has_prose,
                    SUM(CASE WHEN c.bot_family = 'human_comment' AND {human_comm_filter} THEN 1 ELSE 0 END) AS human_comms,
                    AVG(CASE WHEN c.is_jev_signal THEN c.risk_score_normalized END) AS jev_risk,
                    AVG(CASE WHEN c.is_jev_signal THEN c.alerts_count END) AS jev_alerts
                FROM read_parquet('{f_prs}') p
                LEFT JOIN read_parquet('{f_comms}') c
                  ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
                WHERE {clean_origin} IN ('Coding_Agent', 'Human_Engineer')
                  AND {where_clause}
                GROUP BY 1, 2, 3, 4, 5, 6
            )
            SELECT
                author_origin,
                CASE
                    WHEN has_jev = 1 AND jev_flagged = 1 THEN '1_Jev_Flagged'
                    WHEN has_jev = 1 AND jev_flagged = 0 THEN '2_Jev_Clean'
                    WHEN has_prose = 1 THEN '3_Prose_Bot_Control'
                    ELSE '4_No_Bot_Control'
                END AS gate_regime,
                COUNT(*) AS prs_total,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_prs,
                ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
                ROUND(100.0 * AVG(CASE WHEN human_comms > 0 THEN 1.0 ELSE 0.0 END), 2) AS pct_with_human_comm,
                ROUND(AVG(human_comms), 2) AS mean_human_comms,
                ROUND(MEDIAN(dur_mins), 1) AS median_duration_mins,
                ROUND(AVG(jev_risk), 3) AS mean_jev_risk_score
            FROM p_sig
            GROUP BY 1, 2
            ORDER BY 1, 2
        """).fetchall()
        return [
            {
                "scope": scope_label,
                "author_origin": r[0],
                "gate_regime": r[1],
                "prs_total": int(r[2]),
                "merged_prs": int(r[3]),
                "merge_rate_pct": float(r[4]),
                "pct_with_human_comm": float(r[5]),
                "mean_human_comms": float(r[6]),
                "median_duration_mins": float(r[7]) if r[7] is not None else 0.0,
                "mean_jev_risk_score": float(r[8]) if r[8] is not None else None,
            }
            for r in rows
        ]

    sentry_2x2 = run_2x2_query("p.repo_full_name = 'getsentry/sentry'", "getsentry/sentry_paired_control")
    all_active_2x2 = run_2x2_query(
        f"p.repo_full_name IN (SELECT DISTINCT repo_full_name FROM read_parquet('{f_comms}') WHERE is_jev_signal)",
        "all_jev_active_repos_pooled",
    )

    sentry_dml_individual = con.execute(f"""
        WITH p_sig AS (
            SELECT
                p.pr_number, {clean_origin} AS author_origin, p.is_merged,
                MAX(c.risk_score_normalized) AS risk_score,
                MAX(c.alerts_count) AS alerts
            FROM read_parquet('{f_prs}') p
            JOIN read_parquet('{f_comms}') c
              ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
            WHERE p.repo_full_name = 'getsentry/sentry'
              AND c.bot_family = 'jev_decision_model_linter'
              AND {clean_origin} IN ('Coding_Agent', 'Human_Engineer')
            GROUP BY 1, 2, 3
        )
        SELECT author_origin, is_merged, risk_score, alerts FROM p_sig
    """).fetchall()

    hu_rows = [r for r in sentry_dml_individual if r[0] == "Human_Engineer"]
    ag_rows = [r for r in sentry_dml_individual if r[0] == "Coding_Agent"]

    def flag_vs_clean_stats(sub: list) -> dict[str, Any]:
        fl = [r for r in sub if r[3] > 0]
        cl = [r for r in sub if r[3] == 0]
        fl_m = sum(1 for r in fl if r[1])
        cl_m = sum(1 for r in cl if r[1])
        fl_rate = round(100.0 * fl_m / max(1, len(fl)), 2)
        cl_rate = round(100.0 * cl_m / max(1, len(cl)), 2)
        p_fisher = fisher_exact_2x2(cl_m, len(cl), fl_m, len(fl)) if fl and cl else 1.0
        rho_risk, p_rho = stats.spearmanr([r[2] for r in sub], [1 if r[1] else 0 for r in sub]) if len(sub) >= 5 else (0.0, 1.0)
        return {
            "n_total": len(sub),
            "flagged_n": len(fl),
            "flagged_rate_pct": round(100.0 * len(fl) / max(1, len(sub)), 2),
            "clean_n": len(cl),
            "clean_merge_rate_pct": cl_rate,
            "flagged_merge_rate_pct": fl_rate,
            "clean_minus_flagged_pp": round(cl_rate - fl_rate, 2),
            "fisher_p": float(p_fisher),
            "risk_vs_merged_spearman_rho": round(float(rho_risk), 4) if not np.isnan(rho_risk) else 0.0,
            "risk_vs_merged_spearman_p": float(p_rho) if not np.isnan(p_rho) else 1.0,
        }

    sentry_agent_vs_human_dml = {
        "Human_Engineer": flag_vs_clean_stats(hu_rows),
        "Coding_Agent": flag_vs_clean_stats(ag_rows),
    }

    sesh_risk_rows = con.execute(f"""
        WITH s_prs AS (
            SELECT
                p.repo_full_name,
                p.pr_number, {clean_origin} AS author_origin, p.is_merged,
                AVG(CASE WHEN c.bot_family = 'jev_pr_risk_histogram' THEN c.risk_score_normalized ELSE NULL END) AS risk_score,
                AVG(CASE WHEN c.bot_family = 'jev_pr_risk_histogram' THEN c.jev_confidence ELSE NULL END) AS jev_conf,
                MAX(CASE WHEN c.bot_family = 'jev_pr_risk_histogram' THEN c.alerts_count ELSE 0 END) AS flagged,
                SUM(CASE WHEN c.bot_family = 'human_comment' AND {human_comm_filter} THEN 1 ELSE 0 END) AS human_comms
            FROM read_parquet('{f_prs}') p
            JOIN read_parquet('{f_comms}') c
              ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
            GROUP BY 1, 2, 3, 4
            HAVING MAX(CASE WHEN c.bot_family = 'jev_pr_risk_histogram' THEN 1 ELSE 0 END) = 1
        )
        SELECT author_origin, flagged > 0 AS low_conf_flagged, count(*),
               round(avg(risk_score), 3), round(avg(jev_conf), 3),
               round(avg(human_comms), 2), round(100.0*avg(CASE WHEN is_merged THEN 1 ELSE 0 END), 1)
        FROM s_prs GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()

    # AXIS 2B: SM-05 Advisory-Gate Override Analysis
    sm05_advisory_override: dict[str, Any] = {}
    if f_revs.exists():
        sm05_rows = con.execute(f"""
            WITH jev_prs AS (
                SELECT
                    p.repo_full_name,
                    p.pr_number,
                    {clean_origin} AS author_origin,
                    p.is_merged,
                    MAX(CASE WHEN c.is_jev_signal AND c.alerts_count > 0 THEN 1 ELSE 0 END) AS jev_flagged,
                    SUM(CASE WHEN c.bot_family = 'human_comment' AND {human_comm_filter} THEN 1 ELSE 0 END) AS human_comms
                FROM read_parquet('{f_prs}') p
                JOIN read_parquet('{f_comms}') c
                  ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
                WHERE {clean_origin} IN ('Coding_Agent', 'Human_Engineer')
                GROUP BY 1, 2, 3, 4
                HAVING MAX(CASE WHEN c.is_jev_signal THEN 1 ELSE 0 END) = 1
            ),
            h_revs AS (
                SELECT
                    repo_full_name,
                    pr_number,
                    COUNT(*) AS human_formal_revs,
                    SUM(CASE WHEN state = 'APPROVED' THEN 1 ELSE 0 END) AS human_approvals,
                    SUM(CASE WHEN state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS human_cr
                FROM read_parquet('{f_revs}')
                WHERE reviewer_type = 'User'
                  AND {human_rev_filter}
                GROUP BY 1, 2
            ),
            joined AS (
                SELECT
                    j.*,
                    COALESCE(hr.human_formal_revs, 0) AS human_formal_revs,
                    COALESCE(hr.human_approvals, 0) AS human_approvals,
                    COALESCE(hr.human_cr, 0) AS human_cr,
                    CASE
                        WHEN COALESCE(hr.human_formal_revs, 0) > 0 THEN 'Has_Human_Formal_Review'
                        ELSE 'Zero_Human_Formal_Review'
                    END AS review_presence
                FROM jev_prs j
                LEFT JOIN h_revs hr
                  ON j.repo_full_name = hr.repo_full_name AND j.pr_number = hr.pr_number
            )
            SELECT
                author_origin,
                CASE WHEN jev_flagged = 1 THEN '1_Jev_Flagged' ELSE '2_Jev_Clean' END AS jev_tier,
                review_presence,
                COUNT(*) AS prs_n,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_n,
                ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
                SUM(CASE WHEN human_cr > 0 THEN 1 ELSE 0 END) AS human_cr_n,
                ROUND(100.0 * AVG(CASE WHEN human_cr > 0 THEN 1.0 ELSE 0.0 END), 2) AS human_cr_pct,
                SUM(CASE WHEN human_comms = 0 THEN 1 ELSE 0 END) AS zero_human_comm_n
            FROM joined
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        """).fetchall()
        sm05_breakdown = [
            {
                "author_origin": r[0],
                "jev_tier": r[1],
                "review_presence": r[2],
                "prs_n": int(r[3]),
                "merged_n": int(r[4]),
                "merge_rate_pct": float(r[5]),
                "human_cr_n": int(r[6]),
                "human_cr_pct": float(r[7]),
                "zero_human_comm_n": int(r[8]),
            }
            for r in sm05_rows
        ]
        sm05_totals = con.execute(f"""
            WITH jev_prs AS (
                SELECT
                    p.repo_full_name, p.pr_number, {clean_origin} AS author_origin, p.is_merged,
                    MAX(CASE WHEN c.alerts_count > 0 THEN 1 ELSE 0 END) AS jev_flagged
                FROM read_parquet('{f_prs}') p
                JOIN read_parquet('{f_comms}') c
                  ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
                WHERE c.is_jev_signal AND {clean_origin} IN ('Coding_Agent', 'Human_Engineer')
                GROUP BY 1, 2, 3, 4
            )
            SELECT
                author_origin,
                CASE WHEN jev_flagged = 1 THEN '1_Jev_Flagged' ELSE '2_Jev_Clean' END AS jev_tier,
                COUNT(*) AS prs_n,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_n,
                ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct
            FROM jev_prs
            GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchall()
        sm05_advisory_override = {
            "formal_reviews_mined_total": formal_reviews_total,
            "by_origin_verdict_and_review_presence": sm05_breakdown,
            "pooled_totals": [
                {"author_origin": r[0], "jev_tier": r[1], "prs_n": int(r[2]), "merged_n": int(r[3]), "merge_rate_pct": float(r[4])}
                for r in sm05_totals
            ],
        }

    # AXIS 1D: Code Review Bench (15 Prose Bots) & Human Quality Ceiling
    crb_tools = con.execute(f"""
        SELECT
            tool,
            COUNT(*) AS n_prs,
            ROUND(AVG(precision), 4) AS precision,
            ROUND(AVG(recall), 4) AS recall,
            ROUND(AVG(f1), 4) AS f1,
            ROUND(AVG(diff_lines), 1) AS avg_diff_lines
        FROM read_parquet('{f_crb_online}')
        GROUP BY tool
        ORDER BY f1 DESC, n_prs DESC
    """).fetchall()
    crb_size_decay = con.execute(f"""
        SELECT
            COALESCE(size_bucket, 'unknown') AS size_bucket,
            COUNT(*) AS n_prs,
            ROUND(AVG(precision), 4) AS precision,
            ROUND(AVG(recall), 4) AS recall,
            ROUND(AVG(f1), 4) AS f1
        FROM read_parquet('{f_crb_online}')
        GROUP BY 1
        ORDER BY AVG(diff_lines) ASC
    """).fetchall()
    crb_t2 = con.execute(f"""
        SELECT
            COUNT(*) AS n,
            ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_factual_accuracy, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2),
            ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_relevant_to_pr, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2),
            ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_actionable, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2)
        FROM read_parquet('{f_crb_t2}')
    """).fetchone()

    out_json = paths.results_dir / "jev_vs_prose_tollgate_results.json"
    out_2x2_csv = paths.tables_dir / "jev_2x2_tollgate_effectiveness_log.csv"
    out_rules_csv = paths.tables_dir / "jev_top_rules_and_commit_followthrough_log.csv"

    with open(out_2x2_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "scope", "author_origin", "gate_regime", "prs_total", "merged_prs",
            "merge_rate_pct", "pct_with_human_comm", "mean_human_comms",
            "median_duration_mins", "mean_jev_risk_score",
        ])
        for rec in sentry_2x2 + all_active_2x2:
            w.writerow([
                rec["scope"], rec["author_origin"], rec["gate_regime"], rec["prs_total"],
                rec["merged_prs"], rec["merge_rate_pct"], rec["pct_with_human_comm"],
                rec["mean_human_comms"], rec["median_duration_mins"], rec["mean_jev_risk_score"] or "",
            ])

    with open(out_rules_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table_type", "label", "secondary", "n", "metric_1", "metric_2", "metric_3"])
        for r in top_rules:
            w.writerow(["sentry_dml_rule", r["rule_name"], "", r["occurrences"], r["mean_prob"], r["pr_merge_rate_pct"], ""])
        for r in followthrough_list:
            w.writerow(["sentry_commit_followthrough", r["verdict_tier"], r["author_origin"], r["prs_with_commit_timeline"], r["pct_with_post_jev_followup_commit"], r["avg_commits_after_jev"], r["merge_rate_pct"]])
        for r in mirrorstack_breakdown:
            w.writerow(["mirrorstack_taste_gate", r[0], "", r[1], r[2], r[3], ""])
        for r in crb_tools:
            w.writerow(["code_review_bench_tool", r[0], "", r[1], r[2], r[3], r[4]])

    results = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "comms_parquet_source": str(f_comms),
        "data_integrity": "100% mined public GitHub PR/commit/review telemetry + CodeReviewBench + Qodo (0 paid inference calls, 0 synthetic rows)",
        "mined_corpus_scale": {
            "prs_total": int(corpus_totals[0]),
            "comments_total": int(corpus_totals[1]),
            "jev_signal_comments": int(corpus_totals[2]),
            "jev_signal_distinct_prs": int(corpus_totals[3]),
            "formal_reviews_total": formal_reviews_total,
            "commits_total": int(corpus_totals[4]),
        },
        "axis1_attention_and_cost_economics": {
            "bot_family_summary": fam_summary,
            "prose_to_sentry_dml_char_compression_ratio": round(prose_chars / max(1.0, dml_chars), 2),
            "prose_to_mirrorstack_taste_compression_ratio": round(prose_chars / max(1.0, taste_chars), 2),
            "sentry_dml_calls_per_pr": dml_calls_per_pr,
            "sentry_dml_input_tokens_per_pr": dml_tokens_per_pr,
            "sentry_dml_cost_per_pr_usd": dml_cost_per_pr,
        },
        "axis1_rule_taxonomy_and_followthrough": {
            "top_sentry_dml_rules": top_rules,
            "sentry_commit_followthrough": followthrough_list,
            "mirrorstack_gate_outcomes": [
                {"outcome": r[0], "comments": int(r[1]), "prs": int(r[2]), "avg_chars": float(r[3])}
                for r in mirrorstack_breakdown
            ],
        },
        "axis1_and_axis2_2x2_evaluation": {
            "sentry_paired_control_2x2": sentry_2x2,
            "all_jev_active_repos_2x2": all_active_2x2,
            "sentry_dml_agent_vs_human_sensitivity": sentry_agent_vs_human_dml,
            "pr_risk_histogram_scope_note": "All jev_pr_risk_histogram adopter repos",
            "sesh_pr_risk_agent_vs_human": [
                {
                    "author_origin": r[0], "low_conf_flagged": bool(r[1]), "prs": int(r[2]),
                    "mean_risk_score": float(r[3]), "mean_jev_confidence": float(r[4]),
                    "mean_human_comms": float(r[5]), "merge_rate_pct": float(r[6]),
                    "scope_note": "All jev_pr_risk_histogram adopter repos",
                }
                for r in sesh_risk_rows
            ],
            "sm05_advisory_gate_override": sm05_advisory_override,
        },
        "axis1_multi_tool_prose_ceiling_code_review_bench": {
            "online_bot_prs": sum(int(r[1]) for r in crb_tools),
            "n_tools": len(crb_tools),
            "best_f1_tool": {"tool": crb_tools[0][0], "f1": float(crb_tools[0][4]), "precision": float(crb_tools[0][2]), "recall": float(crb_tools[0][3])},
            "worst_f1_tool": {"tool": crb_tools[-1][0], "f1": float(crb_tools[-1][4]), "precision": float(crb_tools[-1][2]), "recall": float(crb_tools[-1][3])},
            "tools": [
                {"tool": r[0], "n_prs": int(r[1]), "precision": float(r[2]), "recall": float(r[3]), "f1": float(r[4]), "avg_diff_lines": float(r[5])}
                for r in crb_tools
            ],
            "by_size_bucket": [
                {"size_bucket": r[0], "n_prs": int(r[1]), "precision": float(r[2]), "recall": float(r[3]), "f1": float(r[4])}
                for r in crb_size_decay
            ],
            "human_annotations_task2": {
                "n_audited_comments": int(crb_t2[0]),
                "factual_accuracy_yes_pct": float(crb_t2[1]),
                "relevant_to_pr_yes_pct": float(crb_t2[2]),
                "actionable_yes_pct": float(crb_t2[3]),
            },
        },
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    log.info("Sentry 2x2 Coding_Agent DML sensitivity: %s", json.dumps(sentry_agent_vs_human_dml["Coding_Agent"]))
    log.info("Sentry 2x2 Human_Engineer DML sensitivity: %s", json.dumps(sentry_agent_vs_human_dml["Human_Engineer"]))
    log.info("CodeReviewBench Human Task2 (N=%d): factual=%.2f%%, relevant=%.2f%%, actionable=%.2f%%",
             crb_t2[0], crb_t2[1], crb_t2[2], crb_t2[3])
    log.info("Wrote %s, %s, and %s", out_json, out_2x2_csv, out_rules_csv)


if __name__ == "__main__":
    main()
