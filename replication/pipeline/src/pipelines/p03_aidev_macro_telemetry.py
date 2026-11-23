#!/usr/bin/env python3
"""
Pipeline p03: Reproducible MSR Empirical Analysis on the AIDev Corpus (Li et al., MSR 2026)
==========================================================================================
Executes macro telemetry, cohort stratification (Clean 38-Bot Catalog), Coarsened Exact
Matching (CEM), 810-repository paired human-vs-agent controls, and Mode I / Mode II
execution stratification over the AIDev corpus.

Outputs:
  - results/msr_aidev_results.json
  - results/data_tables/analyzed_repositories_log.csv
  - results/data_tables/analyzed_human_reviewed_prs_log.csv
  - results/data_tables/aidev_operator_config_prs_log.csv
  - results/data_tables/aidev_execution_modes_and_task_penalties_log.csv
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

import duckdb
import numpy as np
from scipy import stats

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.bot_catalog import TIER1_PR_COMMENTS_BOTS, TIER1_REVIEW_BOTS, sql_in_list
from config.paths import get_paths
from src.utils.logging_utils import setup_verbose_logger
from src.utils.stats_utils import bh_fdr


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def cliffs_delta_and_a12(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 1.0, 0.5, 0.0
    u_stat, p_val = stats.mannwhitneyu(x, y, alternative="two-sided")
    a12 = float(u_stat) / float(nx * ny)
    delta = 2.0 * a12 - 1.0
    return float(p_val), round(a12, 4), round(delta, 4)


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    logger, ts_log_path = setup_verbose_logger(
        "p03_aidev_macro_telemetry",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    logger.info("Timestamped log: %s", ts_log_path)

    data_dir = paths.scratch_dir / "aidev"
    out_json = paths.results_dir / "msr_aidev_results.json"
    out_repos_csv = paths.tables_dir / "analyzed_repositories_log.csv"
    out_prs_csv = paths.tables_dir / "analyzed_human_reviewed_prs_log.csv"
    out_config_prs_csv = paths.tables_dir / "aidev_operator_config_prs_log.csv"
    out_exec_modes_csv = paths.tables_dir / "aidev_execution_modes_and_task_penalties_log.csv"

    run_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con = duckdb.connect()
    bot_sql = sql_in_list(TIER1_REVIEW_BOTS)
    bot_comm_sql = sql_in_list(TIER1_PR_COMMENTS_BOTS)

    parquet_files = [
        "pull_request.parquet",
        "human_pull_request.parquet",
        "pr_reviews.parquet",
        "pr_review_comments.parquet",
        "pr_review_comments_v2.parquet",
        "pr_comments.parquet",
        "pr_commits.parquet",
        "related_issue.parquet",
        "pr_task_type.parquet",
        "repository.parquet",
        "user.parquet",
    ]
    input_manifest: dict[str, dict[str, object]] = {}
    logger.info("Starting MSR AIDev analysis run at %s (data_dir=%s)", run_ts, data_dir)
    for pf in parquet_files:
        fp = data_dir / pf
        if not fp.exists():
            raise FileNotFoundError(f"Missing required AIDev Parquet file: {fp}")
        row_cnt = con.execute(f'SELECT count(*) FROM "{fp}"').fetchone()[0]
        sz = os.path.getsize(fp)
        digest = sha256_file(fp)
        input_manifest[pf] = {
            "size_bytes": sz,
            "row_count": row_cnt,
            "sha256": digest,
        }
        logger.info("Verified Parquet input %-28s | rows=%-8d | bytes=%-10d | sha256=%s", pf, row_cnt, sz, digest[:16])

    # 1. Macro Corpus Overview (Agentic PRs vs. Human Baseline PRs)
    agent_macro = con.execute(
        f"""
        SELECT
            count(*) AS total_prs,
            sum(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
            sum(CASE WHEN state = 'closed' AND merged_at IS NULL THEN 1 ELSE 0 END) AS rejected_closed_prs,
            avg(length(coalesce(body, ''))) AS avg_pr_body_chars
        FROM "{data_dir}/pull_request.parquet"
        """
    ).fetchone()

    human_macro = con.execute(
        f"""
        SELECT
            count(*) AS total_prs,
            sum(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
            sum(CASE WHEN state = 'closed' AND merged_at IS NULL THEN 1 ELSE 0 END) AS rejected_closed_prs,
            avg(length(coalesce(body, ''))) AS avg_pr_body_chars
        FROM "{data_dir}/human_pull_request.parquet"
        """
    ).fetchone()

    # 2. Extract Per-PR Feature Table for All Agentic PRs (Clean 38-Bot Catalog)
    pr_query = f"""
    WITH bot_events AS (
        SELECT pr_id, user AS bot_user FROM "{data_dir}/pr_reviews.parquet" WHERE user IN ({bot_sql})
        UNION
        SELECT pr_id, user AS bot_user FROM "{data_dir}/pr_comments.parquet" WHERE user IN ({bot_comm_sql})
        UNION
        SELECT rv.pr_id, rc.user AS bot_user
        FROM "{data_dir}/pr_review_comments_v2.parquet" rc
        JOIN "{data_dir}/pr_reviews.parquet" rv ON rc.pull_request_review_id = rv.id
        WHERE rc.user IN ({bot_sql}) AND rv.user != 'copilot-swe-agent[bot]'
    ),
    bot_prs AS (
        SELECT pr_id, string_agg(DISTINCT bot_user, ';' ORDER BY bot_user) AS bot_list
        FROM bot_events
        GROUP BY pr_id
    ),
    human_rev AS (
        SELECT
            r.pr_id,
            count(*) AS human_review_count,
            sum(CASE WHEN r.state = 'APPROVED' THEN 1 ELSE 0 END) AS human_approvals,
            sum(CASE WHEN r.state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS human_changes_req,
            sum(CASE WHEN r.state = 'COMMENTED' THEN 1 ELSE 0 END) AS human_commented_reviews,
            avg(length(coalesce(r.body, ''))) AS avg_review_body_chars,
            sum(CASE WHEN r.state = 'APPROVED' AND length(trim(coalesce(r.body, ''))) <= 15 THEN 1 ELSE 0 END) AS lgtm_empty_approvals
        FROM "{data_dir}/pr_reviews.parquet" r
        WHERE r.user_type = 'User' AND r.user NOT LIKE '%[bot]%' AND LOWER(r.user) NOT LIKE '%-bot'
        GROUP BY r.pr_id
    ),
    human_inline AS (
        SELECT
            r.pr_id,
            count(ic.id) AS human_inline_comments,
            avg(length(coalesce(ic.body, ''))) AS avg_inline_chars,
            sum(CASE WHEN regexp_matches(lower(coalesce(ic.body, '')),
                '(architecture|invariant|state|race|lock|security|auth|token|csrf|boundary|contract|leak|idempoten|transaction)')
                THEN 1 ELSE 0 END) AS arch_security_comments
        FROM "{data_dir}/pr_reviews.parquet" r
        JOIN "{data_dir}/pr_review_comments.parquet" ic ON ic.pull_request_review_id = r.id
        WHERE ic.user_type = 'User' AND ic.user NOT LIKE '%[bot]%' AND LOWER(ic.user) NOT LIKE '%-bot'
        GROUP BY r.pr_id
    ),
    commits_agg AS (
        SELECT
            pr_id,
            count(*) AS commit_count,
            sum(CASE WHEN regexp_matches(lower(coalesce(message, '')),
                '(revert|fixup|hotfix|bug|vulnerability|broken|regression)')
                THEN 1 ELSE 0 END) AS corrective_commits,
            sum(CASE WHEN regexp_matches(lower(coalesce(message, '')),
                '(doc|adr|spec|contract|readme|test)')
                THEN 1 ELSE 0 END) AS spec_test_commits
        FROM "{data_dir}/pr_commits.parquet"
        GROUP BY pr_id
    ),
    rel_iss AS (
        SELECT DISTINCT pr_id FROM "{data_dir}/related_issue.parquet"
    )
    SELECT
        p.id AS pr_id,
        p.agent,
        p.state,
        p.merged_at IS NOT NULL AS is_merged,
        b.pr_id IS NOT NULL AS has_tier1_bot,
        coalesce(hr.human_review_count, 0) AS human_review_count,
        coalesce(hr.human_approvals, 0) AS human_approvals,
        coalesce(hr.human_changes_req, 0) AS human_changes_req,
        coalesce(hr.avg_review_body_chars, 0.0) AS avg_review_body_chars,
        coalesce(hr.lgtm_empty_approvals, 0) AS lgtm_empty_approvals,
        coalesce(hi.human_inline_comments, 0) AS human_inline_comments,
        coalesce(hi.avg_inline_chars, 0.0) AS avg_inline_chars,
        coalesce(hi.arch_security_comments, 0) AS arch_security_comments,
        coalesce(ca.commit_count, 1) AS commit_count,
        coalesce(ca.corrective_commits, 0) AS corrective_commits,
        coalesce(ca.spec_test_commits, 0) AS spec_test_commits,
        ri.pr_id IS NOT NULL AS has_linked_issue,
        length(trim(coalesce(p.body, ''))) AS pr_body_chars,
        coalesce(repo.stars, 100) AS repo_stars,
        coalesce(tt.type, 'other') AS task_type,
        coalesce(repo.full_name, 'unknown') AS repo_full_name,
        p.number AS pr_number,
        p.html_url AS html_url,
        coalesce(b.bot_list, '') AS tier1_bots_list,
        p.repo_id AS repo_id
    FROM "{data_dir}/pull_request.parquet" p
    LEFT JOIN bot_prs b ON p.id = b.pr_id
    LEFT JOIN human_rev hr ON p.id = hr.pr_id
    LEFT JOIN human_inline hi ON p.id = hi.pr_id
    LEFT JOIN commits_agg ca ON p.id = ca.pr_id
    LEFT JOIN rel_iss ri ON p.id = ri.pr_id
    LEFT JOIN "{data_dir}/repository.parquet" repo ON p.repo_id = repo.id
    LEFT JOIN "{data_dir}/pr_task_type.parquet" tt ON p.id = tt.id
    ORDER BY p.id
    """
    rows = con.execute(pr_query).fetchall()

    def compute_ibd(r) -> int:
        is_functional = r[19] in ("feat", "fix", "refactor", "perf")
        lacks_traceability = (not r[16]) and (r[15] == 0 or r[17] < 100)
        return 1 if (is_functional and lacks_traceability) else 0

    def compute_rubber_stamp(r) -> int:
        return 1 if (r[6] > 0 and r[10] == 0 and r[9] > 0) else 0

    def compute_ii(r) -> float:
        return float(r[10]) / max(1.0, float(r[13]))

    # Write analyzed_repositories_log.csv
    repo_rows = con.execute(
        f"""
        WITH bot_prs AS (
            SELECT DISTINCT pr_id FROM "{data_dir}/pr_reviews.parquet" WHERE user IN ({bot_sql})
            UNION
            SELECT DISTINCT pr_id FROM "{data_dir}/pr_comments.parquet" WHERE user IN ({bot_comm_sql})
            UNION
            SELECT DISTINCT rv.pr_id
            FROM "{data_dir}/pr_review_comments_v2.parquet" rc
            JOIN "{data_dir}/pr_reviews.parquet" rv ON rc.pull_request_review_id = rv.id
            WHERE rc.user IN ({bot_sql}) AND rv.user != 'copilot-swe-agent[bot]'
        ),
        human_rev AS (
            SELECT DISTINCT pr_id
            FROM "{data_dir}/pr_reviews.parquet"
            WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot'
        ),
        repo_agg AS (
            SELECT
                p.repo_id,
                count(*) AS agent_prs_total,
                sum(CASE WHEN p.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS agent_prs_merged,
                sum(CASE WHEN hr.pr_id IS NOT NULL THEN 1 ELSE 0 END) AS human_reviewed_prs,
                sum(CASE WHEN hr.pr_id IS NOT NULL AND b.pr_id IS NULL THEN 1 ELSE 0 END) AS cohort_b_human_only_prs,
                sum(CASE WHEN hr.pr_id IS NOT NULL AND b.pr_id IS NOT NULL THEN 1 ELSE 0 END) AS cohort_c_tier1_bot_prs
            FROM "{data_dir}/pull_request.parquet" p
            LEFT JOIN bot_prs b ON p.id = b.pr_id
            LEFT JOIN human_rev hr ON p.id = hr.pr_id
            GROUP BY p.repo_id
        )
        SELECT
            r.id AS repo_id,
            r.full_name,
            coalesce(r.language, 'Unknown') AS language,
            r.stars,
            r.forks,
            coalesce(r.license, 'None') AS license,
            coalesce(ra.agent_prs_total, 0) AS agent_prs_total,
            coalesce(ra.agent_prs_merged, 0) AS agent_prs_merged,
            coalesce(ra.human_reviewed_prs, 0) AS human_reviewed_prs,
            coalesce(ra.cohort_b_human_only_prs, 0) AS cohort_b_human_only_prs,
            coalesce(ra.cohort_c_tier1_bot_prs, 0) AS cohort_c_tier1_bot_prs
        FROM "{data_dir}/repository.parquet" r
        LEFT JOIN repo_agg ra ON r.id = ra.repo_id
        ORDER BY r.stars DESC, r.id ASC
        """
    ).fetchall()

    with open(out_repos_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "repo_id",
            "full_name",
            "github_url",
            "language",
            "stars",
            "forks",
            "license",
            "agent_prs_total",
            "agent_prs_merged",
            "human_reviewed_prs",
            "cohort_b_human_only_prs",
            "cohort_c_tier1_bot_prs",
        ])
        for rr in repo_rows:
            w.writerow([
                rr[0],
                rr[1],
                f"https://github.com/{rr[1]}",
                rr[2],
                rr[3],
                rr[4],
                rr[5],
                rr[6],
                rr[7],
                rr[8],
                rr[9],
                rr[10],
            ])

    # Partition Human-Reviewed Agent PRs into Cohort B (Human-Only) and Cohort C (Tier-1 Bot + Human)
    reviewed_b = [r for r in rows if (r[5] > 0 and not r[4])]
    reviewed_c = [r for r in rows if (r[5] > 0 and r[4])]
    all_human_reviewed = [r for r in rows if r[5] > 0]

    with open(out_prs_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "pr_id",
            "repo_full_name",
            "pr_number",
            "html_url",
            "agent",
            "cohort",
            "tier1_bots_list",
            "state",
            "is_merged",
            "human_review_count",
            "human_approvals",
            "human_changes_req",
            "human_inline_comments",
            "inspection_intensity_inline_per_commit",
            "commit_count",
            "corrective_commits",
            "task_type",
            "has_linked_issue",
            "intent_rationale_deficit_ibd",
            "rubber_stamp_approval",
        ])
        for r in all_human_reviewed:
            w.writerow([
                r[0],
                r[20],
                r[21],
                r[22],
                r[1],
                "Cohort_C_Tier1_Bot_Plus_Human" if r[4] else "Cohort_B_Human_Only",
                r[23],
                r[2],
                int(r[3]),
                r[5],
                r[6],
                r[7],
                r[10],
                round(compute_ii(r), 4),
                r[13],
                r[14],
                r[19],
                int(r[16]),
                compute_ibd(r),
                compute_rubber_stamp(r),
            ])

    # Operator config PRs log
    config_pr_rows = con.execute(
        f"""
        SELECT DISTINCT
            p.id AS pr_id,
            repo.full_name AS repo_full_name,
            p.number AS pr_number,
            p.html_url,
            p.agent,
            p.state,
            p.merged_at IS NOT NULL AS is_merged,
            ic.path AS touched_protected_path
        FROM "{data_dir}/pr_review_comments.parquet" ic
        JOIN "{data_dir}/pr_reviews.parquet" r ON ic.pull_request_review_id = r.id
        JOIN "{data_dir}/pull_request.parquet" p ON r.pr_id = p.id
        LEFT JOIN "{data_dir}/repository.parquet" repo ON p.repo_id = repo.id
        WHERE regexp_matches(ic.path, '(CLAUDE\\.md|AGENTS\\.md|GEMINI\\.md|\\.cursor|\\.github/workflows/)')
        ORDER BY p.id ASC, ic.path ASC
        """
    ).fetchall()

    with open(out_config_prs_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "pr_id",
            "repo_full_name",
            "pr_number",
            "html_url",
            "agent",
            "state",
            "is_merged",
            "touched_protected_path",
        ])
        for cr in config_pr_rows:
            w.writerow([cr[0], cr[1], cr[2], cr[3], cr[4], cr[5], int(cr[6]), cr[7]])

    metrics_spec = [
        ("merge_rate", lambda r: 1.0 if r[3] else 0.0),
        ("human_changes_requested_per_pr", lambda r: float(r[7])),
        ("any_human_changes_requested_rate", lambda r: 1.0 if r[7] > 0 else 0.0),
        ("human_review_body_chars", lambda r: float(r[8])),
        ("human_inline_comments_per_pr", lambda r: float(r[10])),
        ("inspection_intensity_inline_per_commit", compute_ii),
        ("rubber_stamp_approval_rate", compute_rubber_stamp),
        ("arch_security_inline_comments_per_pr", lambda r: float(r[12])),
        ("commit_churn_per_pr", lambda r: float(r[13])),
        ("corrective_fix_commits_per_pr", lambda r: float(r[14])),
        ("intent_rationale_deficit_ibd_rate", compute_ibd),
        ("merged_unattested_intent_debt_rate", lambda r: 1.0 if (r[3] and compute_ibd(r) == 1 and r[10] == 0) else 0.0),
    ]

    cohort_comparisons: dict[str, dict[str, float]] = {}
    raw_pvals: list[float] = []
    metric_keys: list[str] = []

    for m_name, fn in metrics_spec:
        vb = np.array([fn(r) for r in reviewed_b], dtype=float)
        vc = np.array([fn(r) for r in reviewed_c], dtype=float)
        pval, a12, delta = cliffs_delta_and_a12(vc, vb)
        raw_pvals.append(pval)
        metric_keys.append(m_name)
        rel_diff_pct = ((vc.mean() - vb.mean()) / vb.mean() * 100.0) if vb.mean() != 0 else 0.0
        cohort_comparisons[m_name] = {
            "cohort_b_human_only_mean": round(float(vb.mean()), 4),
            "cohort_b_human_only_median": round(float(np.median(vb)), 4),
            "cohort_c_tier1_bot_plus_human_mean": round(float(vc.mean()), 4),
            "cohort_c_tier1_bot_plus_human_median": round(float(np.median(vc)), 4),
            "relative_shift_pct": round(float(rel_diff_pct), 2),
            "mann_whitney_p": pval,
            "vargha_delaney_a12": a12,
            "cliffs_delta": delta,
        }

    q_vals = bh_fdr(raw_pvals)
    for k, q in zip(metric_keys, q_vals):
        cohort_comparisons[k]["bh_fdr_q"] = q

    # 3. Coarsened Exact Matching (CEM) Control
    def stratum_key(r):
        c_cnt = r[13]
        c_bucket = "1" if c_cnt == 1 else ("2-3" if c_cnt <= 3 else ("4-7" if c_cnt <= 7 else "8+"))
        stars = r[18]
        s_bucket = "100-500" if stars <= 500 else ("501-2500" if stars <= 2500 else "2501+")
        return (r[19], c_bucket, s_bucket)

    strata_b: dict[tuple, list] = {}
    strata_c: dict[tuple, list] = {}
    for r in reviewed_b:
        strata_b.setdefault(stratum_key(r), []).append(r)
    for r in reviewed_c:
        strata_c.setdefault(stratum_key(r), []).append(r)

    matched_b, matched_c = [], []
    for sk, c_list in sorted(strata_c.items()):
        b_list = strata_b.get(sk, [])
        k = min(len(c_list), len(b_list))
        if k > 0:
            matched_b.extend(sorted(b_list, key=lambda r: hashlib.sha256(str(r[0]).encode()).hexdigest())[:k])
            matched_c.extend(sorted(c_list, key=lambda r: hashlib.sha256(str(r[0]).encode()).hexdigest())[:k])

    cem_results: dict[str, object] = {"matched_pairs_n": len(matched_c), "metrics": {}}
    for m_name, fn in [
        ("merge_rate", lambda r: 1.0 if r[3] else 0.0),
        ("human_changes_requested_per_pr", lambda r: float(r[7])),
        ("any_human_changes_requested_rate", lambda r: 1.0 if r[7] > 0 else 0.0),
        ("human_review_body_chars", lambda r: float(r[8])),
        ("inspection_intensity_inline_per_commit", compute_ii),
        ("merged_unattested_intent_debt_rate", lambda r: 1.0 if (r[3] and compute_ibd(r) == 1 and r[10] == 0) else 0.0),
    ]:
        vb = np.array([fn(r) for r in matched_b], dtype=float)
        vc = np.array([fn(r) for r in matched_c], dtype=float)
        pval, a12, delta = cliffs_delta_and_a12(vc, vb)
        rel_diff = ((vc.mean() - vb.mean()) / vb.mean() * 100.0) if vb.mean() != 0 else 0.0
        cem_results["metrics"][m_name] = {
            "matched_b_mean": round(float(vb.mean()), 4),
            "matched_c_mean": round(float(vc.mean()), 4),
            "relative_shift_pct": round(float(rel_diff), 2),
            "mann_whitney_p": pval,
            "cliffs_delta": delta,
        }

    # 4. Paired Intra-Repository Matched Control
    q_paired = f"""
    WITH shared_repos AS (
        SELECT DISTINCT r.url as repo_url
        FROM read_parquet('{data_dir}/pull_request.parquet') ai
        JOIN read_parquet('{data_dir}/human_pull_request.parquet') hu
          ON ai.repo_url = hu.repo_url
        JOIN read_parquet('{data_dir}/repository.parquet') r
          ON ai.repo_url = r.url
    )
    SELECT
        'Human' as cohort,
        count(*) as total_prs,
        count(CASE WHEN h.merged_at IS NOT NULL THEN 1 END) as merged_prs,
        round(count(CASE WHEN h.merged_at IS NOT NULL THEN 1 END) * 100.0 / count(*), 2) as merge_rate_pct
    FROM read_parquet('{data_dir}/human_pull_request.parquet') h
    WHERE repo_url IN (SELECT repo_url FROM shared_repos)
    UNION ALL
    SELECT
        'Agent' as cohort,
        count(*) as total_prs,
        count(CASE WHEN a.merged_at IS NOT NULL THEN 1 END) as merged_prs,
        round(count(CASE WHEN a.merged_at IS NOT NULL THEN 1 END) * 100.0 / count(*), 2) as merge_rate_pct
    FROM read_parquet('{data_dir}/pull_request.parquet') a
    WHERE repo_url IN (SELECT repo_url FROM shared_repos);
    """
    paired_rows = con.execute(q_paired).fetchall()
    hu_row = [r for r in paired_rows if r[0] == "Human"][0]
    ai_row = [r for r in paired_rows if r[0] == "Agent"][0]
    hu_rate = float(hu_row[3])
    ai_rate = float(ai_row[3])
    penalty_pp = round(hu_rate - ai_rate, 2)
    q_shared_count = f"""
    SELECT count(DISTINCT r.url)
    FROM read_parquet('{data_dir}/pull_request.parquet') ai
    JOIN read_parquet('{data_dir}/human_pull_request.parquet') hu
      ON ai.repo_url = hu.repo_url
    JOIN read_parquet('{data_dir}/repository.parquet') r
      ON ai.repo_url = r.url
    """
    shared_repo_count = int(con.execute(q_shared_count).fetchone()[0])
    tbl = [[hu_row[2], hu_row[1] - hu_row[2]], [ai_row[2], ai_row[1] - ai_row[2]]]
    chi2_val, p_val, _, _ = stats.chi2_contingency(tbl)
    odds_ratio_val = float((ai_row[2] / (ai_row[1] - ai_row[2])) / (hu_row[2] / (hu_row[1] - hu_row[2])))

    paired_summary = {
        "shared_repos_count": shared_repo_count,
        "human_prs_total": int(hu_row[1]),
        "human_prs_merged": int(hu_row[2]),
        "human_merge_rate_pct": hu_rate,
        "agent_prs_total": int(ai_row[1]),
        "agent_prs_merged": int(ai_row[2]),
        "agent_merge_rate_pct": ai_rate,
        "paired_merge_penalty_pp": penalty_pp,
        "chi2_stat": round(float(chi2_val), 2),
        "p_value": float(p_val),
        "odds_ratio": round(odds_ratio_val, 3),
    }

    # 5. Execution Mode Stratification (Mode I Self-Merged vs Mode II Peer-Merged)
    q_exec_modes = f"""
    WITH hr AS (
        SELECT DISTINCT pr_id
        FROM "{data_dir}/pr_reviews.parquet"
        WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot'
    ),
    merged_actor AS (
        SELECT pr_id, arg_min(actor, try_cast(created_at AS TIMESTAMPTZ)) AS merge_actor
        FROM "{data_dir}/pr_timeline.parquet"
        WHERE event = 'merged' AND actor IS NOT NULL
        GROUP BY pr_id
    ),
    repo_vol AS (
        SELECT repo_id, count(*) AS repo_agent_prs
        FROM "{data_dir}/pull_request.parquet"
        GROUP BY repo_id
    ),
    ca AS (
        SELECT pr_id, count(*) AS commits
        FROM "{data_dir}/pr_commits.parquet"
        GROUP BY pr_id
    )
    SELECT
        CASE WHEN ma.merge_actor = p.user THEN 'Self-Merged (Mode I)' ELSE 'Peer-Merged (Mode II)' END AS exec_mode,
        CASE WHEN p.agent = 'OpenAI_Codex' THEN 'Codex' ELSE 'Non-Codex' END AS agent_family,
        count(*) AS n_prs,
        round(avg(CASE WHEN hr.pr_id IS NULL THEN 100.0 ELSE 0.0 END), 2) AS silent_gate_pct,
        round(median(date_diff('second', try_cast(p.created_at AS TIMESTAMPTZ), try_cast(p.merged_at AS TIMESTAMPTZ)) / 60.0), 2) AS median_merge_minutes,
        round(avg(rv.repo_agent_prs), 1) AS avg_repo_agent_prs,
        round(avg(coalesce(ca.commits, 1)), 2) AS avg_commits
    FROM "{data_dir}/pull_request.parquet" p
    JOIN merged_actor ma ON p.id = ma.pr_id
    JOIN repo_vol rv ON p.repo_id = rv.repo_id
    LEFT JOIN hr ON p.id = hr.pr_id
    LEFT JOIN ca ON p.id = ca.pr_id
    WHERE p.merged_at IS NOT NULL
    GROUP BY 1, 2
    ORDER BY n_prs DESC
    """
    exec_mode_rows = con.execute(q_exec_modes).fetchall()
    execution_modes = [
        {
            "execution_mode": r[0],
            "agent_family": r[1],
            "n_prs": int(r[2]),
            "silent_gate_pct": float(r[3]),
            "median_merge_minutes": float(r[4]),
            "avg_repo_agent_prs": float(r[5]),
            "avg_commits": float(r[6]),
        }
        for r in exec_mode_rows
    ]

    q_per_agent = f"""
    WITH hr AS (
        SELECT DISTINCT pr_id
        FROM "{data_dir}/pr_reviews.parquet"
        WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot'
    ),
    merged_actor AS (
        SELECT pr_id, arg_min(actor, try_cast(created_at AS TIMESTAMPTZ)) AS merge_actor
        FROM "{data_dir}/pr_timeline.parquet"
        WHERE event = 'merged' AND actor IS NOT NULL
        GROUP BY pr_id
    ),
    ca AS (
        SELECT pr_id, count(*) AS commits
        FROM "{data_dir}/pr_commits.parquet"
        GROUP BY pr_id
    )
    SELECT
        p.agent,
        count(*) AS total_prs,
        sum(CASE WHEN p.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
        round(avg(CASE WHEN p.merged_at IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS merge_rate_pct,
        round(avg(CASE WHEN p.merged_at IS NOT NULL AND ma.pr_id IS NOT NULL THEN CASE WHEN ma.merge_actor = p.user THEN 100.0 ELSE 0.0 END ELSE NULL END), 2) AS self_merged_among_matched_pct,
        round(avg(CASE WHEN hr.pr_id IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS human_reviewed_pct,
        round(avg(CASE WHEN hr.pr_id IS NULL THEN 100.0 ELSE 0.0 END), 2) AS silent_gate_pct,
        round(median(CASE WHEN p.merged_at IS NOT NULL THEN date_diff('second', try_cast(p.created_at AS TIMESTAMPTZ), try_cast(p.merged_at AS TIMESTAMPTZ)) / 60.0 ELSE NULL END), 2) AS median_merge_minutes,
        round(avg(coalesce(ca.commits, 1)), 2) AS mean_commits
    FROM "{data_dir}/pull_request.parquet" p
    LEFT JOIN merged_actor ma ON p.id = ma.pr_id
    LEFT JOIN hr ON p.id = hr.pr_id
    LEFT JOIN ca ON p.id = ca.pr_id
    GROUP BY 1
    ORDER BY total_prs DESC
    """
    per_agent_profile = [
        {
            "agent": r[0],
            "total_prs": int(r[1]),
            "merged_prs": int(r[2]),
            "merge_rate_pct": float(r[3]),
            "self_merged_among_matched_pct": float(r[4]) if r[4] is not None else 0.0,
            "human_reviewed_pct": float(r[5]),
            "silent_gate_pct": float(r[6]),
            "median_merge_minutes": float(r[7]) if r[7] is not None else 0.0,
            "mean_commits": float(r[8]),
        }
        for r in con.execute(q_per_agent).fetchall()
    ]

    q_vol_scaling = f"""
    WITH hr AS (
        SELECT DISTINCT pr_id
        FROM "{data_dir}/pr_reviews.parquet"
        WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot'
    ),
    repo_vol AS (
        SELECT repo_id, count(*) AS repo_agent_prs
        FROM "{data_dir}/pull_request.parquet"
        GROUP BY repo_id
    ),
    tagged AS (
        SELECT
            p.id,
            p.agent,
            p.merged_at IS NOT NULL AS is_merged,
            hr.pr_id IS NULL AS is_silent,
            CASE
                WHEN rv.repo_agent_prs <= 2 THEN '1-2 PRs'
                WHEN rv.repo_agent_prs <= 10 THEN '3-10 PRs'
                WHEN rv.repo_agent_prs <= 50 THEN '11-50 PRs'
                ELSE '51+ PRs'
            END AS vol_bucket,
            rv.repo_agent_prs
        FROM "{data_dir}/pull_request.parquet" p
        JOIN repo_vol rv ON p.repo_id = rv.repo_id
        LEFT JOIN hr ON p.id = hr.pr_id
    )
    SELECT
        'All_Agents' AS scope,
        vol_bucket,
        count(*) AS n_prs,
        round(avg(CASE WHEN is_silent THEN 100.0 ELSE 0.0 END), 2) AS silent_pct,
        round(avg(CASE WHEN is_merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
        min(repo_agent_prs) AS sort_key
    FROM tagged
    GROUP BY 1, 2
    UNION ALL
    SELECT
        'Non_Codex_Only' AS scope,
        vol_bucket,
        count(*) AS n_prs,
        round(avg(CASE WHEN is_silent THEN 100.0 ELSE 0.0 END), 2) AS silent_pct,
        round(avg(CASE WHEN is_merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
        min(repo_agent_prs) AS sort_key
    FROM tagged
    WHERE agent != 'OpenAI_Codex'
    GROUP BY 1, 2
    ORDER BY scope, sort_key
    """
    vol_rows = con.execute(q_vol_scaling).fetchall()
    volume_scaling = {
        "all_agents": [
            {"bucket": r[1], "n_prs": int(r[2]), "silent_pct": float(r[3]), "merge_rate_pct": float(r[4])}
            for r in vol_rows if r[0] == "All_Agents"
        ],
        "non_codex_only": [
            {"bucket": r[1], "n_prs": int(r[2]), "silent_pct": float(r[3]), "merge_rate_pct": float(r[4])}
            for r in vol_rows if r[0] == "Non_Codex_Only"
        ],
    }

    q_paired_task = f"""
    WITH shared_repos AS (
        SELECT DISTINCT r.url AS repo_url
        FROM "{data_dir}/pull_request.parquet" ai
        JOIN "{data_dir}/human_pull_request.parquet" hu ON ai.repo_url = hu.repo_url
        JOIN "{data_dir}/repository.parquet" r ON ai.repo_url = r.url
    ),
    hu_t AS (
        SELECT
            coalesce(ht.type, 'unknown') AS task_type,
            count(*) AS hu_n,
            sum(CASE WHEN h.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS hu_merged,
            round(avg(CASE WHEN h.merged_at IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS hu_merge_pct
        FROM "{data_dir}/human_pull_request.parquet" h
        LEFT JOIN "{data_dir}/human_pr_task_type.parquet" ht ON h.id = ht.id
        WHERE h.repo_url IN (SELECT repo_url FROM shared_repos)
        GROUP BY 1
    ),
    ai_t AS (
        SELECT
            coalesce(pt.type, 'unknown') AS task_type,
            count(*) AS ai_n,
            sum(CASE WHEN a.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS ai_merged,
            round(avg(CASE WHEN a.merged_at IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS ai_merge_pct
        FROM "{data_dir}/pull_request.parquet" a
        LEFT JOIN "{data_dir}/pr_task_type.parquet" pt ON a.id = pt.id
        WHERE a.repo_url IN (SELECT repo_url FROM shared_repos)
        GROUP BY 1
    )
    SELECT
        coalesce(hu_t.task_type, ai_t.task_type) AS task_type,
        coalesce(hu_t.hu_n, 0) AS hu_n,
        coalesce(hu_t.hu_merged, 0) AS hu_merged,
        coalesce(hu_t.hu_merge_pct, 0.0) AS hu_merge_pct,
        coalesce(ai_t.ai_n, 0) AS ai_n,
        coalesce(ai_t.ai_merged, 0) AS ai_merged,
        coalesce(ai_t.ai_merge_pct, 0.0) AS ai_merge_pct
    FROM hu_t
    FULL OUTER JOIN ai_t ON hu_t.task_type = ai_t.task_type
    ORDER BY (coalesce(hu_t.hu_n, 0) + coalesce(ai_t.ai_n, 0)) DESC
    """
    paired_task_penalties = []
    for r in con.execute(q_paired_task).fetchall():
        hu_n, ai_n = int(r[1]), int(r[4])
        hu_m, ai_m = float(r[3]), float(r[6])
        if hu_n >= 20 and ai_n >= 20:
            paired_task_penalties.append({
                "task_type": r[0],
                "human_n": hu_n,
                "human_merged": int(r[2]),
                "human_merge_rate_pct": hu_m,
                "agent_n": ai_n,
                "agent_merged": int(r[5]),
                "agent_merge_rate_pct": ai_m,
                "penalty_pp": round(ai_m - hu_m, 2),
            })

    q_paired_lang = f"""
    WITH shared_repos AS (
        SELECT DISTINCT r.url AS repo_url, coalesce(r.language, 'Unknown') AS language
        FROM "{data_dir}/pull_request.parquet" ai
        JOIN "{data_dir}/human_pull_request.parquet" hu ON ai.repo_url = hu.repo_url
        JOIN "{data_dir}/repository.parquet" r ON ai.repo_url = r.url
    ),
    hu_l AS (
        SELECT sr.language, count(*) AS hu_n, round(avg(CASE WHEN h.merged_at IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS hu_merge_pct
        FROM "{data_dir}/human_pull_request.parquet" h
        JOIN shared_repos sr ON h.repo_url = sr.repo_url
        GROUP BY 1
    ),
    ai_l AS (
        SELECT sr.language, count(*) AS ai_n, round(avg(CASE WHEN a.merged_at IS NOT NULL THEN 100.0 ELSE 0.0 END), 2) AS ai_merge_pct
        FROM "{data_dir}/pull_request.parquet" a
        JOIN shared_repos sr ON a.repo_url = sr.repo_url
        GROUP BY 1
    )
    SELECT
        hu_l.language,
        hu_l.hu_n,
        hu_l.hu_merge_pct,
        ai_l.ai_n,
        ai_l.ai_merge_pct
    FROM hu_l
    JOIN ai_l ON hu_l.language = ai_l.language
    WHERE hu_l.hu_n >= 50 AND ai_l.ai_n >= 50
    ORDER BY (hu_l.hu_n + ai_l.ai_n) DESC
    """
    paired_language_penalties = [
        {
            "language": r[0],
            "human_n": int(r[1]),
            "human_merge_rate_pct": float(r[2]),
            "agent_n": int(r[3]),
            "agent_merge_rate_pct": float(r[4]),
            "penalty_pp": round(float(r[4]) - float(r[2]), 2),
        }
        for r in con.execute(q_paired_lang).fetchall()
    ]

    q_commit_dist = f"""
    WITH hr AS (
        SELECT DISTINCT pr_id
        FROM "{data_dir}/pr_reviews.parquet"
        WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot'
    ),
    ca AS (
        SELECT pr_id, count(*) AS commits
        FROM "{data_dir}/pr_commits.parquet"
        GROUP BY pr_id
    )
    SELECT
        CASE WHEN hr.pr_id IS NOT NULL THEN 'Reviewed' ELSE 'Silent' END AS review_gate,
        CASE WHEN p.merged_at IS NOT NULL THEN 'Merged' ELSE 'Unmerged' END AS outcome,
        count(*) AS n_prs,
        round(avg(coalesce(ca.commits, 1)), 2) AS mean_commits,
        round(median(coalesce(ca.commits, 1)), 1) AS median_commits,
        round(quantile_cont(coalesce(ca.commits, 1), 0.90), 1) AS p90_commits
    FROM "{data_dir}/pull_request.parquet" p
    LEFT JOIN hr ON p.id = hr.pr_id
    LEFT JOIN ca ON p.id = ca.pr_id
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    commit_distribution = [
        {
            "review_gate": r[0],
            "outcome": r[1],
            "n_prs": int(r[2]),
            "mean_commits": float(r[3]),
            "median_commits": float(r[4]),
            "p90_commits": float(r[5]),
        }
        for r in con.execute(q_commit_dist).fetchall()
    ]

    exec_csv_rows = []
    for m in execution_modes:
        exec_csv_rows.append([
            "Execution_Mode",
            f"{m['execution_mode']} | {m['agent_family']}",
            m["n_prs"],
            m["silent_gate_pct"],
            m["median_merge_minutes"],
            m["avg_repo_agent_prs"],
            m["avg_commits"],
            "Matched against pr_timeline merged event actor == pr.user",
        ])
    for ag in per_agent_profile:
        exec_csv_rows.append([
            "Per_Agent_Profile",
            ag["agent"],
            ag["total_prs"],
            ag["silent_gate_pct"],
            ag["median_merge_minutes"],
            ag["self_merged_among_matched_pct"],
            ag["mean_commits"],
            f"merge_rate={ag['merge_rate_pct']}%; human_reviewed={ag['human_reviewed_pct']}%",
        ])
    for scope_key, buckets in volume_scaling.items():
        for b in buckets:
            exec_csv_rows.append([
                f"Volume_Scaling_{scope_key}",
                b["bucket"],
                b["n_prs"],
                b["silent_pct"],
                b["merge_rate_pct"],
                "",
                "",
                "Non-Codex isolates human-reviewed repositories from Codex self-merge sandboxes",
            ])
    for t in paired_task_penalties:
        exec_csv_rows.append([
            "Paired_Task_Type_Penalty",
            t["task_type"],
            t["agent_n"],
            t["human_n"],
            t["agent_merge_rate_pct"],
            t["human_merge_rate_pct"],
            t["penalty_pp"],
            f"{shared_repo_count} paired repos: AI {t['agent_merge_rate_pct']}% vs Human {t['human_merge_rate_pct']}%",
        ])
    for l in paired_language_penalties:
        exec_csv_rows.append([
            "Paired_Language_Penalty",
            l["language"],
            l["agent_n"],
            l["human_n"],
            l["agent_merge_rate_pct"],
            l["human_merge_rate_pct"],
            l["penalty_pp"],
            f"{shared_repo_count} paired repos: AI {l['agent_merge_rate_pct']}% vs Human {l['human_merge_rate_pct']}%",
        ])
    for c in commit_distribution:
        exec_csv_rows.append([
            "Commit_Distribution",
            f"{c['review_gate']} | {c['outcome']}",
            c["n_prs"],
            c["mean_commits"],
            c["median_commits"],
            c["p90_commits"],
            "",
            "Mean/median/P90 commits across pr_commits.parquet",
        ])

    with open(out_exec_modes_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "stratum", "n_primary", "metric_1", "metric_2", "metric_3", "metric_4", "notes"])
        w.writerows(exec_csv_rows)

    output = {
        "execution_timestamp_utc": run_ts,
        "dataset": "AIDev (Li et al., MSR 2026; Zenodo 10.5281/zenodo.16899501)",
        "input_parquet_manifest": input_manifest,
        "generated_audit_logs": {
            "repositories_csv": "analyzed_repositories_log.csv",
            "repositories_logged_count": len(repo_rows),
            "human_reviewed_prs_csv": "analyzed_human_reviewed_prs_log.csv",
            "human_reviewed_prs_logged_count": len(all_human_reviewed),
            "operator_config_prs_csv": "aidev_operator_config_prs_log.csv",
            "operator_config_pr_path_rows_count": len(config_pr_rows),
            "execution_modes_and_task_penalties_csv": "aidev_execution_modes_and_task_penalties_log.csv",
            "execution_modes_and_task_penalties_rows_count": len(exec_csv_rows),
        },
        "macro_corpus_summary": {
            "agentic_prs_total": agent_macro[0],
            "agentic_prs_merged": agent_macro[1],
            "agentic_prs_merge_rate_pct": round(agent_macro[1] / agent_macro[0] * 100.0, 2),
            "agentic_prs_rejected_closed": agent_macro[2],
            "agentic_prs_with_formal_human_review": len(reviewed_b) + len(reviewed_c),
            "agentic_prs_bypassing_formal_human_review_pct": round(
                (1.0 - (len(reviewed_b) + len(reviewed_c)) / agent_macro[0]) * 100.0, 2
            ),
            "human_baseline_prs_total": human_macro[0],
            "human_baseline_prs_merged": human_macro[1],
            "human_baseline_merge_rate_pct": round(human_macro[1] / human_macro[0] * 100.0, 2),
        },
        "human_reviewed_cohorts": {
            "cohort_b_human_only_n": len(reviewed_b),
            "cohort_c_tier1_bot_plus_human_n": len(reviewed_c),
            "total_human_reviewed_agent_prs": len(reviewed_b) + len(reviewed_c),
            "comparisons": cohort_comparisons,
        },
        "coarsened_exact_matching_control": cem_results,
        "paired_control_summary": paired_summary,
        "execution_mode_and_task_stratification": {
            "matched_merged_prs_total": sum(m["n_prs"] for m in execution_modes),
            "mode_i_self_merged_total": sum(m["n_prs"] for m in execution_modes if "Self-Merged" in m["execution_mode"]),
            "mode_ii_peer_merged_total": sum(m["n_prs"] for m in execution_modes if "Peer-Merged" in m["execution_mode"]),
            "execution_modes": execution_modes,
            "per_agent_profile": per_agent_profile,
            "volume_scaling": volume_scaling,
            "paired_task_type_penalties": paired_task_penalties,
            "paired_language_penalties": paired_language_penalties,
            "commit_distribution": commit_distribution,
        },
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(
        "Macro Corpus: total_agent_prs=%d, merged=%d (%.2f%%), human_reviewed=%d, silent_gate=%.2f%%",
        agent_macro[0],
        agent_macro[1],
        agent_macro[1] / agent_macro[0] * 100.0,
        len(reviewed_b) + len(reviewed_c),
        (1.0 - (len(reviewed_b) + len(reviewed_c)) / agent_macro[0]) * 100.0,
    )
    logger.info(
        "Cohorts: Cohort B (Human-Only)=%d PRs | Cohort C (Tier-1 Bot + Human)=%d PRs | CEM Matched Pairs=%d",
        len(reviewed_b),
        len(reviewed_c),
        len(matched_c),
    )
    for k, v in cohort_comparisons.items():
        logger.info(
            "Metric %-42s | B_mean=%.4f | C_mean=%.4f | shift=%+.2f%% | p=%.3e | q_BH=%.3e | delta=%+.4f",
            k,
            v["cohort_b_human_only_mean"],
            v["cohort_c_tier1_bot_plus_human_mean"],
            v["relative_shift_pct"],
            v["mann_whitney_p"],
            v["bh_fdr_q"],
            v["cliffs_delta"],
        )
    logger.info("Wrote %d repositories to %s", len(repo_rows), out_repos_csv)
    logger.info("Wrote %d human-reviewed PRs to %s", len(all_human_reviewed), out_prs_csv)
    logger.info("Wrote %d protected-config PR path rows to %s", len(config_pr_rows), out_config_prs_csv)
    logger.info("Wrote %d execution-mode & task-penalty strata rows to %s", len(exec_csv_rows), out_exec_modes_csv)
    logger.info("Wrote summary JSON to %s", out_json)


if __name__ == "__main__":
    main()
