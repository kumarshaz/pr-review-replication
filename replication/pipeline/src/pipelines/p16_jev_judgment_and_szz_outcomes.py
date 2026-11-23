#!/usr/bin/env python3
"""
Pipeline 16: Deep Study of Jev Decision-Model Tollgates on Human Judgment (NQ-01)
and Commit-Attributed Bare-Git SZZ Post-Release Defect Outcomes (NQ-02).

100% grounded in real on-disk Parquet, CSV, and bare-git SZZ ledgers.
Zero GitHub API token required, zero fabricated metrics, zero silent defaults.

Outputs:
  - paths.results_dir / "jev_judgment_and_szz_outcomes.json"
  - paths.tables_dir / "jev_szz_within_repo_outcomes_log.csv"
  - paths.tables_dir / "jev_verbosity_vs_human_judgment_log.csv"
  - paths.results_dir / "JEV_JUDGMENT_AND_SZZ_REPORT.md"
"""

from __future__ import annotations

import csv
import datetime
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from scipy import stats

_PR_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
if str(_PR_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_PR_ANALYSIS_ROOT))

from config.bot_catalog import (  # noqa: E402
    DETERMINISTIC_SAST_BOTS,
    EXCLUDED_AUTHOR_BOT_ACTORS,
    JEV_EXTRA_BOT_LOGINS,
    TIER1_PR_COMMENTS_BOTS,
    TIER1_REVIEW_BOTS,
    clean_jev_author_origin_sql,
    sql_in_list,
)
from config.paths import PathConfig, get_paths  # noqa: E402
from src.utils.logging_utils import setup_verbose_logger  # noqa: E402
from src.utils.stats_utils import (  # noqa: E402
    bh_fdr,
    fisher_exact_2x2,
    two_prop_z_test,
    wilson_ci,
    yaml_frontmatter,
)

HYDRATED_JEV_REPOS: tuple[str, ...] = (
    "getsentry/sentry",
    "craftmilldev/loopway",
    "craftmilldev/sesh",
)

# All canonical + rescued Jev decision-model families and deterministic/prose controls
PRIMARY_BOT_FAMILIES: tuple[str, ...] = (
    "jev_decision_model_linter",
    "jev_pr_risk_histogram",
    "jev_taste_policy_gate",
    "jev_review_router",
    "jev_council_architect_review",
    "jev_loop_review_gate",
    "jev_way_of_working_advisor",
    "deterministic_merge_gate",
    "static_sast_bot_control",
    "prose_review_bot_control",
)


def _clean_author_origin_sql(origin_col: str, login_col: str) -> str:
    """Reclassify bot-operated Human_Engineer logins cleanly out of Human_Engineer slices."""
    return clean_jev_author_origin_sql(author_login_col=login_col, author_origin_col=origin_col)


def _human_actor_sql(col: str) -> str:
    excluded = sorted(
        {b.lower() for b in EXCLUDED_AUTHOR_BOT_ACTORS}
        | {b.lower() for b in JEV_EXTRA_BOT_LOGINS}
        | {b.lower() for b in TIER1_REVIEW_BOTS}
        | {b.lower() for b in DETERMINISTIC_SAST_BOTS}
    )
    in_clause = sql_in_list(excluded)
    return (
        f"LOWER(COALESCE({col}, '')) NOT LIKE '%[bot]' "
        f"AND LOWER(COALESCE({col}, '')) NOT LIKE '%-bot' "
        f"AND LOWER(COALESCE({col}, '')) NOT IN ({in_clause})"
    )


def _wilson_pct(k: int, n: int) -> list[float]:
    lo, hi = wilson_ci(int(k), int(n))
    return [round(100.0 * lo, 2), round(100.0 * hi, 2)]


def _safe_rate(k: int, n: int) -> float:
    return round(100.0 * k / n, 2) if n > 0 else 0.0


def _csv_columns(con: duckdb.DuckDBPyConnection, csv_path: Path) -> set[str]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{csv_path.as_posix()}', header=true)"
    ).fetchall()
    return {str(r[0]) for r in rows}


def _mantel_haenszel(strata: list[tuple[str, int, int, int, int]]) -> dict[str, Any]:
    """
    Compute Mantel-Haenszel pooled Odds Ratio, Robins-Breslow-Greenland 95% CI,
    Cochran-Mantel-Haenszel chi2 p-value, and N-weighted risk difference (pp)
    across matched intra-repo strata: (repo, k_treat, n_treat, k_ctrl, n_ctrl).
    """
    valid = [s for s in strata if s[2] > 0 and s[4] > 0]
    if not valid:
        return {
            "matched_repos_count": 0,
            "matched_repos": [],
            "treat_k": 0,
            "treat_n": 0,
            "ctrl_k": 0,
            "ctrl_n": 0,
            "or_mh": None,
            "or_ci95": None,
            "cmh_chi2": None,
            "cmh_p_value": None,
            "weighted_diff_pp": None,
        }

    num_or = 0.0
    den_or = 0.0
    sum_p_r = 0.0
    sum_p_s = 0.0
    sum_q_r = 0.0
    sum_q_s = 0.0
    cmh_num = 0.0
    cmh_var = 0.0
    wt_diff_num = 0.0
    wt_diff_den = 0.0

    tot_kt, tot_nt, tot_kc, tot_nc = 0, 0, 0, 0
    for _repo, kt, nt, kc, nc in valid:
        tot_kt += kt
        tot_nt += nt
        tot_kc += kc
        tot_nc += nc

        a = float(kt)
        b = float(nt - kt)
        c = float(kc)
        d = float(nc - kc)
        t = float(nt + nc)
        if t <= 1.0:
            continue

        r_i = (a * d) / t
        s_i = (b * c) / t
        num_or += r_i
        den_or += s_i

        p_i = (a + d) / t
        q_i = (b + c) / t
        sum_p_r += p_i * r_i
        sum_p_s += p_i * s_i
        sum_q_r += q_i * r_i
        sum_q_s += q_i * s_i

        m1 = a + c
        m0 = b + d
        exp_a = nt * m1 / t
        var_a = (nt * nc * m1 * m0) / (t * t * (t - 1.0))
        cmh_num += a - exp_a
        cmh_var += var_a

        w_i = (nt * nc) / t
        wt_diff_num += w_i * ((a / nt) - (c / nc))
        wt_diff_den += w_i

    or_mh = None
    or_ci95 = None
    if num_or > 0.0 and den_or > 0.0:
        or_mh = round(num_or / den_or, 4)
        var_log_or = (
            sum_p_r / (2.0 * num_or * num_or)
            + (sum_p_s + sum_q_r) / (2.0 * num_or * den_or)
            + sum_q_s / (2.0 * den_or * den_or)
        )
        se_log = math.sqrt(max(0.0, var_log_or))
        log_or = math.log(or_mh)
        or_ci95 = [
            round(math.exp(log_or - 1.96 * se_log), 4),
            round(math.exp(log_or + 1.96 * se_log), 4),
        ]

    cmh_chi2 = None
    cmh_p = None
    if cmh_var > 0.0:
        cmh_chi2 = round((cmh_num * cmh_num) / cmh_var, 4)
        cmh_p = float(stats.chi2.sf(cmh_chi2, df=1))

    weighted_diff_pp = (
        round(100.0 * wt_diff_num / wt_diff_den, 2) if wt_diff_den > 0.0 else None
    )

    return {
        "matched_repos_count": len(valid),
        "matched_repos": [s[0] for s in valid],
        "treat_k": int(tot_kt),
        "treat_n": int(tot_nt),
        "treat_rate_pct": _safe_rate(tot_kt, tot_nt),
        "ctrl_k": int(tot_kc),
        "ctrl_n": int(tot_nc),
        "ctrl_rate_pct": _safe_rate(tot_kc, tot_nc),
        "or_mh": or_mh,
        "or_ci95": or_ci95,
        "cmh_chi2": cmh_chi2,
        "cmh_p_value": cmh_p,
        "weighted_diff_pp": weighted_diff_pp,
    }


def _mann_whitney(vals_a: list[float], vals_b: list[float]) -> dict[str, Any]:
    if len(vals_a) < 2 or len(vals_b) < 2:
        return {"n_a": len(vals_a), "n_b": len(vals_b), "u_stat": None, "p_value": None}
    u_stat, p_val = stats.mannwhitneyu(vals_a, vals_b, alternative="two-sided")
    return {
        "n_a": len(vals_a),
        "n_b": len(vals_b),
        "median_a": round(float(np.median(vals_a)), 3),
        "median_b": round(float(np.median(vals_b)), 3),
        "u_stat": round(float(u_stat), 2),
        "p_value": float(p_val),
    }


def _spearman(x: list[float], y: list[float]) -> dict[str, Any]:
    if len(x) < 5 or len(set(x)) < 2 or len(set(y)) < 2:
        return {"n": len(x), "rho": None, "p_value": None}
    rho, p_val = stats.spearmanr(x, y)
    return {
        "n": len(x),
        "rho": round(float(rho), 4) if not math.isnan(rho) else None,
        "p_value": float(p_val) if not math.isnan(p_val) else None,
    }


def run_p16(paths: PathConfig | None = None) -> dict[str, Any]:
    paths = paths or get_paths()
    paths.ensure_dirs()
    log, ts_log_path = setup_verbose_logger(
        "p16_jev_judgment_and_szz",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )

    jev_dir = paths.scratch_dir / "jev_pr_reviews"
    aidev_dir = paths.scratch_dir / "aidev"

    f_prs = jev_dir / "jev_pull_requests.parquet"
    f_sigs_reparsed = paths.results_dir / "jev_bot_signals_reparsed.parquet"
    f_sigs_raw = jev_dir / "jev_bot_signals_and_comments.parquet"
    f_sigs = f_sigs_reparsed if f_sigs_reparsed.exists() else f_sigs_raw
    f_revs = jev_dir / "jev_formal_reviews.parquet"
    f_commits = jev_dir / "jev_git_commits.parquet"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    for req in (f_prs, f_sigs, f_revs, f_commits, f_szz):
        if not req.exists():
            raise FileNotFoundError(f"Required input file missing: {req}")

    log.info("Using Jev signals file: %s", f_sigs)
    log.info("Using SZZ ledger: %s", f_szz)

    con = duckdb.connect()
    szz_cols = _csv_columns(con, f_szz)
    has_hotspot_14d = "pre_pr_14d_hotspot_fixes" in szz_cols
    has_hotspot_cols = {
        "pre_pr_30d_hotspot_fixes",
        "pre_pr_30d_hotspot_commits",
    }.issubset(szz_cols)
    has_surv14 = "file_survival_14d_pct" in szz_cols
    log.info(
        "SZZ schema check: total_cols=%d | has_hotspot_14d=%s | has_hotspot_cols=%s | has_file_survival_14d=%s",
        len(szz_cols),
        has_hotspot_14d,
        has_hotspot_cols,
        has_surv14,
    )

    human_comm_filter = _human_actor_sql("author_login")
    human_rev_filter = _human_actor_sql("reviewer_login")
    primary_fams_in = sql_in_list(PRIMARY_BOT_FAMILIES)
    clean_p_origin_sql = _clean_author_origin_sql("p.author_origin", "p.author_login")

    # ------------------------------------------------------------------
    # PART A1: Verbosity & Information-Density Stratification Across Regimes
    # ------------------------------------------------------------------
    log.info("Part A1: Computing verbosity, alerts, merge rates, and post-bot human engagement across regimes")

    bot_fam_rows = con.execute(f"""
        SELECT
            bot_family,
            COUNT(*) AS comment_rows,
            COUNT(DISTINCT LOWER(repo_full_name) || '#' || CAST(pr_number AS VARCHAR)) AS distinct_prs,
            ROUND(AVG(comment_chars), 2) AS mean_chars,
            ROUND(MEDIAN(comment_chars), 1) AS median_chars,
            ROUND(QUANTILE_CONT(comment_chars, 0.25), 1) AS q25_chars,
            ROUND(QUANTILE_CONT(comment_chars, 0.75), 1) AS q75_chars,
            ROUND(AVG(COALESCE(alerts_count, 0)), 3) AS mean_alerts,
            ROUND(MEDIAN(COALESCE(alerts_count, 0)), 1) AS median_alerts,
            ROUND(100.0 * AVG(CASE WHEN COALESCE(alerts_count, 0) > 0 THEN 1.0 ELSE 0.0 END), 2) AS pct_flagged
        FROM read_parquet('{f_sigs.as_posix()}')
        WHERE bot_family IN ({primary_fams_in})
        GROUP BY 1
        ORDER BY comment_rows DESC
    """).fetchall()

    bot_family_verbosity = [
        {
            "bot_family": r[0],
            "comment_rows": int(r[1]),
            "distinct_prs": int(r[2]),
            "mean_chars": float(r[3]),
            "median_chars": float(r[4]),
            "q25_chars": float(r[5]),
            "q75_chars": float(r[6]),
            "iqr_chars": round(float(r[6]) - float(r[5]), 1),
            "mean_alerts": float(r[7]),
            "median_alerts": float(r[8]),
            "pct_flagged": float(r[9]),
        }
        for r in bot_fam_rows
    ]

    # PR-level regime assignment + post-bot human discussion engagement
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_pr_regime_engagement AS
        WITH bot_first AS (
            SELECT
                LOWER(repo_full_name) AS repo_l,
                pr_number,
                MAX(CASE WHEN bot_family = 'jev_decision_model_linter' THEN 1 ELSE 0 END) AS has_dml,
                MAX(CASE WHEN bot_family = 'jev_pr_risk_histogram' THEN 1 ELSE 0 END) AS has_risk,
                MAX(CASE WHEN bot_family = 'jev_taste_policy_gate' THEN 1 ELSE 0 END) AS has_taste,
                MAX(CASE WHEN bot_family = 'jev_review_router' THEN 1 ELSE 0 END) AS has_router,
                MAX(CASE WHEN bot_family = 'jev_council_architect_review' THEN 1 ELSE 0 END) AS has_council,
                MAX(CASE WHEN bot_family = 'jev_loop_review_gate' THEN 1 ELSE 0 END) AS has_loop,
                MAX(CASE WHEN bot_family = 'jev_way_of_working_advisor' THEN 1 ELSE 0 END) AS has_way,
                MAX(CASE WHEN bot_family = 'deterministic_merge_gate' THEN 1 ELSE 0 END) AS has_det_gate,
                MAX(CASE WHEN bot_family = 'static_sast_bot_control' THEN 1 ELSE 0 END) AS has_sast,
                MAX(CASE WHEN bot_family = 'prose_review_bot_control' THEN 1 ELSE 0 END) AS has_prose,
                MAX(CASE WHEN is_jev_signal THEN 1 ELSE 0 END) AS has_jev,
                MAX(CASE WHEN is_jev_signal AND COALESCE(alerts_count, 0) > 0 THEN 1 ELSE 0 END) AS jev_flagged,
                SUM(CASE WHEN is_jev_signal THEN COALESCE(alerts_count, 0) ELSE 0 END) AS jev_alerts_sum,
                AVG(CASE WHEN is_jev_signal THEN comment_chars END) AS jev_mean_chars,
                AVG(CASE WHEN bot_family IN ({primary_fams_in}) THEN comment_chars END) AS primary_bot_mean_chars,
                MIN(CASE WHEN bot_family IN ({primary_fams_in}) THEN TRY_CAST(created_at AS TIMESTAMPTZ) END) AS first_bot_ts,
                MIN(CASE WHEN is_jev_signal THEN TRY_CAST(created_at AS TIMESTAMPTZ) END) AS first_jev_ts
            FROM read_parquet('{f_sigs.as_posix()}')
            GROUP BY 1, 2
        ),
        human_comms AS (
            SELECT
                LOWER(c.repo_full_name) AS repo_l,
                c.pr_number,
                TRY_CAST(c.created_at AS TIMESTAMPTZ) AS hc_ts,
                c.comment_chars
            FROM read_parquet('{f_sigs.as_posix()}') c
            WHERE c.bot_family = 'human_comment'
              AND c.author_type = 'User'
              AND {human_comm_filter.replace('author_login', 'c.author_login')}
        ),
        hc_agg AS (
            SELECT
                p.repo_full_name,
                LOWER(p.repo_full_name) AS repo_l,
                p.pr_number,
                COUNT(hc.hc_ts) AS total_human_comms,
                SUM(CASE WHEN hc.hc_ts IS NOT NULL AND (bf.first_bot_ts IS NULL OR hc.hc_ts > bf.first_bot_ts) THEN 1 ELSE 0 END) AS post_bot_human_comms,
                AVG(CASE WHEN hc.hc_ts IS NOT NULL AND (bf.first_bot_ts IS NULL OR hc.hc_ts > bf.first_bot_ts) THEN hc.comment_chars END) AS post_bot_human_mean_chars,
                MIN(CASE WHEN bf.first_bot_ts IS NOT NULL AND hc.hc_ts > bf.first_bot_ts THEN hc.hc_ts END) AS first_post_bot_hc_ts
            FROM read_parquet('{f_prs.as_posix()}') p
            LEFT JOIN bot_first bf ON LOWER(p.repo_full_name) = bf.repo_l AND p.pr_number = bf.pr_number
            LEFT JOIN human_comms hc ON LOWER(p.repo_full_name) = hc.repo_l AND p.pr_number = hc.pr_number
            GROUP BY 1, 2, 3
        ),
        fr_agg AS (
            SELECT
                LOWER(repo_full_name) AS repo_l,
                pr_number,
                COUNT(*) AS total_formal_reviews,
                SUM(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} THEN 1 ELSE 0 END) AS human_formal_reviews,
                SUM(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} AND state = 'APPROVED' THEN 1 ELSE 0 END) AS human_approved,
                SUM(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS human_cr,
                SUM(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} AND COALESCE(body_chars, 0) > 20 THEN 1 ELSE 0 END) AS human_substantive_revs,
                SUM(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} AND state = 'APPROVED' AND COALESCE(body_chars, 0) <= 20 THEN 1 ELSE 0 END) AS human_rubber_stamps,
                AVG(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} THEN COALESCE(body_chars, 0) END) AS mean_human_rev_chars,
                MIN(CASE WHEN reviewer_type = 'User' AND {human_rev_filter} THEN TRY_CAST(submitted_at AS TIMESTAMPTZ) END) AS first_human_rev_ts
            FROM read_parquet('{f_revs.as_posix()}')
            GROUP BY 1, 2
        )
        SELECT
            p.repo_full_name,
            p.pr_number,
            {clean_p_origin_sql} AS author_origin,
            p.state,
            p.is_merged,
            TRY_CAST(p.created_at AS TIMESTAMPTZ) AS pr_created_ts,
            TRY_CAST(p.merged_at AS TIMESTAMPTZ) AS pr_merged_ts,
            CASE
                WHEN bf.has_dml = 1 THEN 'jev_decision_model_linter'
                WHEN bf.has_risk = 1 THEN 'jev_pr_risk_histogram'
                WHEN bf.has_taste = 1 THEN 'jev_taste_policy_gate'
                WHEN bf.has_router = 1 THEN 'jev_review_router'
                WHEN bf.has_council = 1 THEN 'jev_council_architect_review'
                WHEN bf.has_loop = 1 THEN 'jev_loop_review_gate'
                WHEN bf.has_way = 1 THEN 'jev_way_of_working_advisor'
                WHEN bf.has_det_gate = 1 THEN 'deterministic_merge_gate'
                WHEN bf.has_sast = 1 THEN 'static_sast_bot_control'
                WHEN bf.has_prose = 1 THEN 'prose_review_bot_control'
                ELSE 'no_bot_control'
            END AS regime,
            COALESCE(bf.has_jev, 0) AS has_jev,
            COALESCE(bf.jev_flagged, 0) AS jev_flagged,
            COALESCE(bf.jev_alerts_sum, 0) AS jev_alerts_sum,
            bf.jev_mean_chars,
            bf.primary_bot_mean_chars,
            bf.first_bot_ts,
            bf.first_jev_ts,
            COALESCE(h.total_human_comms, 0) AS total_human_comms,
            COALESCE(h.post_bot_human_comms, 0) AS post_bot_human_comms,
            h.post_bot_human_mean_chars,
            DATE_DIFF('minute', bf.first_bot_ts, h.first_post_bot_hc_ts) AS mins_bot_to_first_hc,
            COALESCE(f.total_formal_reviews, 0) AS total_formal_reviews,
            COALESCE(f.human_formal_reviews, 0) AS human_formal_reviews,
            COALESCE(f.human_approved, 0) AS human_approved,
            COALESCE(f.human_cr, 0) AS human_cr,
            COALESCE(f.human_substantive_revs, 0) AS human_substantive_revs,
            COALESCE(f.human_rubber_stamps, 0) AS human_rubber_stamps,
            f.mean_human_rev_chars,
            DATE_DIFF('minute', TRY_CAST(p.created_at AS TIMESTAMPTZ), f.first_human_rev_ts) AS mins_open_to_first_hrev,
            DATE_DIFF('minute', bf.first_jev_ts, f.first_human_rev_ts) AS mins_jev_to_first_hrev
        FROM read_parquet('{f_prs.as_posix()}') p
        LEFT JOIN bot_first bf ON LOWER(p.repo_full_name) = bf.repo_l AND p.pr_number = bf.pr_number
        LEFT JOIN hc_agg h ON LOWER(p.repo_full_name) = h.repo_l AND p.pr_number = h.pr_number
        LEFT JOIN fr_agg f ON LOWER(p.repo_full_name) = f.repo_l AND p.pr_number = f.pr_number
    """)

    regime_rows = con.execute("""
        SELECT
            regime,
            COUNT(*) AS prs_total,
            SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_prs,
            ROUND(AVG(primary_bot_mean_chars), 1) AS mean_bot_chars,
            ROUND(MEDIAN(primary_bot_mean_chars), 1) AS median_bot_chars,
            ROUND(QUANTILE_CONT(primary_bot_mean_chars, 0.75) - QUANTILE_CONT(primary_bot_mean_chars, 0.25), 1) AS iqr_bot_chars,
            ROUND(AVG(jev_alerts_sum), 2) AS mean_alerts,
            SUM(CASE WHEN post_bot_human_comms > 0 THEN 1 ELSE 0 END) AS prs_with_post_bot_hc,
            ROUND(AVG(post_bot_human_comms), 2) AS mean_post_bot_hc_count,
            ROUND(AVG(post_bot_human_mean_chars), 1) AS mean_post_bot_hc_chars,
            ROUND(MEDIAN(CASE WHEN mins_bot_to_first_hc >= 0 THEN mins_bot_to_first_hc END), 1) AS median_mins_to_hc,
            SUM(CASE WHEN total_formal_reviews > 0 THEN 1 ELSE 0 END) AS prs_with_any_formal_rev,
            SUM(CASE WHEN human_formal_reviews > 0 THEN 1 ELSE 0 END) AS prs_with_human_formal_rev
        FROM v_pr_regime_engagement
        GROUP BY 1
        ORDER BY prs_total DESC
    """).fetchall()

    regime_summary: list[dict[str, Any]] = []
    for r in regime_rows:
        n_pr = int(r[1])
        m_pr = int(r[2])
        hc_pr = int(r[7])
        fr_any = int(r[11])
        fr_hum = int(r[12])
        regime_summary.append({
            "regime": r[0],
            "prs_total": n_pr,
            "merged_prs": m_pr,
            "merge_rate_pct": _safe_rate(m_pr, n_pr),
            "merge_rate_ci95_pct": _wilson_pct(m_pr, n_pr),
            "mean_bot_chars": float(r[3]) if r[3] is not None else None,
            "median_bot_chars": float(r[4]) if r[4] is not None else None,
            "iqr_bot_chars": float(r[5]) if r[5] is not None else None,
            "mean_alerts": float(r[6]),
            "prs_with_post_bot_human_comment": hc_pr,
            "pct_with_post_bot_human_comment": _safe_rate(hc_pr, n_pr),
            "post_bot_hc_ci95_pct": _wilson_pct(hc_pr, n_pr),
            "mean_post_bot_human_comment_count": float(r[8]),
            "mean_post_bot_human_comment_chars": float(r[9]) if r[9] is not None else None,
            "median_mins_bot_to_first_human_comment": float(r[10]) if r[10] is not None else None,
            "formal_review_any_hydrated_prs": fr_any,
            "formal_review_any_hydration_pct": _safe_rate(fr_any, n_pr),
            "formal_review_human_hydrated_prs": fr_hum,
            "formal_review_human_hydration_pct": _safe_rate(fr_hum, n_pr),
        })

    # ------------------------------------------------------------------
    # PART A2: Hydrated Formal Review Judgment & Post-Jev Commits
    # ------------------------------------------------------------------
    log.info("Part A2: Analyzing hydrated Jev repos (%s) formal review judgment & pre-merge corrective commits", HYDRATED_JEV_REPOS)

    hydrated_in = sql_in_list(r.lower() for r in HYDRATED_JEV_REPOS)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_hydrated_jev_prs AS
        WITH cm_agg AS (
            SELECT
                LOWER(c.repo_full_name) AS repo_l,
                CAST(c.pr_number AS BIGINT) AS pr_number,
                COUNT(*) AS total_git_commits,
                SUM(CASE WHEN e.first_jev_ts IS NOT NULL
                          AND TRY_CAST(c.committed_at AS TIMESTAMPTZ) > e.first_jev_ts
                          AND (e.pr_merged_ts IS NULL OR TRY_CAST(c.committed_at AS TIMESTAMPTZ) <= e.pr_merged_ts)
                         THEN 1 ELSE 0 END) AS post_jev_pre_merge_commits
            FROM read_parquet('{f_commits.as_posix()}') c
            JOIN v_pr_regime_engagement e
              ON LOWER(c.repo_full_name) = LOWER(e.repo_full_name)
             AND CAST(c.pr_number AS BIGINT) = e.pr_number
            GROUP BY 1, 2
        )
        SELECT
            e.*,
            CASE WHEN cm.total_git_commits IS NOT NULL THEN 1 ELSE 0 END AS has_commit_timeline,
            COALESCE(cm.total_git_commits, 0) AS total_git_commits,
            COALESCE(cm.post_jev_pre_merge_commits, 0) AS post_jev_pre_merge_commits,
            CASE
                WHEN NOT e.is_merged AND LOWER(COALESCE(e.state, '')) = 'closed'
                     AND e.human_formal_reviews = 0 AND e.total_human_comms = 0
                THEN 1 ELSE 0
            END AS pre_review_self_closed
        FROM v_pr_regime_engagement e
        LEFT JOIN cm_agg cm
          ON LOWER(e.repo_full_name) = cm.repo_l AND e.pr_number = cm.pr_number
        WHERE LOWER(e.repo_full_name) IN ({hydrated_in})
          AND e.author_origin IN ('Human_Engineer', 'Coding_Agent')
    """)

    def _agg_hydrated_group(group_expr: str, where_extra: str = "1=1") -> list[dict[str, Any]]:
        rows = con.execute(f"""
            SELECT
                {group_expr} AS stratum,
                COUNT(*) AS prs,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged,
                SUM(CASE WHEN pre_review_self_closed = 1 THEN 1 ELSE 0 END) AS self_closed,
                SUM(CASE WHEN human_formal_reviews > 0 THEN 1 ELSE 0 END) AS prs_with_hrev,
                SUM(CASE WHEN human_approved > 0 THEN 1 ELSE 0 END) AS prs_approved,
                SUM(CASE WHEN human_cr > 0 THEN 1 ELSE 0 END) AS prs_cr,
                SUM(CASE WHEN human_substantive_revs > 0 THEN 1 ELSE 0 END) AS prs_substantive,
                SUM(CASE WHEN human_rubber_stamps > 0 AND human_substantive_revs = 0 AND human_cr = 0 THEN 1 ELSE 0 END) AS prs_rubber_stamp_only,
                ROUND(AVG(CASE WHEN human_formal_reviews > 0 THEN mean_human_rev_chars END), 1) AS mean_hrev_chars,
                ROUND(MEDIAN(CASE WHEN mins_open_to_first_hrev >= 0 THEN mins_open_to_first_hrev END), 1) AS med_mins_to_hrev,
                SUM(CASE WHEN has_commit_timeline = 1 THEN 1 ELSE 0 END) AS prs_with_commits,
                SUM(CASE WHEN has_commit_timeline = 1 AND post_jev_pre_merge_commits > 0 THEN 1 ELSE 0 END) AS prs_with_post_jev_commit
            FROM v_hydrated_jev_prs
            WHERE {where_extra}
            GROUP BY 1
            ORDER BY 1
        """).fetchall()
        out = []
        for r in rows:
            n_pr = int(r[1])
            n_hr = int(r[4])
            n_cm = int(r[11])
            out.append({
                "stratum": str(r[0]),
                "prs": n_pr,
                "merged_prs": int(r[2]),
                "merge_rate_pct": _safe_rate(int(r[2]), n_pr),
                "merge_rate_ci95_pct": _wilson_pct(int(r[2]), n_pr),
                "pre_review_self_closed_prs": int(r[3]),
                "pre_review_self_closure_pct": _safe_rate(int(r[3]), n_pr),
                "prs_with_human_formal_review": n_hr,
                "prs_approved": int(r[5]),
                "approved_among_reviewed_pct": _safe_rate(int(r[5]), n_hr),
                "prs_changes_requested": int(r[6]),
                "cr_among_reviewed_pct": _safe_rate(int(r[6]), n_hr),
                "prs_substantive_review_gt20c": int(r[7]),
                "substantive_among_reviewed_pct": _safe_rate(int(r[7]), n_hr),
                "prs_rubber_stamp_only": int(r[8]),
                "rubber_stamp_among_reviewed_pct": _safe_rate(int(r[8]), n_hr),
                "mean_human_review_body_chars": float(r[9]) if r[9] is not None else None,
                "median_mins_open_to_first_human_review": float(r[10]) if r[10] is not None else None,
                "prs_with_commit_timeline": n_cm,
                "prs_with_post_jev_corrective_commit": int(r[12]),
                "post_jev_corrective_commit_pct": _safe_rate(int(r[12]), n_cm),
            })
        return out

    hydrated_by_verdict_origin = _agg_hydrated_group(
        """
        author_origin || '::' || CASE
            WHEN has_jev = 1 AND jev_flagged = 1 THEN 'Jev_Flagged'
            WHEN has_jev = 1 AND jev_flagged = 0 THEN 'Jev_Clean'
            ELSE 'No_Jev_Control'
        END
        """
    )

    # Jev verbosity quartiles inside hydrated repos (Jev-signaled PRs only)
    # DuckDB disallows window functions directly inside GROUP BY; materialize quartile CTE cleanly
    q_rows = con.execute("""
        WITH q AS (
            SELECT
                *,
                NTILE(4) OVER (ORDER BY jev_mean_chars) AS q_idx
            FROM v_hydrated_jev_prs
            WHERE jev_mean_chars IS NOT NULL
        )
        SELECT
            'Q' || CAST(q_idx AS VARCHAR) AS quartile,
            COUNT(*) AS prs,
            ROUND(MIN(jev_mean_chars), 1) AS min_chars,
            ROUND(MAX(jev_mean_chars), 1) AS max_chars,
            SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged,
            SUM(CASE WHEN pre_review_self_closed = 1 THEN 1 ELSE 0 END) AS self_closed,
            SUM(CASE WHEN human_formal_reviews > 0 THEN 1 ELSE 0 END) AS prs_hrev,
            SUM(CASE WHEN human_approved > 0 THEN 1 ELSE 0 END) AS prs_app,
            SUM(CASE WHEN human_cr > 0 THEN 1 ELSE 0 END) AS prs_cr,
            SUM(CASE WHEN human_substantive_revs > 0 THEN 1 ELSE 0 END) AS prs_sub,
            SUM(CASE WHEN human_rubber_stamps > 0 AND human_substantive_revs = 0 AND human_cr = 0 THEN 1 ELSE 0 END) AS prs_rs,
            ROUND(AVG(CASE WHEN human_formal_reviews > 0 THEN mean_human_rev_chars END), 1) AS mean_hrev_chars,
            SUM(CASE WHEN has_commit_timeline = 1 THEN 1 ELSE 0 END) AS prs_cm,
            SUM(CASE WHEN has_commit_timeline = 1 AND post_jev_pre_merge_commits > 0 THEN 1 ELSE 0 END) AS prs_post_cm
        FROM q
        GROUP BY q_idx
        ORDER BY q_idx
    """).fetchall()
    hydrated_jev_quartiles = [
        {
            "quartile": r[0],
            "prs": int(r[1]),
            "min_jev_chars": float(r[2]),
            "max_jev_chars": float(r[3]),
            "merge_rate_pct": _safe_rate(int(r[4]), int(r[1])),
            "pre_review_self_closure_pct": _safe_rate(int(r[5]), int(r[1])),
            "prs_with_human_formal_review": int(r[6]),
            "approved_among_reviewed_pct": _safe_rate(int(r[7]), int(r[6])),
            "cr_among_reviewed_pct": _safe_rate(int(r[8]), int(r[6])),
            "substantive_among_reviewed_pct": _safe_rate(int(r[9]), int(r[6])),
            "rubber_stamp_among_reviewed_pct": _safe_rate(int(r[10]), int(r[6])),
            "mean_human_review_body_chars": float(r[11]) if r[11] is not None else None,
            "prs_with_commit_timeline": int(r[12]),
            "post_jev_corrective_commit_pct": _safe_rate(int(r[13]), int(r[12])),
        }
        for r in q_rows
    ]

    # Hypothesis tests within hydrated Jev PRs: Flagged vs Clean
    flagged_vs_clean_tests: dict[str, Any] = {}
    for origin in ("ALL", "Human_Engineer", "Coding_Agent"):
        origin_cond = "1=1" if origin == "ALL" else f"author_origin = '{origin}'"
        sub = con.execute(f"""
            SELECT
                CASE WHEN jev_flagged = 1 THEN 'Flagged' ELSE 'Clean' END AS arm,
                COUNT(*) AS prs,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged,
                SUM(CASE WHEN pre_review_self_closed = 1 THEN 1 ELSE 0 END) AS self_closed,
                SUM(CASE WHEN human_formal_reviews > 0 THEN 1 ELSE 0 END) AS hrev_n,
                SUM(CASE WHEN human_approved > 0 THEN 1 ELSE 0 END) AS app_k,
                SUM(CASE WHEN human_cr > 0 THEN 1 ELSE 0 END) AS cr_k,
                SUM(CASE WHEN human_substantive_revs > 0 THEN 1 ELSE 0 END) AS sub_k,
                SUM(CASE WHEN has_commit_timeline = 1 THEN 1 ELSE 0 END) AS cm_n,
                SUM(CASE WHEN has_commit_timeline = 1 AND post_jev_pre_merge_commits > 0 THEN 1 ELSE 0 END) AS post_cm_k
            FROM v_hydrated_jev_prs
            WHERE jev_mean_chars IS NOT NULL AND {origin_cond}
            GROUP BY 1
        """).fetchall()
        m = {r[0]: r for r in sub}
        if "Clean" in m and "Flagged" in m:
            c, f = m["Clean"], m["Flagged"]
            flagged_vs_clean_tests[origin] = {
                "merge_rate_clean_vs_flagged": {
                    **two_prop_z_test(int(c[2]), int(c[1]), int(f[2]), int(f[1])),
                    "fisher_p": fisher_exact_2x2(int(c[2]), int(c[1]), int(f[2]), int(f[1])),
                },
                "self_closure_clean_vs_flagged": {
                    **two_prop_z_test(int(c[3]), int(c[1]), int(f[3]), int(f[1])),
                    "fisher_p": fisher_exact_2x2(int(c[3]), int(c[1]), int(f[3]), int(f[1])),
                },
                "substantive_review_clean_vs_flagged": {
                    **two_prop_z_test(int(c[7]), int(c[4]), int(f[7]), int(f[4])),
                    "fisher_p": fisher_exact_2x2(int(c[7]), int(c[4]), int(f[7]), int(f[4])),
                },
                "post_jev_corrective_commit_clean_vs_flagged": {
                    **two_prop_z_test(int(c[9]), int(c[8]), int(f[9]), int(f[8])),
                    "fisher_p": fisher_exact_2x2(int(c[9]), int(c[8]), int(f[9]), int(f[8])),
                },
            }

    # ------------------------------------------------------------------
    # PART A3: Within-Repo Verbosity vs Human Judgment Correlation
    #          (getsentry/sentry AND AIDev Cohort C N=1,676 cross-check)
    # ------------------------------------------------------------------
    log.info("Part A3: Correlating log10(bot_chars) vs human judgment in getsentry/sentry and AIDev Cohort C")

    sentry_pts = con.execute("""
        SELECT
            LOG10(GREATEST(1.0, primary_bot_mean_chars)) AS log_bot_chars,
            primary_bot_mean_chars,
            CASE WHEN human_cr > 0 THEN 1.0 ELSE 0.0 END AS has_cr,
            CASE WHEN human_rubber_stamps > 0 AND human_substantive_revs = 0 AND human_cr = 0 THEN 1.0 ELSE 0.0 END AS is_rubber_stamp,
            COALESCE(mean_human_rev_chars, 0.0) AS mean_hrev_chars,
            CASE WHEN post_bot_human_comms > 0 THEN 1.0 ELSE 0.0 END AS has_post_bot_hc,
            human_formal_reviews
        FROM v_pr_regime_engagement
        WHERE LOWER(repo_full_name) = 'getsentry/sentry'
          AND primary_bot_mean_chars IS NOT NULL
    """).fetchall()

    sentry_reviewed_pts = [r for r in sentry_pts if int(r[6]) > 0]
    sentry_corr = {
        "n_all_bot_prs": len(sentry_pts),
        "n_formal_reviewed_prs": len(sentry_reviewed_pts),
        "spearman_log_bot_chars_vs_post_bot_human_comment": _spearman(
            [float(r[0]) for r in sentry_pts], [float(r[5]) for r in sentry_pts]
        ),
        "spearman_log_bot_chars_vs_human_cr_reviewed": _spearman(
            [float(r[0]) for r in sentry_reviewed_pts], [float(r[2]) for r in sentry_reviewed_pts]
        ),
        "spearman_log_bot_chars_vs_human_review_body_chars": _spearman(
            [float(r[0]) for r in sentry_reviewed_pts], [float(r[4]) for r in sentry_reviewed_pts]
        ),
        "spearman_log_bot_chars_vs_rubber_stamp": _spearman(
            [float(r[0]) for r in sentry_reviewed_pts], [float(r[3]) for r in sentry_reviewed_pts]
        ),
    }

    # AIDev Cohort C cross-check (N=1,676)
    f_cohort_log = paths.tables_dir / "analyzed_human_reviewed_prs_log.csv"
    f_aidev_comm = aidev_dir / "pr_comments.parquet"
    f_aidev_rev = aidev_dir / "pr_reviews.parquet"
    f_aidev_rc2 = aidev_dir / "pr_review_comments_v2.parquet"

    aidev_cohort_c_corr: dict[str, Any] = {"status": "missing_inputs"}
    verbosity_csv_rows: list[dict[str, Any]] = []

    # Add Sentry quartile/regime rows to verbosity CSV
    sentry_bucket_rows = con.execute("""
        WITH b AS (
            SELECT
                CASE
                    WHEN primary_bot_mean_chars < 400 THEN '1_<400_chars'
                    WHEN primary_bot_mean_chars < 800 THEN '2_400_799_chars'
                    WHEN primary_bot_mean_chars < 1500 THEN '3_800_1499_chars'
                    ELSE '4_1500plus_chars'
                END AS verbosity_bucket,
                *
            FROM v_pr_regime_engagement
            WHERE LOWER(repo_full_name) = 'getsentry/sentry'
              AND primary_bot_mean_chars IS NOT NULL
        )
        SELECT
            verbosity_bucket,
            COUNT(*) AS prs,
            ROUND(MEDIAN(primary_bot_mean_chars), 1) AS med_bot_chars,
            SUM(CASE WHEN post_bot_human_comms > 0 THEN 1 ELSE 0 END) AS post_bot_hc_prs,
            SUM(CASE WHEN human_formal_reviews > 0 THEN 1 ELSE 0 END) AS hrev_prs,
            SUM(CASE WHEN human_cr > 0 THEN 1 ELSE 0 END) AS cr_prs,
            SUM(CASE WHEN human_rubber_stamps > 0 AND human_substantive_revs = 0 AND human_cr = 0 THEN 1 ELSE 0 END) AS rubber_stamp_prs,
            ROUND(AVG(CASE WHEN human_formal_reviews > 0 THEN mean_human_rev_chars END), 1) AS mean_hrev_chars
        FROM b
        GROUP BY 1
        ORDER BY 1
    """).fetchall()
    for r in sentry_bucket_rows:
        n_pr, n_hr = int(r[1]), int(r[4])
        verbosity_csv_rows.append({
            "ecosystem": "Jev_Mined::getsentry/sentry",
            "verbosity_bucket": r[0],
            "prs": n_pr,
            "median_bot_chars": float(r[2]),
            "formal_reviewed_prs": n_hr,
            "post_bot_human_comment_pct": _safe_rate(int(r[3]), n_pr),
            "human_cr_veto_pct": _safe_rate(int(r[5]), n_hr),
            "rubber_stamp_pct": _safe_rate(int(r[6]), n_hr),
            "mean_human_review_body_chars": float(r[7]) if r[7] is not None else "",
        })

    if all(p.exists() for p in (f_cohort_log, f_aidev_comm, f_aidev_rev, f_aidev_rc2)):
        tier1_all_in = sql_in_list(TIER1_REVIEW_BOTS)
        tier1_comm_in = sql_in_list(TIER1_PR_COMMENTS_BOTS)
        cohort_c_rows = con.execute(f"""
            WITH c_prs AS (
                SELECT *
                FROM read_csv_auto('{f_cohort_log.as_posix()}', header=true)
                WHERE cohort = 'Cohort_C_Tier1_Bot_Plus_Human'
            ),
            bot_comm_chars AS (
                SELECT pr_id, SUM(LENGTH(COALESCE(body, ''))) AS chars
                FROM read_parquet('{f_aidev_comm.as_posix()}')
                WHERE "user" IN ({tier1_comm_in})
                GROUP BY 1
            ),
            bot_rev_chars AS (
                SELECT r.pr_id, SUM(LENGTH(COALESCE(r.body, ''))) AS chars
                FROM read_parquet('{f_aidev_rev.as_posix()}') r
                WHERE r."user" IN ({tier1_all_in})
                GROUP BY 1
            ),
            bot_rc2_chars AS (
                SELECT r.pr_id, SUM(LENGTH(COALESCE(rc.body, ''))) AS chars
                FROM read_parquet('{f_aidev_rc2.as_posix()}') rc
                JOIN read_parquet('{f_aidev_rev.as_posix()}') r
                  ON rc.pull_request_review_id = r.id
                WHERE rc."user" IN ({tier1_all_in})
                GROUP BY 1
            ),
            human_rev_len AS (
                SELECT pr_id, AVG(LENGTH(COALESCE(body, ''))) AS mean_hrev_chars
                FROM read_parquet('{f_aidev_rev.as_posix()}')
                WHERE user_type = 'User'
                  AND {_human_actor_sql('"user"')}
                GROUP BY 1
            )
            SELECT
                c.pr_id,
                COALESCE(bc.chars, 0) + COALESCE(br.chars, 0) + COALESCE(brc.chars, 0) AS total_bot_chars,
                CASE WHEN c.human_changes_req > 0 THEN 1 ELSE 0 END AS has_cr,
                CAST(c.rubber_stamp_approval AS BIGINT) AS is_rubber_stamp,
                COALESCE(hr.mean_hrev_chars, 0.0) AS mean_hrev_chars,
                c.human_inline_comments,
                CASE WHEN c.corrective_commits > 0 THEN 1 ELSE 0 END AS has_corrective
            FROM c_prs c
            LEFT JOIN bot_comm_chars bc ON c.pr_id = bc.pr_id
            LEFT JOIN bot_rev_chars br ON c.pr_id = br.pr_id
            LEFT JOIN bot_rc2_chars brc ON c.pr_id = brc.pr_id
            LEFT JOIN human_rev_len hr ON c.pr_id = hr.pr_id
            WHERE (COALESCE(bc.chars, 0) + COALESCE(br.chars, 0) + COALESCE(brc.chars, 0)) > 0
        """).fetchall()

        log_chars = [math.log10(max(1.0, float(r[1]))) for r in cohort_c_rows]
        aidev_cohort_c_corr = {
            "n_cohort_c_with_bot_chars": len(cohort_c_rows),
            "spearman_log_bot_chars_vs_human_cr": _spearman(log_chars, [float(r[2]) for r in cohort_c_rows]),
            "spearman_log_bot_chars_vs_rubber_stamp": _spearman(log_chars, [float(r[3]) for r in cohort_c_rows]),
            "spearman_log_bot_chars_vs_human_review_body_chars": _spearman(log_chars, [float(r[4]) for r in cohort_c_rows]),
            "spearman_log_bot_chars_vs_human_inline_comments": _spearman(log_chars, [float(r[5]) for r in cohort_c_rows]),
            "spearman_log_bot_chars_vs_corrective_commits": _spearman(log_chars, [float(r[6]) for r in cohort_c_rows]),
            "buckets": [],
        }

        buckets_map: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
        for r in cohort_c_rows:
            ch = float(r[1])
            if ch < 500:
                bk = "1_<500_chars"
            elif ch < 1500:
                bk = "2_500_1499_chars"
            elif ch < 4000:
                bk = "3_1500_3999_chars"
            else:
                bk = "4_4000plus_chars"
            buckets_map[bk].append(r)

        for bk in sorted(buckets_map.keys()):
            grp = buckets_map[bk]
            n_g = len(grp)
            cr_k = sum(int(x[2]) for x in grp)
            rs_k = sum(int(x[3]) for x in grp)
            med_ch = round(float(np.median([float(x[1]) for x in grp])), 1)
            mean_hch = round(float(np.mean([float(x[4]) for x in grp])), 1)
            b_rec = {
                "verbosity_bucket": bk,
                "prs": n_g,
                "median_bot_chars": med_ch,
                "human_cr_veto_pct": _safe_rate(cr_k, n_g),
                "human_cr_ci95_pct": _wilson_pct(cr_k, n_g),
                "rubber_stamp_pct": _safe_rate(rs_k, n_g),
                "rubber_stamp_ci95_pct": _wilson_pct(rs_k, n_g),
                "mean_human_review_body_chars": mean_hch,
            }
            aidev_cohort_c_corr["buckets"].append(b_rec)
            verbosity_csv_rows.append({
                "ecosystem": "AIDev_Cohort_C",
                "verbosity_bucket": bk,
                "prs": n_g,
                "median_bot_chars": med_ch,
                "formal_reviewed_prs": n_g,
                "post_bot_human_comment_pct": "",
                "human_cr_veto_pct": b_rec["human_cr_veto_pct"],
                "rubber_stamp_pct": b_rec["rubber_stamp_pct"],
                "mean_human_review_body_chars": mean_hch,
            })

    # Write jev_verbosity_vs_human_judgment_log.csv
    out_verbosity_csv = paths.tables_dir / "jev_verbosity_vs_human_judgment_log.csv"
    with open(out_verbosity_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "ecosystem",
            "verbosity_bucket",
            "prs",
            "median_bot_chars",
            "formal_reviewed_prs",
            "post_bot_human_comment_pct",
            "human_cr_veto_pct",
            "rubber_stamp_pct",
            "mean_human_review_body_chars",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(verbosity_csv_rows)
    log.info("Wrote %d rows -> %s", len(verbosity_csv_rows), out_verbosity_csv)

    # ------------------------------------------------------------------
    # PART B: NQ-02 Bare-Git SZZ Post-Release Defect Outcomes
    # ------------------------------------------------------------------
    log.info("Part B: Computing NQ-02 Bare-Git SZZ outcomes (14d & 30d, within-repo MH, hotspot DiD, mediation)")

    hotspot_14d_select = (
        "COALESCE(s.pre_pr_14d_hotspot_fixes, 0) AS pre_pr_14d_hotspot_fixes"
        if has_hotspot_14d
        else "NULL::BIGINT AS pre_pr_14d_hotspot_fixes"
    )
    hotspot_select = (
        "COALESCE(s.pre_pr_30d_hotspot_fixes, 0) AS pre_pr_30d_hotspot_fixes, "
        "COALESCE(s.pre_pr_30d_hotspot_commits, 0) AS pre_pr_30d_hotspot_commits"
        if has_hotspot_cols
        else "NULL::BIGINT AS pre_pr_30d_hotspot_fixes, NULL::BIGINT AS pre_pr_30d_hotspot_commits"
    )
    surv14_select = (
        "s.file_survival_14d_pct" if has_surv14 else "NULL::DOUBLE AS file_survival_14d_pct"
    )
    clean_s_origin_sql = _clean_author_origin_sql("s.author_origin", "jp.author_login")

    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_jev_szz_joined AS
        WITH sig AS (
            SELECT
                LOWER(repo_full_name) AS repo_l,
                pr_number,
                MAX(CASE WHEN is_jev_signal THEN 1 ELSE 0 END) AS has_jev,
                MAX(CASE WHEN is_jev_signal AND COALESCE(alerts_count, 0) > 0 THEN 1 ELSE 0 END) AS jev_flagged,
                MAX(CASE WHEN bot_family = 'prose_review_bot_control' THEN 1 ELSE 0 END) AS has_prose,
                MAX(CASE WHEN bot_family = 'static_sast_bot_control' THEN 1 ELSE 0 END) AS has_sast,
                MIN(CASE WHEN is_jev_signal THEN TRY_CAST(created_at AS TIMESTAMPTZ) END) AS first_jev_ts
            FROM read_parquet('{f_sigs.as_posix()}')
            GROUP BY 1, 2
        ),
        cm AS (
            SELECT
                LOWER(c.repo_full_name) AS repo_l,
                CAST(c.pr_number AS BIGINT) AS pr_number,
                COUNT(*) AS total_commits,
                SUM(CASE WHEN g.first_jev_ts IS NOT NULL
                          AND TRY_CAST(c.committed_at AS TIMESTAMPTZ) > g.first_jev_ts
                          AND TRY_CAST(c.committed_at AS TIMESTAMPTZ) <= s.merged_at
                         THEN 1 ELSE 0 END) AS post_jev_fix_commits
            FROM read_parquet('{f_commits.as_posix()}') c
            JOIN read_csv_auto('{f_szz.as_posix()}', header=true) s
              ON LOWER(c.repo_full_name) = LOWER(s.repo_full_name)
             AND CAST(c.pr_number AS BIGINT) = s.pr_number
            LEFT JOIN sig g
              ON LOWER(c.repo_full_name) = g.repo_l
             AND CAST(c.pr_number AS BIGINT) = g.pr_number
            WHERE s.corpus = 'Jev_Mined'
            GROUP BY 1, 2
        ),
        clean_szz AS (
            SELECT
                s.*,
                {clean_s_origin_sql} AS clean_author_origin
            FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
            LEFT JOIN read_parquet('{f_prs.as_posix()}') jp
              ON LOWER(s.repo_full_name) = LOWER(jp.repo_full_name) AND s.pr_number = jp.pr_number
            WHERE s.corpus = 'Jev_Mined'
        )
        SELECT
            s.repo_full_name,
            s.pr_number,
            s.clean_author_origin AS author_origin,
            CASE
                WHEN COALESCE(g.has_jev, 0) = 1 AND COALESCE(g.jev_flagged, 0) = 1 THEN 'Jev_Flagged'
                WHEN COALESCE(g.has_jev, 0) = 1 AND COALESCE(g.jev_flagged, 0) = 0 THEN 'Jev_Clean'
                WHEN COALESCE(g.has_prose, 0) = 1 THEN 'Prose_Bot_Control'
                WHEN COALESCE(g.has_sast, 0) = 1 THEN 'Static_SAST_Control'
                ELSE 'No_Bot_Control'
            END AS arm,
            CASE WHEN COALESCE(g.has_jev, 0) = 1 THEN 1 ELSE 0 END AS has_jev,
            s.uncensored_14d,
            s.uncensored_30d,
            s.szz_bugfix_14d,
            s.szz_bugfix_30d,
            s.reverted_14d,
            s.reverted_30d,
            {surv14_select},
            s.file_survival_30d_pct,
            s.days_to_first_szz_fix,
            {hotspot_14d_select},
            {hotspot_select},
            CASE WHEN cm.total_commits IS NOT NULL THEN 1 ELSE 0 END AS has_commit_timeline,
            COALESCE(cm.post_jev_fix_commits, 0) AS post_jev_fix_commits
        FROM clean_szz s
        LEFT JOIN sig g
          ON LOWER(s.repo_full_name) = g.repo_l AND s.pr_number = g.pr_number
        LEFT JOIN cm
          ON LOWER(s.repo_full_name) = cm.repo_l AND s.pr_number = cm.pr_number
        WHERE s.clean_author_origin IN ('Human_Engineer', 'Coding_Agent')
    """)

    def _query_szz_window(window_days: int) -> dict[str, Any]:
        u_col = f"uncensored_{window_days}d"
        b_col = f"szz_bugfix_{window_days}d"
        r_col = f"reverted_{window_days}d"
        sv_col = f"file_survival_{window_days}d_pct"

        pooled_rows = con.execute(f"""
            SELECT
                author_origin,
                arm,
                COUNT(*) AS n,
                SUM({b_col}) AS szz_bugs,
                SUM({r_col}) AS reverts,
                ROUND(AVG({sv_col}), 2) AS mean_survival_pct,
                ROUND(MEDIAN(CASE WHEN {b_col} = 1 THEN days_to_first_szz_fix END), 2) AS med_days_to_fix,
                ROUND(AVG(pre_pr_30d_hotspot_fixes), 3) AS mean_pre_hotspot_fixes
            FROM v_jev_szz_joined
            WHERE {u_col} = 1
            GROUP BY 1, 2
            ORDER BY 1, 2
        """).fetchall()

        pooled = [
            {
                "author_origin": r[0],
                "arm": r[1],
                "n": int(r[2]),
                "szz_bugs": int(r[3]),
                "szz_bugfix_pct": _safe_rate(int(r[3]), int(r[2])),
                "szz_bugfix_ci95_pct": _wilson_pct(int(r[3]), int(r[2])),
                "reverts": int(r[4]),
                "revert_pct": _safe_rate(int(r[4]), int(r[2])),
                "mean_file_survival_pct": float(r[5]) if r[5] is not None else None,
                "median_days_to_first_szz_fix": float(r[6]) if r[6] is not None else None,
                "mean_pre_pr_30d_hotspot_fixes": float(r[7]) if r[7] is not None else None,
            }
            for r in pooled_rows
        ]

        repo_rows = con.execute(f"""
            SELECT
                repo_full_name,
                author_origin,
                arm,
                COUNT(*) AS n,
                SUM({b_col}) AS szz_bugs,
                SUM({r_col}) AS reverts,
                ROUND(AVG({sv_col}), 2) AS mean_survival_pct,
                ROUND(AVG(pre_pr_30d_hotspot_fixes), 3) AS mean_pre_hotspot_fixes
            FROM v_jev_szz_joined
            WHERE {u_col} = 1
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        """).fetchall()

        per_repo = [
            {
                "window": f"{window_days}d",
                "repo_full_name": r[0],
                "author_origin": r[1],
                "arm": r[2],
                "n": int(r[3]),
                "szz_bugs": int(r[4]),
                "szz_bugfix_pct": _safe_rate(int(r[4]), int(r[3])),
                "szz_bugfix_ci95_pct": _wilson_pct(int(r[4]), int(r[3])),
                "reverts": int(r[5]),
                "mean_file_survival_pct": float(r[6]) if r[6] is not None else None,
                "mean_pre_pr_30d_hotspot_fixes": float(r[7]) if r[7] is not None else None,
            }
            for r in repo_rows
        ]

        # Mantel-Haenszel within-repo matched comparisons (stratified by repo x author_origin)
        def _mh_compare(treat_arms: tuple[str, ...], ctrl_arms: tuple[str, ...], origin_filter: str) -> dict[str, Any]:
            t_in = sql_in_list(treat_arms)
            c_in = sql_in_list(ctrl_arms)
            o_cond = "1=1" if origin_filter == "ALL" else f"author_origin = '{origin_filter}'"
            rows = con.execute(f"""
                SELECT
                    repo_full_name || '::' || author_origin AS stratum,
                    SUM(CASE WHEN arm IN ({t_in}) THEN {b_col} ELSE 0 END) AS kt,
                    SUM(CASE WHEN arm IN ({t_in}) THEN 1 ELSE 0 END) AS nt,
                    SUM(CASE WHEN arm IN ({c_in}) THEN {b_col} ELSE 0 END) AS kc,
                    SUM(CASE WHEN arm IN ({c_in}) THEN 1 ELSE 0 END) AS nc
                FROM v_jev_szz_joined
                WHERE {u_col} = 1 AND {o_cond}
                GROUP BY 1
                HAVING nt > 0 AND nc > 0
                ORDER BY 1
            """).fetchall()
            strata = [(str(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows]
            return _mantel_haenszel(strata)

        mh_comparisons = {}
        for origin in ("ALL", "Human_Engineer", "Coding_Agent"):
            mh_comparisons[origin] = {
                "jev_flagged_vs_jev_clean": _mh_compare(("Jev_Flagged",), ("Jev_Clean",), origin),
                "jev_any_vs_no_bot_control": _mh_compare(("Jev_Flagged", "Jev_Clean"), ("No_Bot_Control",), origin),
                "jev_any_vs_prose_bot_control": _mh_compare(("Jev_Flagged", "Jev_Clean"), ("Prose_Bot_Control",), origin),
            }

        return {
            "window_days": window_days,
            "pooled_by_origin_arm": pooled,
            "per_repo_breakdown": per_repo,
            "mantel_haenszel_within_repo_matched": mh_comparisons,
        }

    szz_14d = _query_szz_window(14)
    szz_30d = _query_szz_window(30)

    # Export within-repo SZZ outcomes CSV (both 14d and 30d rows)
    out_szz_csv = paths.tables_dir / "jev_szz_within_repo_outcomes_log.csv"
    with open(out_szz_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "window",
            "repo_full_name",
            "author_origin",
            "arm",
            "n",
            "szz_bugs",
            "szz_bugfix_pct",
            "szz_bugfix_ci95_low",
            "szz_bugfix_ci95_high",
            "reverts",
            "mean_file_survival_pct",
            "mean_pre_pr_30d_hotspot_fixes",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in szz_14d["per_repo_breakdown"] + szz_30d["per_repo_breakdown"]:
            w.writerow({
                "window": row["window"],
                "repo_full_name": row["repo_full_name"],
                "author_origin": row["author_origin"],
                "arm": row["arm"],
                "n": row["n"],
                "szz_bugs": row["szz_bugs"],
                "szz_bugfix_pct": row["szz_bugfix_pct"],
                "szz_bugfix_ci95_low": row["szz_bugfix_ci95_pct"][0],
                "szz_bugfix_ci95_high": row["szz_bugfix_ci95_pct"][1],
                "reverts": row["reverts"],
                "mean_file_survival_pct": row["mean_file_survival_pct"] if row["mean_file_survival_pct"] is not None else "",
                "mean_pre_pr_30d_hotspot_fixes": row["mean_pre_pr_30d_hotspot_fixes"] if row["mean_pre_pr_30d_hotspot_fixes"] is not None else "",
            })
    log.info("Wrote %s", out_szz_csv)

    # ------------------------------------------------------------------
    # PART B2: Pre-PR 30-Day Hotspot Confounding Control & DiD Proxy
    # ------------------------------------------------------------------
    hotspot_control: dict[str, Any]
    if not has_hotspot_cols:
        log.warning(
            "pre_pr_30d_hotspot_fixes / pre_pr_30d_hotspot_commits absent in %s; "
            "skipping hotspot stratification rather than emitting defaults.",
            f_szz,
        )
        hotspot_control = {"status": "missing_hotspot_columns_in_ledger"}
    else:
        log.info("Part B2: Running Cold-File vs Hot-File confounding control & DiD proxy")
        hs_rows = con.execute("""
            SELECT
                CASE WHEN pre_pr_30d_hotspot_fixes = 0 THEN 'Cold_Files (pre_fixes==0)' ELSE 'Hot_Files (pre_fixes>=1)' END AS file_heat,
                arm,
                COUNT(*) AS n_u14,
                SUM(szz_bugfix_14d) AS bug14,
                SUM(CASE WHEN uncensored_30d = 1 THEN 1 ELSE 0 END) AS n_u30,
                SUM(CASE WHEN uncensored_30d = 1 THEN szz_bugfix_30d ELSE 0 END) AS bug30,
                ROUND(AVG(pre_pr_30d_hotspot_fixes), 3) AS mean_pre_fixes,
                ROUND(AVG(CASE WHEN pre_pr_30d_hotspot_fixes > 0 THEN 1.0 ELSE 0.0 END) * 100.0, 2) AS pre_hot_pct
            FROM v_jev_szz_joined
            WHERE uncensored_14d = 1
            GROUP BY 1, 2
            ORDER BY 1, 2
        """).fetchall()

        # Selection bias test: pre_pr_30d_hotspot_fixes for Jev_Flagged vs Jev_Clean vs No_Bot_Control
        pre_vals_by_arm: dict[str, list[float]] = defaultdict(list)
        for arm_name, pre_fix_30d in con.execute("""
            SELECT arm, pre_pr_30d_hotspot_fixes
            FROM v_jev_szz_joined
            WHERE uncensored_14d = 1
        """).fetchall():
            pre_vals_by_arm[str(arm_name)].append(float(pre_fix_30d))

        # Symmetric 14d-vs-14d DiD proxy over uncensored_14d == 1
        did_14d_by_arm: dict[str, list[float]] = defaultdict(list)
        if has_hotspot_14d:
            for arm_name, pre_fix_14d, b14 in con.execute("""
                SELECT arm, pre_pr_14d_hotspot_fixes, szz_bugfix_14d
                FROM v_jev_szz_joined
                WHERE uncensored_14d = 1
            """).fetchall():
                did_14d_by_arm[str(arm_name)].append(
                    float(b14) - (1.0 if float(pre_fix_14d) > 0 else 0.0)
                )
        else:
            log.warning(
                "pre_pr_14d_hotspot_fixes absent in %s; omitting 14d-vs-14d symmetric DiD.",
                f_szz,
            )

        # Symmetric 30d-vs-30d DiD proxy over uncensored_30d == 1
        did_30d_by_arm: dict[str, list[float]] = defaultdict(list)
        for arm_name, pre_fix_30d, b30 in con.execute("""
            SELECT arm, pre_pr_30d_hotspot_fixes, szz_bugfix_30d
            FROM v_jev_szz_joined
            WHERE uncensored_30d = 1
        """).fetchall():
            did_30d_by_arm[str(arm_name)].append(
                float(b30) - (1.0 if float(pre_fix_30d) > 0 else 0.0)
            )

        # Within-repo Cold-File MH test: Jev_Flagged vs Jev_Clean and Jev_Any vs No_Bot_Control
        cold_mh_flagged_vs_clean = _mantel_haenszel([
            (str(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]))
            for r in con.execute("""
                SELECT
                    repo_full_name || '::' || author_origin AS stratum,
                    SUM(CASE WHEN arm = 'Jev_Flagged' THEN szz_bugfix_14d ELSE 0 END) AS kt,
                    SUM(CASE WHEN arm = 'Jev_Flagged' THEN 1 ELSE 0 END) AS nt,
                    SUM(CASE WHEN arm = 'Jev_Clean' THEN szz_bugfix_14d ELSE 0 END) AS kc,
                    SUM(CASE WHEN arm = 'Jev_Clean' THEN 1 ELSE 0 END) AS nc
                FROM v_jev_szz_joined
                WHERE uncensored_14d = 1 AND pre_pr_30d_hotspot_fixes = 0
                GROUP BY 1 HAVING nt > 0 AND nc > 0
            """).fetchall()
        ])
        cold_mh_jev_vs_nobot = _mantel_haenszel([
            (str(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]))
            for r in con.execute("""
                SELECT
                    repo_full_name || '::' || author_origin AS stratum,
                    SUM(CASE WHEN arm IN ('Jev_Flagged', 'Jev_Clean') THEN szz_bugfix_14d ELSE 0 END) AS kt,
                    SUM(CASE WHEN arm IN ('Jev_Flagged', 'Jev_Clean') THEN 1 ELSE 0 END) AS nt,
                    SUM(CASE WHEN arm = 'No_Bot_Control' THEN szz_bugfix_14d ELSE 0 END) AS kc,
                    SUM(CASE WHEN arm = 'No_Bot_Control' THEN 1 ELSE 0 END) AS nc
                FROM v_jev_szz_joined
                WHERE uncensored_14d = 1 AND pre_pr_30d_hotspot_fixes = 0
                GROUP BY 1 HAVING nt > 0 AND nc > 0
            """).fetchall()
        ])

        hotspot_control = {
            "status": "computed",
            "cold_vs_hot_strata_u14": [
                {
                    "file_heat": r[0],
                    "arm": r[1],
                    "n_u14": int(r[2]),
                    "bug14": int(r[3]),
                    "bug14_pct": _safe_rate(int(r[3]), int(r[2])),
                    "bug14_ci95_pct": _wilson_pct(int(r[3]), int(r[2])),
                    "n_u30": int(r[4]),
                    "bug30": int(r[5]),
                    "bug30_pct": _safe_rate(int(r[5]), int(r[4])),
                    "mean_pre_pr_30d_hotspot_fixes": float(r[6]),
                }
                for r in hs_rows
            ],
            "selection_bias_pre_hotspot_mw_flagged_vs_clean": _mann_whitney(
                pre_vals_by_arm.get("Jev_Flagged", []),
                pre_vals_by_arm.get("Jev_Clean", []),
            ),
            "did_proxy_14d_vs_14d_symmetric_by_arm": (
                {
                    arm: {
                        "n": len(vals),
                        "mean_did_delta": round(float(np.mean(vals)), 4),
                    }
                    for arm, vals in sorted(did_14d_by_arm.items())
                    if vals
                }
                if has_hotspot_14d
                else {"status": "missing_pre_pr_14d_hotspot_fixes_in_ledger"}
            ),
            "did_proxy_30d_vs_30d_symmetric_by_arm": {
                arm: {
                    "n": len(vals),
                    "mean_did_delta": round(float(np.mean(vals)), 4),
                }
                for arm, vals in sorted(did_30d_by_arm.items())
                if vals
            },
            "cold_files_within_repo_mh_flagged_vs_clean_14d": cold_mh_flagged_vs_clean,
            "cold_files_within_repo_mh_jev_vs_nobot_14d": cold_mh_jev_vs_nobot,
        }

    # ------------------------------------------------------------------
    # PART B3: Post-Jev Pre-Merge Fix Mediation Test
    # ------------------------------------------------------------------
    log.info("Part B3: Running Post-Jev Pre-Merge Fix Mediation Test among merged Jev_Flagged PRs")
    med_rows_14 = con.execute("""
        SELECT
            CASE WHEN post_jev_fix_commits > 0 THEN 'Acted_PostJev_Fix (>=1 commit)' ELSE 'Ignored_No_PostJev_Fix (0 commits)' END AS mediation_arm,
            COUNT(*) AS n,
            SUM(szz_bugfix_14d) AS bug14,
            SUM(reverted_14d) AS rev14,
            SUM(CASE WHEN uncensored_30d = 1 THEN 1 ELSE 0 END) AS n_u30,
            SUM(CASE WHEN uncensored_30d = 1 THEN szz_bugfix_30d ELSE 0 END) AS bug30
        FROM v_jev_szz_joined
        WHERE arm = 'Jev_Flagged'
          AND has_commit_timeline = 1
          AND uncensored_14d = 1
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    med_map = {r[0]: r for r in med_rows_14}
    acted = med_map.get("Acted_PostJev_Fix (>=1 commit)")
    ignored = med_map.get("Ignored_No_PostJev_Fix (0 commits)")
    mediation_test = {
        "arms_u14": [
            {
                "mediation_arm": r[0],
                "n_u14": int(r[1]),
                "bug14": int(r[2]),
                "bug14_pct": _safe_rate(int(r[2]), int(r[1])),
                "bug14_ci95_pct": _wilson_pct(int(r[2]), int(r[1])),
                "rev14": int(r[3]),
                "n_u30": int(r[4]),
                "bug30": int(r[5]),
                "bug30_pct": _safe_rate(int(r[5]), int(r[4])),
            }
            for r in med_rows_14
        ],
        "acted_vs_ignored_14d_test": (
            {
                **two_prop_z_test(int(ignored[2]), int(ignored[1]), int(acted[2]), int(acted[1])),
                "fisher_p": fisher_exact_2x2(int(ignored[2]), int(ignored[1]), int(acted[2]), int(acted[1])),
            }
            if acted and ignored
            else {"status": "insufficient_arms"}
        ),
    }

    # BH-FDR across key p-values in NQ-01 & NQ-02
    raw_p_items: list[tuple[str, float]] = []
    for origin, tests_d in flagged_vs_clean_tests.items():
        for tname, res in tests_d.items():
            if "p_value" in res and res["p_value"] is not None:
                raw_p_items.append((f"nq01::{origin}::{tname}", float(res["p_value"])))
    for w_key, szz_obj in (("14d", szz_14d), ("30d", szz_30d)):
        for origin, cmp_d in szz_obj["mantel_haenszel_within_repo_matched"].items():
            for cname, res in cmp_d.items():
                if res.get("cmh_p_value") is not None:
                    raw_p_items.append((f"nq02_{w_key}::{origin}::{cname}", float(res["cmh_p_value"])))

    fdr_adjusted = {}
    if raw_p_items:
        q_vals = bh_fdr([p for _, p in raw_p_items])
        fdr_adjusted = {
            k: {"raw_p": round(p, 6), "bh_fdr_q": round(q, 6)}
            for (k, p), q in zip(raw_p_items, q_vals)
        }

    results: dict[str, Any] = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signals_source": str(f_sigs),
        "szz_ledger_source": str(f_szz),
        "nq01_jev_verbosity_and_human_judgment": {
            "bot_family_verbosity": bot_family_verbosity,
            "regime_engagement_and_hydration": regime_summary,
            "hydrated_repos": list(HYDRATED_JEV_REPOS),
            "hydrated_by_verdict_and_origin": hydrated_by_verdict_origin,
            "hydrated_jev_verbosity_quartiles": hydrated_jev_quartiles,
            "flagged_vs_clean_hypothesis_tests": flagged_vs_clean_tests,
            "within_repo_verbosity_vs_judgment_sentry": sentry_corr,
            "aidev_cohort_c_verbosity_vs_judgment": aidev_cohort_c_corr,
        },
        "nq02_jev_bare_git_szz_outcomes": {
            "szz_14d_uncensored": szz_14d,
            "szz_30d_uncensored": szz_30d,
            "pre_pr_30d_hotspot_confounding_control": hotspot_control,
            "post_jev_pre_merge_fix_mediation_test": mediation_test,
        },
        "bh_fdr_adjusted_p_values": fdr_adjusted,
        "log_file": str(ts_log_path),
    }

    out_json = paths.results_dir / "jev_judgment_and_szz_outcomes.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    log.info("Wrote JSON results -> %s", out_json)

    # Generate Markdown report with mandatory Rule-0 YAML frontmatter
    md_lines: list[str] = [
        yaml_frontmatter(
            title="Jev Decision-Model Tollgates: Human Judgment (NQ-01) & Bare-Git SZZ Outcomes (NQ-02)",
            intent="Empirical evaluation of compact Jev decision-model tollgates vs verbose prose bots on human formal review judgment, corrective commits, and within-repo bare-git SZZ post-release bugfix outcomes.",
            doc_type="study-protocol",
            status="active",
            skills=["empirical-methodologist"],
        ).rstrip("\n"),
        "# Jev Decision-Model Tollgates: Human Judgment (NQ-01) & Bare-Git SZZ Outcomes (NQ-02)",
        "",
        f"**Generated (UTC):** `{results['generated_at_utc']}`  ",
        f"**Signals Source:** `{f_sigs.name}` | **SZZ Ledger:** `{f_szz.name}`",
        "",
        "## 1. NQ-01: Verbosity, Information Density & Human Engagement Across Regimes",
        "",
        "| Regime | PRs | Merged % (95% CI) | Median Bot Chars | Post-Bot Human Comment % | Formal Review Hydration % |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in regime_summary:
        med_c = f"{r['median_bot_chars']:.1f}" if r["median_bot_chars"] is not None else "N/A"
        ci = r["merge_rate_ci95_pct"]
        md_lines.append(
            f"| `{r['regime']}` | {r['prs_total']:,} | {r['merge_rate_pct']:.2f}% [{ci[0]:.1f}, {ci[1]:.1f}] | "
            f"{med_c} | {r['pct_with_post_bot_human_comment']:.2f}% | "
            f"{r['formal_review_human_hydration_pct']:.2f}% ({r['formal_review_human_hydrated_prs']}/{r['prs_total']}) |"
        )

    md_lines.extend([
        "",
        "### Hydrated Jev Repos (`getsentry/sentry`, `craftmilldev/loopway`, `craftmilldev/sesh`) Formal Judgment",
        "",
        "| Stratum | PRs | Merge % | Pre-Review Self-Close % | Human Reviewed | CR % | Substantive (>20c) % | Post-Jev Commit % |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in hydrated_by_verdict_origin:
        md_lines.append(
            f"| `{r['stratum']}` | {r['prs']:,} | {r['merge_rate_pct']:.2f}% | {r['pre_review_self_closure_pct']:.2f}% | "
            f"{r['prs_with_human_formal_review']:,} | {r['cr_among_reviewed_pct']:.2f}% | "
            f"{r['substantive_among_reviewed_pct']:.2f}% | {r['post_jev_corrective_commit_pct']:.2f}% |"
        )

    md_lines.extend([
        "",
        "### Verbosity vs. Human Judgment Correlations",
        f"- **`getsentry/sentry`** (`n={sentry_corr['n_all_bot_prs']}`, formal reviewed `n={sentry_corr['n_formal_reviewed_prs']}`): "
        f"Spearman `rho(log_bot_chars, post_bot_human_comment) = {sentry_corr['spearman_log_bot_chars_vs_post_bot_human_comment']['rho']}` "
        f"(p={sentry_corr['spearman_log_bot_chars_vs_post_bot_human_comment']['p_value']}); "
        f"`rho(log_bot_chars, human_CR) = {sentry_corr['spearman_log_bot_chars_vs_human_cr_reviewed']['rho']}`; "
        f"`rho(log_bot_chars, rubber_stamp) = {sentry_corr['spearman_log_bot_chars_vs_rubber_stamp']['rho']}`.",
    ])
    if "n_cohort_c_with_bot_chars" in aidev_cohort_c_corr:
        md_lines.append(
            f"- **`AIDev` Cohort C** (`n={aidev_cohort_c_corr['n_cohort_c_with_bot_chars']}`): "
            f"Spearman `rho(log_bot_chars, human_CR) = {aidev_cohort_c_corr['spearman_log_bot_chars_vs_human_cr']['rho']}` "
            f"(p={aidev_cohort_c_corr['spearman_log_bot_chars_vs_human_cr']['p_value']}); "
            f"`rho(log_bot_chars, rubber_stamp) = {aidev_cohort_c_corr['spearman_log_bot_chars_vs_rubber_stamp']['rho']}` "
            f"(p={aidev_cohort_c_corr['spearman_log_bot_chars_vs_rubber_stamp']['p_value']})."
        )

    md_lines.extend([
        "",
        "## 2. NQ-02: Commit-Attributed Bare-Git SZZ Outcomes (14d & 30d Uncensored)",
        "",
        "| Window | Author Origin | Arm | N | SZZ Bugs | SZZ Bugfix % (95% CI) | Reverts | Mean File Survival % |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for win_lbl, szz_obj in (("14d", szz_14d), ("30d", szz_30d)):
        for r in szz_obj["pooled_by_origin_arm"]:
            ci = r["szz_bugfix_ci95_pct"]
            sv = f"{r['mean_file_survival_pct']:.2f}%" if r["mean_file_survival_pct"] is not None else "N/A"
            md_lines.append(
                f"| {win_lbl} | `{r['author_origin']}` | `{r['arm']}` | {r['n']:,} | {r['szz_bugs']:,} | "
                f"{r['szz_bugfix_pct']:.2f}% [{ci[0]:.1f}, {ci[1]:.1f}] | {r['reverts']:,} | {sv} |"
            )

    md_lines.extend([
        "",
        "### Mantel-Haenszel Within-Repo Matched Summaries (Simpson's Paradox Guardrail)",
        "",
        "| Window | Cohort | Comparison | Matched Strata | Treat k/n (%) | Ctrl k/n (%) | MH Odds Ratio (95% CI) | CMH p-value |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for win_lbl, szz_obj in (("14d", szz_14d), ("30d", szz_30d)):
        for origin, cmp_d in szz_obj["mantel_haenszel_within_repo_matched"].items():
            for cname, mh in cmp_d.items():
                if mh["matched_repos_count"] == 0:
                    continue
                or_str = f"{mh['or_mh']} {mh['or_ci95']}" if mh["or_mh"] is not None else "N/A"
                p_str = f"{mh['cmh_p_value']:.4g}" if mh["cmh_p_value"] is not None else "N/A"
                md_lines.append(
                    f"| {win_lbl} | `{origin}` | `{cname}` | {mh['matched_repos_count']} | "
                    f"{mh['treat_k']}/{mh['treat_n']} ({mh['treat_rate_pct']:.2f}%) | "
                    f"{mh['ctrl_k']}/{mh['ctrl_n']} ({mh['ctrl_rate_pct']:.2f}%) | {or_str} | {p_str} |"
                )

    md_lines.extend([
        "",
        "### Hotspot Confounding Control & Post-Jev Pre-Merge Fix Mediation",
        f"- **Hotspot control status:** `{hotspot_control.get('status')}`",
        f"- **Mediation arms (u14 Jev_Flagged with commit timelines):** {len(mediation_test['arms_u14'])} arms evaluated.",
        "",
        "## 3. Generated Audit Artifacts",
        f"- JSON summary: `{out_json.name}`",
        f"- Within-repo SZZ CSV: `{out_szz_csv.name}`",
        f"- Verbosity vs. judgment CSV: `{out_verbosity_csv.name}`",
        f"- Verbose log: `{ts_log_path.name}`",
        "",
    ])

    out_md = paths.results_dir / "JEV_JUDGMENT_AND_SZZ_REPORT.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    log.info("Wrote Markdown report -> %s", out_md)

    return results


def main() -> None:
    run_p16()


if __name__ == "__main__":
    main()
