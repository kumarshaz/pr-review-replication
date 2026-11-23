#!/usr/bin/env python3
"""
Pipeline p04: Raw Code Patch Inspection, Sociotechnical Overrides & Post-Merge Regressions
=========================================================================================
Analyzes inline diff_hunks in AIDev pr_review_comments_v2.parquet, silent warning
overrides, formal human veto overrides & review_dismissed events, Conway gatekeeper
centralization (Gini), multi-horizon post-merge regression velocity (with repo-velocity
normalization and 281-shared-repo controls), review bot brain-family impact (with
FILTER (WHERE p.merged_ts IS NOT NULL) and partitioned post-merge comments), and
anonymous live GitHub .patch verification.

Outputs:
  - results/raw_patch_and_sociotechnical_results.json
  - results/data_tables/raw_patch_unaddressed_warnings_log.csv
  - results/data_tables/human_veto_overrides_and_dismissals_log.csv
  - results/data_tables/normalized_post_merge_hazard_log.csv
  - results/data_tables/review_bot_reputation_and_brain_log.csv
  - results/data_tables/organization_governance_archetypes_log.csv
  - results/data_tables/post_merge_failures_and_reverts_log.csv
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

import duckdb
import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config.bot_catalog as bot_catalog
from config.bot_catalog import DETERMINISTIC_SAST_BOTS, TIER1_PR_COMMENTS_BOTS, TIER1_REVIEW_BOTS, sql_in_list
from config.paths import get_paths
from src.utils.logging_utils import setup_verbose_logger
from src.utils.stats_utils import gini_coefficient

MULTIMODEL_RAG_BOTS: tuple[str, ...] = tuple(
    getattr(
        bot_catalog,
        "MULTIMODEL_RAG_BOTS",
        getattr(
            bot_catalog,
            "_MULTIMODEL_RAG_BOTS",
            (
                "coderabbitai[bot]",
                "greptile-apps[bot]",
                "ellipsis-dev[bot]",
                "cubic-dev-ai[bot]",
                "sourcery-ai[bot]",
                "qodo-merge-pro[bot]",
                "qodo-merge-for-open-source[bot]",
                "codiumai-pr-agent[bot]",
                "cursor[bot]",
                "entelligence-ai-pr-reviews[bot]",
                "entelligence-ai-pr-reviewer[bot]",
                "codeant-ai[bot]",
                "korbit-ai[bot]",
                "kodus-ai[bot]",
            ),
        ),
    )
)


def fetch_live_github_patch_and_postmerge(repo_full_name: str, pr_number: int, merged_at: str) -> dict:
    """Fetches anonymous live unified `.patch` and public post-merge bug/regression issues."""
    patch_url = f"https://github.com/{repo_full_name}/pull/{pr_number}.patch"
    info = {
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "merged_at": merged_at,
        "live_patch_url": patch_url,
        "live_patch_reachable": False,
        "live_patch_bytes": 0,
        "live_patch_sha256": None,
        "live_patch_preview_lines": [],
        "post_merge_repo_bug_issues_sampled": [],
    }
    try:
        req = urllib.request.Request(patch_url, headers={"User-Agent": "Research-Workspace-MSR"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_bytes = resp.read()
            info["live_patch_reachable"] = True
            info["live_patch_bytes"] = len(raw_bytes)
            info["live_patch_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            text = raw_bytes.decode("utf-8", errors="replace")
            info["live_patch_preview_lines"] = text.splitlines()[:18]
    except Exception as exc:
        info["live_patch_error"] = str(exc)

    try:
        issues_url = f"https://api.github.com/repos/{repo_full_name}/issues?state=all&since={merged_at}&per_page=10"
        req = urllib.request.Request(
            issues_url,
            headers={"User-Agent": "Research-Workspace-MSR", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            for it in items:
                if "pull_request" not in it:
                    title_low = (it.get("title") or "").lower()
                    if any(k in title_low for k in ("bug", "fix", "error", "fail", "crash", "regression", "leak", "race", "broken")):
                        info["post_merge_repo_bug_issues_sampled"].append({
                            "issue_number": it.get("number"),
                            "title": it.get("title"),
                            "state": it.get("state"),
                            "created_at": it.get("created_at"),
                            "html_url": it.get("html_url"),
                        })
    except Exception as exc:
        info["post_merge_issues_note"] = str(exc)

    return info


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    logger, ts_log_path = setup_verbose_logger(
        "p04_diff_hunks_sociotech",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    logger.info("Timestamped log: %s", ts_log_path)

    parquet_dir = paths.scratch_dir / "aidev"
    con = duckdb.connect()
    bots_sql = sql_in_list(TIER1_REVIEW_BOTS)
    bots_comm_sql = sql_in_list(TIER1_PR_COMMENTS_BOTS)
    sast_bots_sql = sql_in_list(DETERMINISTIC_SAST_BOTS)
    rag_bots_sql = sql_in_list(MULTIMODEL_RAG_BOTS)

    # 1. Raw Code Patch Inspection (excluding copilot-swe-agent[bot] author replies)
    raw_patch_summary = con.execute(f"""
        WITH parsed_rc AS (
            SELECT
                rc.*,
                CAST(SPLIT_PART(rc.pull_request_url, '/', -1) AS BIGINT) AS pr_number,
                REPLACE(
                    SPLIT_PART(rc.pull_request_url, '/repos/', 2),
                    '/pulls/' || SPLIT_PART(rc.pull_request_url, '/', -1),
                    ''
                ) AS repo_full_name
            FROM '{parquet_dir}/pr_review_comments_v2.parquet' rc
            LEFT JOIN '{parquet_dir}/pr_reviews.parquet' rv ON rc.pull_request_review_id = rv.id
            WHERE COALESCE(rv.user, '') != 'copilot-swe-agent[bot]'
        ),
        joined AS (
            SELECT
                rc.*,
                pr.id AS pr_id,
                pr.agent,
                pr.state AS pr_state,
                pr.merged_at,
                pr.html_url
            FROM parsed_rc rc
            JOIN '{parquet_dir}/repository.parquet' repo ON rc.repo_full_name = repo.full_name
            JOIN '{parquet_dir}/pull_request.parquet' pr ON pr.repo_id = repo.id AND pr.number = rc.pr_number
        )
        SELECT
            COUNT(*) AS total_inline_patch_reviews,
            COUNT(DISTINCT pr_id) AS distinct_prs_with_patches,
            COUNT(DISTINCT repo_full_name || '/' || path) AS distinct_files_patched,
            SUM(CASE WHEN user_type = 'Bot' THEN 1 ELSE 0 END) AS bot_inline_patch_comments,
            SUM(CASE WHEN user_type = 'User' THEN 1 ELSE 0 END) AS human_inline_patch_comments,
            AVG(LENGTH(diff_hunk)) AS avg_diff_hunk_chars,
            SUM(CASE WHEN diff_hunk LIKE '%# type: ignore%' OR diff_hunk LIKE '%@ts-ignore%' OR diff_hunk LIKE '%@ts-expect-error%' OR diff_hunk LIKE '%eslint-disable%' OR diff_hunk LIKE '%noinspection%' OR diff_hunk LIKE '%pragma: no cover%' THEN 1 ELSE 0 END) AS linter_type_suppressions_in_patch,
            SUM(CASE WHEN diff_hunk LIKE '%except:%' OR diff_hunk LIKE '%except Exception%' OR diff_hunk LIKE '%catch (%' THEN 1 ELSE 0 END) AS broad_exception_handlers_in_patch,
            SUM(CASE WHEN diff_hunk LIKE '%.skip(%' OR diff_hunk LIKE '%pytest.mark.skip%' OR diff_hunk LIKE '%@Disabled%' THEN 1 ELSE 0 END) AS skipped_tests_in_patch,
            SUM(CASE WHEN LOWER(body) LIKE '%security%' OR LOWER(body) LIKE '%vulnerab%' OR LOWER(body) LIKE '%secret%' OR LOWER(body) LIKE '%password%' OR LOWER(body) LIKE '%credential%' OR LOWER(body) LIKE '%injection%' OR LOWER(body) LIKE '%xss%' OR LOWER(body) LIKE '%csrf%' OR LOWER(body) LIKE '%race condition%' OR LOWER(body) LIKE '%leak%' THEN 1 ELSE 0 END) AS security_and_bug_warnings_on_patch,
            SUM(CASE WHEN (LOWER(body) LIKE '%security%' OR LOWER(body) LIKE '%vulnerab%' OR LOWER(body) LIKE '%secret%' OR LOWER(body) LIKE '%password%' OR LOWER(body) LIKE '%credential%' OR LOWER(body) LIKE '%injection%' OR LOWER(body) LIKE '%xss%' OR LOWER(body) LIKE '%csrf%' OR LOWER(body) LIKE '%race condition%' OR LOWER(body) LIKE '%leak%') AND merged_at IS NOT NULL THEN 1 ELSE 0 END) AS security_and_bug_warnings_on_merged_prs,
            SUM(CASE WHEN LOWER(body) LIKE '%prompt for ai agents%' OR LOWER(body) LIKE '%committable suggestion%' THEN 1 ELSE 0 END) AS machine_to_machine_agent_prompts_in_comments
        FROM joined
    """).fetchone()

    unaddressed_by_actor = con.execute(f"""
        WITH parsed_rc AS (
            SELECT
                rc.*,
                CAST(SPLIT_PART(rc.pull_request_url, '/', -1) AS BIGINT) AS pr_number,
                REPLACE(
                    SPLIT_PART(rc.pull_request_url, '/repos/', 2),
                    '/pulls/' || SPLIT_PART(rc.pull_request_url, '/', -1),
                    ''
                ) AS repo_full_name
            FROM '{parquet_dir}/pr_review_comments_v2.parquet' rc
            LEFT JOIN '{parquet_dir}/pr_reviews.parquet' rv ON rc.pull_request_review_id = rv.id
            WHERE COALESCE(rv.user, '') != 'copilot-swe-agent[bot]'
        ),
        joined AS (
            SELECT
                rc.*,
                pr.id AS pr_id,
                pr.agent,
                pr.merged_at,
                pr.html_url
            FROM parsed_rc rc
            JOIN '{parquet_dir}/repository.parquet' repo ON rc.repo_full_name = repo.full_name
            JOIN '{parquet_dir}/pull_request.parquet' pr ON pr.repo_id = repo.id AND pr.number = rc.pr_number
            WHERE pr.merged_at IS NOT NULL
        )
        SELECT
            user_type,
            COUNT(*) AS total_merged_patch_comments,
            SUM(CASE WHEN commit_id = original_commit_id AND position IS NOT NULL THEN 1 ELSE 0 END) AS unaddressed_merged_as_is,
            ROUND(100.0 * SUM(CASE WHEN commit_id = original_commit_id AND position IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS unaddressed_rate_pct,
            SUM(CASE WHEN commit_id = original_commit_id AND position IS NOT NULL AND (LOWER(body) LIKE '%security%' OR LOWER(body) LIKE '%vulnerab%' OR LOWER(body) LIKE '%secret%' OR LOWER(body) LIKE '%password%' OR LOWER(body) LIKE '%bug%' OR LOWER(body) LIKE '%race condition%' OR LOWER(body) LIKE '%null%' OR LOWER(body) LIKE '%leak%') THEN 1 ELSE 0 END) AS unaddressed_security_or_bug_merged_as_is
        FROM joined
        GROUP BY user_type
        ORDER BY user_type
    """).fetchall()

    unaddressed_rows = con.execute(f"""
        WITH parsed_rc AS (
            SELECT
                rc.*,
                CAST(SPLIT_PART(rc.pull_request_url, '/', -1) AS BIGINT) AS pr_number,
                REPLACE(
                    SPLIT_PART(rc.pull_request_url, '/repos/', 2),
                    '/pulls/' || SPLIT_PART(rc.pull_request_url, '/', -1),
                    ''
                ) AS repo_full_name
            FROM '{parquet_dir}/pr_review_comments_v2.parquet' rc
            LEFT JOIN '{parquet_dir}/pr_reviews.parquet' rv ON rc.pull_request_review_id = rv.id
            WHERE COALESCE(rv.user, '') != 'copilot-swe-agent[bot]'
        )
        SELECT
            pr.id AS pr_id,
            rc.repo_full_name,
            rc.pr_number,
            pr.html_url,
            pr.agent,
            rc.user AS reviewer,
            rc.user_type,
            rc.path AS file_path,
            rc.commit_id,
            rc.original_commit_id,
            CASE WHEN LOWER(rc.body) LIKE '%security%' OR LOWER(rc.body) LIKE '%vulnerab%' OR LOWER(rc.body) LIKE '%secret%' OR LOWER(rc.body) LIKE '%password%' OR LOWER(rc.body) LIKE '%bug%' OR LOWER(rc.body) LIKE '%race condition%' OR LOWER(rc.body) LIKE '%null%' OR LOWER(rc.body) LIKE '%leak%' THEN 1 ELSE 0 END AS is_security_or_bug_warning,
            REPLACE(REPLACE(SUBSTRING(rc.diff_hunk, 1, 250), CHR(10), ' '), CHR(13), ' ') AS diff_hunk_snippet,
            REPLACE(REPLACE(SUBSTRING(rc.body, 1, 250), CHR(10), ' '), CHR(13), ' ') AS warning_snippet,
            pr.merged_at
        FROM parsed_rc rc
        JOIN '{parquet_dir}/repository.parquet' repo ON rc.repo_full_name = repo.full_name
        JOIN '{parquet_dir}/pull_request.parquet' pr ON pr.repo_id = repo.id AND pr.number = rc.pr_number
        WHERE pr.merged_at IS NOT NULL
          AND rc.commit_id = rc.original_commit_id
          AND rc.position IS NOT NULL
        ORDER BY is_security_or_bug_warning DESC, rc.user_type ASC, pr.id ASC
    """).fetchall()

    unaddressed_csv = paths.tables_dir / "raw_patch_unaddressed_warnings_log.csv"
    with open(unaddressed_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "pr_id", "repo_full_name", "pr_number", "html_url", "agent",
            "reviewer", "reviewer_type", "file_path", "commit_id", "original_commit_id",
            "is_security_or_bug_warning", "diff_hunk_snippet", "warning_snippet", "merged_at",
        ])
        w.writerows(unaddressed_rows)

    # 2. Human Veto Overrides & Review Dismissals ("The Overridden Gate")
    override_by_cohort = con.execute(f"""
        WITH tier1_prs AS (
            SELECT DISTINCT pr_id FROM (
                SELECT pr_id, user FROM '{parquet_dir}/pr_reviews.parquet' WHERE user IN ({bots_sql})
                UNION ALL
                SELECT pr_id, user FROM '{parquet_dir}/pr_comments.parquet' WHERE user IN ({bots_comm_sql})
            )
        ),
        rev_agg AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'APPROVED' THEN 1 ELSE 0 END) AS h_app,
                ARG_MAX(state, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state IN ('APPROVED', 'CHANGES_REQUESTED')) AS final_h_state
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        )
        SELECT
            CASE WHEN t.pr_id IS NOT NULL THEN 'Cohort_C_Tier1_Bot_Plus_Human' ELSE 'Cohort_B_Human_Only' END AS cohort,
            COUNT(*) AS prs_with_human_cr,
            SUM(CASE WHEN pr.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_total,
            SUM(CASE WHEN pr.merged_at IS NOT NULL AND final_h_state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS merged_overriding_final_human_cr,
            SUM(CASE WHEN pr.merged_at IS NOT NULL AND h_app = 0 THEN 1 ELSE 0 END) AS merged_with_zero_human_approval,
            ROUND(100.0 * SUM(CASE WHEN pr.merged_at IS NOT NULL AND final_h_state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) / COUNT(*), 2) AS veto_override_rate_pct
        FROM rev_agg r
        JOIN '{parquet_dir}/pull_request.parquet' pr ON r.pr_id = pr.id
        LEFT JOIN tier1_prs t ON r.pr_id = t.pr_id
        WHERE r.h_cr > 0
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    veto_and_dismissed_rows = con.execute(f"""
        WITH rev_agg AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'APPROVED' THEN 1 ELSE 0 END) AS h_app,
                ARG_MAX(user, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED') AS cr_reviewer,
                ARG_MAX(body, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED') AS cr_body,
                ARG_MAX(state, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state IN ('APPROVED', 'CHANGES_REQUESTED')) AS final_h_state
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        ),
        dismissed AS (
            SELECT
                pr_id,
                COUNT(*) AS dismissal_count,
                STRING_AGG(DISTINCT actor, ';') AS dismissal_actors
            FROM '{parquet_dir}/pr_timeline.parquet'
            WHERE event = 'review_dismissed'
            GROUP BY pr_id
        )
        SELECT
            pr.id AS pr_id,
            repo.full_name AS repo_full_name,
            pr.number AS pr_number,
            pr.html_url,
            pr.agent,
            pr.state,
            CASE WHEN pr.merged_at IS NOT NULL THEN 1 ELSE 0 END AS is_merged,
            COALESCE(r.h_cr, 0) AS human_changes_requested_count,
            COALESCE(r.h_app, 0) AS human_approved_count,
            COALESCE(r.final_h_state, 'NONE') AS final_human_verdict,
            COALESCE(r.cr_reviewer, '') AS last_cr_reviewer,
            COALESCE(d.dismissal_count, 0) AS review_dismissed_events,
            COALESCE(d.dismissal_actors, '') AS dismissal_actors,
            REPLACE(REPLACE(SUBSTRING(COALESCE(r.cr_body, ''), 1, 220), CHR(10), ' '), CHR(13), ' ') AS cr_reason_snippet,
            pr.merged_at
        FROM '{parquet_dir}/pull_request.parquet' pr
        JOIN '{parquet_dir}/repository.parquet' repo ON pr.repo_id = repo.id
        LEFT JOIN rev_agg r ON pr.id = r.pr_id
        LEFT JOIN dismissed d ON pr.id = d.pr_id
        WHERE (pr.merged_at IS NOT NULL AND r.final_h_state = 'CHANGES_REQUESTED')
           OR COALESCE(d.dismissal_count, 0) > 0
        ORDER BY is_merged DESC, human_changes_requested_count DESC
    """).fetchall()

    overrides_csv = paths.tables_dir / "human_veto_overrides_and_dismissals_log.csv"
    with open(overrides_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "pr_id", "repo_full_name", "pr_number", "html_url", "agent", "state",
            "is_merged", "human_changes_requested_count", "human_approved_count",
            "final_human_verdict", "last_cr_reviewer", "review_dismissed_events",
            "dismissal_actors", "cr_reason_snippet", "merged_at",
        ])
        w.writerows(veto_and_dismissed_rows)

    # 3. Conway Centralization & The "Hero-Reviewer" Burnout Bottleneck
    repo_reviewer_rows = con.execute(f"""
        SELECT
            pr.repo_id,
            r.user,
            COUNT(*) AS rev_cnt
        FROM '{parquet_dir}/pr_reviews.parquet' r
        JOIN '{parquet_dir}/pull_request.parquet' pr ON r.pr_id = pr.id
        WHERE r.user_type = 'User' AND r.user IS NOT NULL AND r.user NOT LIKE '%[bot]%' AND LOWER(r.user) NOT LIKE '%-bot'
        GROUP BY pr.repo_id, r.user
    """).fetchall()

    by_repo: dict[int, list[int]] = {}
    for repo_id, _user, cnt in repo_reviewer_rows:
        by_repo.setdefault(repo_id, []).append(int(cnt))

    qualifying_repos = {k: np.array(v, dtype=float) for k, v in by_repo.items() if sum(v) >= 5}
    top1_shares = [float(np.max(v) / np.sum(v)) for v in qualifying_repos.values()]
    ginis = [gini_coefficient(v.tolist()) for v in qualifying_repos.values() if len(v) >= 2]
    single_gatekeeper_count = sum(1 for v in qualifying_repos.values() if len(v) == 1)

    conway_metrics = {
        "repos_with_5plus_human_reviews": len(qualifying_repos),
        "single_human_gatekeeper_repos_bus_factor_1": single_gatekeeper_count,
        "single_human_gatekeeper_repo_pct": round(100.0 * single_gatekeeper_count / max(1, len(qualifying_repos)), 2),
        "mean_top1_reviewer_workload_share_pct": round(100.0 * float(np.mean(top1_shares)), 2) if top1_shares else 0.0,
        "median_top1_reviewer_workload_share_pct": round(100.0 * float(np.median(top1_shares)), 2) if top1_shares else 0.0,
        "mean_multi_reviewer_gini_index": round(float(np.mean(ginis)), 4) if ginis else 0.0,
    }

    # 4. Multi-Horizon (7d, 14d, 30d, 90d) Post-Merge Regression & Defect Velocity
    regime_regression_rows = con.execute(f"""
        WITH repo_max_ts AS (
            SELECT repo_id, MAX(created_at::TIMESTAMP) AS max_repo_ts
            FROM '{parquet_dir}/pull_request.parquet'
            GROUP BY repo_id
        ),
        pr_base AS (
            SELECT
                pr.id AS pr_id,
                pr.repo_id,
                pr.number,
                pr.created_at::TIMESTAMP AS created_ts,
                pr.merged_at::TIMESTAMP AS merged_ts,
                t.type AS task_type,
                (LOWER(pr.title) LIKE '%revert%' OR LOWER(pr.title) LIKE '%regression%' OR LOWER(pr.title) LIKE '%hotfix%' OR LOWER(pr.body) LIKE '%regression%') AS is_reg_or_revert,
                rm.max_repo_ts
            FROM '{parquet_dir}/pull_request.parquet' pr
            LEFT JOIN '{parquet_dir}/pr_task_type.parquet' t ON pr.id = t.id
            JOIN repo_max_ts rm ON pr.repo_id = rm.repo_id
        ),
        defect_prs AS (
            SELECT pr_id, repo_id, created_ts, (task_type = 'fix') AS is_fix, is_reg_or_revert
            FROM pr_base
            WHERE task_type = 'fix' OR is_reg_or_revert
        ),
        merged_prs AS (
            SELECT
                p1.pr_id,
                p1.repo_id,
                p1.merged_ts,
                (p1.max_repo_ts >= p1.merged_ts + INTERVAL 90 DAY) AS has_full_90d_window,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 7 DAY THEN 1 ELSE 0 END) AS fix_7d,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS fix_14d,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 30 DAY THEN 1 ELSE 0 END) AS fix_30d,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY THEN 1 ELSE 0 END) AS fix_90d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 7 DAY THEN 1 ELSE 0 END) AS reg_7d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS reg_14d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 30 DAY THEN 1 ELSE 0 END) AS reg_30d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY THEN 1 ELSE 0 END) AS reg_90d
            FROM pr_base p1
            LEFT JOIN defect_prs p2 ON p1.repo_id = p2.repo_id AND p1.pr_id != p2.pr_id AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY
            WHERE p1.merged_ts IS NOT NULL
            GROUP BY p1.pr_id, p1.repo_id, p1.merged_ts, p1.max_repo_ts
        ),
        rev_flags AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' THEN 1 ELSE 0 END) AS h_revs,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'APPROVED' THEN 1 ELSE 0 END) AS h_app,
                ARG_MAX(state, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state IN ('APPROVED', 'CHANGES_REQUESTED')) AS final_h_state
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        )
        SELECT
            CASE
                WHEN COALESCE(rf.h_revs, 0) = 0 THEN '1_Silent_Gate_No_Human_Review'
                WHEN rf.final_h_state = 'CHANGES_REQUESTED' THEN '2_Human_Veto_Overridden_Merge'
                WHEN rf.h_app > 0 AND rf.h_cr = 0 THEN '3_Human_First_Pass_Approval_No_CR'
                WHEN rf.h_cr > 0 AND rf.final_h_state = 'APPROVED' THEN '4_Human_CR_Resolved_Then_Approved'
                ELSE '5_Human_Comment_Only_Merge'
            END AS review_regime,
            COUNT(*) AS merged_prs,
            SUM(CASE WHEN m.has_full_90d_window THEN 1 ELSE 0 END) AS uncensored_90d_n,
            ROUND(100.0 * AVG(CASE WHEN m.fix_7d > 0 THEN 1.0 ELSE 0.0 END), 2) AS fix_7d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.fix_14d > 0 THEN 1.0 ELSE 0.0 END), 2) AS fix_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.fix_30d > 0 THEN 1.0 ELSE 0.0 END), 2) AS fix_30d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.fix_90d > 0 THEN 1.0 ELSE 0.0 END), 2) AS fix_90d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.reg_7d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_7d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.reg_14d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.reg_30d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_30d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.reg_90d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_90d_pct,
            ROUND(100.0 * AVG(CASE WHEN m.reg_90d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE m.has_full_90d_window), 2) AS reg_90d_strictly_uncensored_pct
        FROM merged_prs m
        LEFT JOIN rev_flags rf ON m.pr_id = rf.pr_id
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    # 4b. Repo-Velocity Normalized Hazard & Within-Shared-Repo Matched Regime Control
    normalized_hazard_rows = con.execute(f"""
        WITH repo_stats AS (
            SELECT
                repo_id,
                count(*) AS repo_total_prs,
                greatest(1.0, date_diff('day', min(created_at::TIMESTAMP), max(created_at::TIMESTAMP))) AS repo_span_days
            FROM '{parquet_dir}/pull_request.parquet'
            GROUP BY repo_id
        ),
        pr_base AS (
            SELECT
                pr.id AS pr_id,
                pr.repo_id,
                pr.created_at::TIMESTAMP AS created_ts,
                pr.merged_at::TIMESTAMP AS merged_ts,
                t.type AS task_type,
                (LOWER(pr.title) LIKE '%revert%' OR LOWER(pr.title) LIKE '%regression%' OR LOWER(pr.title) LIKE '%hotfix%' OR LOWER(pr.body) LIKE '%regression%') AS is_reg
            FROM '{parquet_dir}/pull_request.parquet' pr
            LEFT JOIN '{parquet_dir}/pr_task_type.parquet' t ON pr.id = t.id
        ),
        defect_prs AS (
            SELECT pr_id, repo_id, created_ts, (task_type = 'fix') AS is_fix, is_reg
            FROM pr_base
            WHERE task_type = 'fix' OR is_reg
        ),
        rev_flags AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' THEN 1 ELSE 0 END) AS h_revs,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'APPROVED' THEN 1 ELSE 0 END) AS h_app,
                ARG_MAX(state, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state IN ('APPROVED', 'CHANGES_REQUESTED')) AS final_h_state
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        ),
        post_comm AS (
            SELECT
                pc.pr_id,
                MAX(CASE WHEN pc.created_at::TIMESTAMP > p.merged_ts AND regexp_matches(lower(coalesce(pc.body, '')), '(revert|regression|broke|broken|hotfix|bug|failed)') THEN 1 ELSE 0 END) AS has_post_bug_comm
            FROM '{parquet_dir}/pr_comments.parquet' pc
            JOIN pr_base p ON pc.pr_id = p.pr_id
            WHERE p.merged_ts IS NOT NULL
            GROUP BY pc.pr_id
        ),
        tl_flags AS (
            SELECT pr_id, MAX(CASE WHEN event = 'reopened' THEN 1 ELSE 0 END) AS has_reopened
            FROM '{parquet_dir}/pr_timeline.parquet'
            GROUP BY pr_id
        ),
        merged_counts AS (
            SELECT
                p1.pr_id,
                p1.repo_id,
                rs.repo_total_prs,
                rs.repo_total_prs * 1.0 / rs.repo_span_days AS repo_prs_per_day,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS fix_14d,
                SUM(CASE WHEN p2.is_reg AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS reg_14d,
                coalesce(pc.has_post_bug_comm, 0) AS has_post_bug_comm,
                coalesce(tl.has_reopened, 0) AS has_reopened,
                CASE
                    WHEN COALESCE(rf.h_revs, 0) = 0 THEN '1_Silent_Gate_No_Human_Review'
                    WHEN rf.final_h_state = 'CHANGES_REQUESTED' THEN '2_Human_Veto_Overridden_Merge'
                    WHEN rf.h_app > 0 AND rf.h_cr = 0 THEN '3_Human_First_Pass_Approval_No_CR'
                    WHEN rf.h_cr > 0 AND rf.final_h_state = 'APPROVED' THEN '4_Human_CR_Resolved_Then_Approved'
                    ELSE '5_Human_Comment_Only_Merge'
                END AS review_regime
            FROM pr_base p1
            JOIN repo_stats rs ON p1.repo_id = rs.repo_id
            LEFT JOIN rev_flags rf ON p1.pr_id = rf.pr_id
            LEFT JOIN post_comm pc ON p1.pr_id = pc.pr_id
            LEFT JOIN tl_flags tl ON p1.pr_id = tl.pr_id
            LEFT JOIN defect_prs p2 ON p1.repo_id = p2.repo_id AND p1.pr_id != p2.pr_id AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY
            WHERE p1.merged_ts IS NOT NULL
            GROUP BY p1.pr_id, p1.repo_id, rs.repo_total_prs, repo_prs_per_day, pc.has_post_bug_comm, tl.has_reopened, rf.h_revs, rf.final_h_state, rf.h_app, rf.h_cr
        )
        SELECT
            review_regime,
            COUNT(*) AS merged_prs,
            ROUND(MEDIAN(repo_total_prs), 1) AS median_repo_agent_prs,
            ROUND(AVG(repo_total_prs), 1) AS mean_repo_agent_prs,
            ROUND(AVG(repo_prs_per_day), 2) AS mean_repo_prs_per_day,
            ROUND(100.0 * AVG(CASE WHEN reg_14d > 0 THEN 1.0 ELSE 0.0 END), 2) AS raw_reg_14d_pct,
            ROUND(AVG(reg_14d * 100.0 / GREATEST(1.0, repo_total_prs)), 4) AS reg_14d_per_100_repo_prs,
            ROUND(100.0 * AVG(has_post_bug_comm), 2) AS direct_post_merge_bug_comm_pct,
            ROUND(100.0 * AVG(has_reopened), 2) AS reopened_pct
        FROM merged_counts
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    within_shared_repo_rows = con.execute(f"""
        WITH pr_base AS (
            SELECT
                pr.id AS pr_id,
                pr.repo_id,
                pr.created_at::TIMESTAMP AS created_ts,
                pr.merged_at::TIMESTAMP AS merged_ts,
                t.type AS task_type,
                (LOWER(pr.title) LIKE '%revert%' OR LOWER(pr.title) LIKE '%regression%' OR LOWER(pr.title) LIKE '%hotfix%' OR LOWER(pr.body) LIKE '%regression%') AS is_reg
            FROM '{parquet_dir}/pull_request.parquet' pr
            LEFT JOIN '{parquet_dir}/pr_task_type.parquet' t ON pr.id = t.id
        ),
        defect_prs AS (
            SELECT pr_id, repo_id, created_ts, (task_type = 'fix') AS is_fix, is_reg
            FROM pr_base
            WHERE task_type = 'fix' OR is_reg
        ),
        rev_flags AS (
            SELECT pr_id, SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' THEN 1 ELSE 0 END) AS h_revs
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        ),
        merged AS (
            SELECT
                p1.pr_id,
                p1.repo_id,
                (COALESCE(rf.h_revs, 0) > 0) AS is_reviewed,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS fix_14d,
                SUM(CASE WHEN p2.is_reg AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS reg_14d,
                SUM(CASE WHEN p2.is_reg AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 30 DAY THEN 1 ELSE 0 END) AS reg_30d
            FROM pr_base p1
            LEFT JOIN rev_flags rf ON p1.pr_id = rf.pr_id
            LEFT JOIN defect_prs p2 ON p1.repo_id = p2.repo_id AND p1.pr_id != p2.pr_id AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 30 DAY
            WHERE p1.merged_ts IS NOT NULL
            GROUP BY p1.pr_id, p1.repo_id, is_reviewed
        ),
        shared_repos AS (
            SELECT repo_id
            FROM merged
            GROUP BY repo_id
            HAVING SUM(CASE WHEN is_reviewed THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN NOT is_reviewed THEN 1 ELSE 0 END) > 0
        )
        SELECT
            CASE WHEN is_reviewed THEN 'Reviewed_In_Shared_Repos' ELSE 'Silent_In_Shared_Repos' END AS cohort,
            COUNT(DISTINCT repo_id) AS shared_repos,
            COUNT(*) AS merged_prs,
            ROUND(100.0 * AVG(CASE WHEN fix_14d > 0 THEN 1.0 ELSE 0.0 END), 2) AS fix_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN reg_14d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN reg_30d > 0 THEN 1.0 ELSE 0.0 END), 2) AS reg_30d_pct,
            ROUND(AVG(reg_14d), 3) AS mean_reg_14d_cnt
        FROM merged
        WHERE repo_id IN (SELECT repo_id FROM shared_repos)
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    timeline_counts = con.execute(f"""
        SELECT
            SUM(CASE WHEN tl.event = 'review_dismissed' THEN 1 ELSE 0 END) AS rd_events,
            COUNT(DISTINCT CASE WHEN tl.event = 'review_dismissed' THEN tl.pr_id END) AS rd_prs,
            SUM(CASE WHEN tl.event = 'review_dismissed' AND pr.merged_at IS NOT NULL THEN 1 ELSE 0 END) AS rd_merged_events,
            SUM(CASE WHEN tl.event = 'head_ref_force_pushed' THEN 1 ELSE 0 END) AS force_push_events
        FROM '{parquet_dir}/pr_timeline.parquet' tl
        JOIN '{parquet_dir}/pull_request.parquet' pr ON tl.pr_id = pr.id
        WHERE tl.event IN ('review_dismissed', 'head_ref_force_pushed')
    """).fetchone()

    norm_hazard_csv = paths.tables_dir / "normalized_post_merge_hazard_log.csv"
    with open(norm_hazard_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table_type", "stratum", "merged_prs", "median_or_shared_repos", "metric_1", "metric_2", "metric_3", "metric_4", "metric_5"])
        for r in normalized_hazard_rows:
            w.writerow(["Regime_Volume_Normalized", r[0], r[1], r[2], r[3], r[4], r[5], r[6], f"bug_comm={r[7]}%;reopen={r[8]}%"])
        for r in within_shared_repo_rows:
            w.writerow(["Within_Shared_Repo_Control", r[0], r[2], r[1], r[3], r[4], r[5], r[6], "Controls constant repo PR velocity across shared repos with both silent and reviewed PRs"])

    # 5. Review Bot Reputation, Brain / LLM Family, & Author-Reviewer Coupling
    bot_reputation_rows = con.execute(f"""
        WITH parsed_rc AS (
            SELECT
                rc.*,
                CAST(SPLIT_PART(rc.pull_request_url, '/', -1) AS BIGINT) AS pr_number,
                REPLACE(
                    SPLIT_PART(rc.pull_request_url, '/repos/', 2),
                    '/pulls/' || SPLIT_PART(rc.pull_request_url, '/', -1),
                    ''
                ) AS repo_full_name
            FROM '{parquet_dir}/pr_review_comments_v2.parquet' rc
            LEFT JOIN '{parquet_dir}/pr_reviews.parquet' rv ON rc.pull_request_review_id = rv.id
            WHERE rc.user_type = 'Bot'
              AND COALESCE(rv.user, '') != 'copilot-swe-agent[bot]'
        ),
        joined AS (
            SELECT
                rc.user AS bot_name,
                CASE
                    WHEN rc.user IN ({sast_bots_sql}) THEN '1_Deterministic_SAST_Brain'
                    WHEN rc.user IN ({rag_bots_sql}) THEN '2_MultiModel_RAG_Agentic_Brain'
                    WHEN rc.user IN ('copilot-pull-request-reviewer[bot]', 'chatgpt-codex-connector[bot]', 'Copilot') THEN '3_OpenAI_Copilot_Native_Brain'
                    WHEN rc.user IN ('gemini-code-assist[bot]') THEN '4_Google_Gemini_Native_Brain'
                    WHEN rc.user IN ('claude[bot]') THEN '5_Anthropic_Claude_Native_Brain'
                    ELSE '6_Other_Bot_Engine'
                END AS brain_family,
                rc.commit_id,
                rc.original_commit_id,
                rc.position,
                rc.body,
                pr.id AS pr_id,
                pr.merged_at
            FROM parsed_rc rc
            JOIN '{parquet_dir}/repository.parquet' repo ON rc.repo_full_name = repo.full_name
            JOIN '{parquet_dir}/pull_request.parquet' pr ON pr.repo_id = repo.id AND pr.number = rc.pr_number
        )
        SELECT
            bot_name,
            brain_family,
            COUNT(*) AS total_inline_comments,
            COUNT(DISTINCT pr_id) AS distinct_prs_reviewed,
            SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) AS comments_on_merged_prs,
            SUM(CASE WHEN merged_at IS NOT NULL AND (commit_id != original_commit_id OR position IS NULL) THEN 1 ELSE 0 END) AS addressed_before_merge,
            SUM(CASE WHEN merged_at IS NOT NULL AND commit_id = original_commit_id AND position IS NOT NULL THEN 1 ELSE 0 END) AS ignored_merged_untouched,
            ROUND(100.0 * SUM(CASE WHEN merged_at IS NOT NULL AND (commit_id != original_commit_id OR position IS NULL) THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS developer_action_reputation_pct,
            ROUND(100.0 * SUM(CASE WHEN merged_at IS NOT NULL AND commit_id = original_commit_id AND position IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS silent_ignore_rate_pct,
            ROUND(AVG(LENGTH(body)), 1) AS avg_comment_chars
        FROM joined
        GROUP BY bot_name, brain_family
        HAVING COUNT(*) >= 15
        ORDER BY total_inline_comments DESC
    """).fetchall()

    bot_rep_csv = paths.tables_dir / "review_bot_reputation_and_brain_log.csv"
    with open(bot_rep_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "bot_name", "brain_family", "total_inline_comments", "distinct_prs_reviewed",
            "comments_on_merged_prs", "addressed_before_merge", "ignored_merged_untouched",
            "developer_action_reputation_pct", "silent_ignore_rate_pct", "avg_comment_chars",
        ])
        w.writerows(bot_reputation_rows)

    brain_family_impact_rows = con.execute(f"""
        WITH pr_base AS (
            SELECT
                pr.id AS pr_id,
                pr.repo_id,
                pr.agent,
                pr.created_at::TIMESTAMP AS created_ts,
                pr.merged_at::TIMESTAMP AS merged_ts,
                t.type AS task_type,
                (LOWER(pr.title) LIKE '%revert%' OR LOWER(pr.title) LIKE '%regression%' OR LOWER(pr.title) LIKE '%hotfix%' OR LOWER(pr.body) LIKE '%regression%') AS is_reg_or_revert
            FROM '{parquet_dir}/pull_request.parquet' pr
            LEFT JOIN '{parquet_dir}/pr_task_type.parquet' t ON pr.id = t.id
        ),
        defect_prs AS (
            SELECT pr_id, repo_id, created_ts, (task_type = 'fix') AS is_fix, is_reg_or_revert
            FROM pr_base
            WHERE task_type = 'fix' OR is_reg_or_revert
        ),
        bot_brains AS (
            SELECT
                pr_id,
                CASE
                    WHEN user IN ({sast_bots_sql}) THEN '1_Deterministic_SAST_Brain'
                    WHEN user IN ({rag_bots_sql}) THEN '2_MultiModel_RAG_Agentic_Brain'
                    WHEN user IN ('copilot-pull-request-reviewer[bot]', 'chatgpt-codex-connector[bot]') THEN '3_OpenAI_Copilot_Native_Brain'
                    WHEN user IN ('gemini-code-assist[bot]') THEN '4_Google_Gemini_Native_Brain'
                    WHEN user IN ('claude[bot]') THEN '5_Anthropic_Claude_Native_Brain'
                    ELSE NULL
                END AS brain_family
            FROM (
                SELECT pr_id, user FROM '{parquet_dir}/pr_reviews.parquet' WHERE user_type = 'Bot'
                UNION ALL
                SELECT pr_id, user FROM '{parquet_dir}/pr_comments.parquet' WHERE user_type = 'Bot'
            )
            WHERE brain_family IS NOT NULL
        ),
        pr_brain AS (
            SELECT pr_id, MIN(brain_family) AS primary_brain_family
            FROM bot_brains
            GROUP BY pr_id
        ),
        human_revs AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' THEN 1 ELSE 0 END) AS h_revs,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        ),
        post_outcomes AS (
            SELECT
                p1.pr_id,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS fix_14d,
                SUM(CASE WHEN p2.is_fix AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY THEN 1 ELSE 0 END) AS fix_90d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 14 DAY THEN 1 ELSE 0 END) AS reg_14d,
                SUM(CASE WHEN p2.is_reg_or_revert AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY THEN 1 ELSE 0 END) AS reg_90d
            FROM pr_base p1
            JOIN pr_brain b ON p1.pr_id = b.pr_id
            LEFT JOIN defect_prs p2 ON p1.repo_id = p2.repo_id AND p1.pr_id != p2.pr_id AND p2.created_ts > p1.merged_ts AND p2.created_ts <= p1.merged_ts + INTERVAL 90 DAY
            WHERE p1.merged_ts IS NOT NULL
            GROUP BY p1.pr_id
        )
        SELECT
            b.primary_brain_family,
            COUNT(DISTINCT p.pr_id) AS total_prs,
            SUM(CASE WHEN p.merged_ts IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
            ROUND(100.0 * AVG(CASE WHEN p.merged_ts IS NOT NULL THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
            ROUND(100.0 * AVG(CASE WHEN COALESCE(hr.h_cr, 0) > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE COALESCE(hr.h_revs, 0) > 0), 2) AS human_veto_rate_when_human_reviewed_pct,
            ROUND(100.0 * AVG(CASE WHEN po.fix_14d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE p.merged_ts IS NOT NULL), 2) AS post_merge_fix_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN po.fix_90d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE p.merged_ts IS NOT NULL), 2) AS post_merge_fix_90d_pct,
            ROUND(100.0 * AVG(CASE WHEN po.reg_14d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE p.merged_ts IS NOT NULL), 2) AS post_merge_reg_14d_pct,
            ROUND(100.0 * AVG(CASE WHEN po.reg_90d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE p.merged_ts IS NOT NULL), 2) AS post_merge_reg_90d_pct
        FROM pr_brain b
        JOIN pr_base p ON b.pr_id = p.pr_id
        LEFT JOIN human_revs hr ON p.pr_id = hr.pr_id
        LEFT JOIN post_outcomes po ON p.pr_id = po.pr_id
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    # 6. Organization / Repository Owner Governance Archetypes
    org_archetype_rows = con.execute(f"""
        WITH org_classified AS (
            SELECT
                r.id AS repo_id,
                r.full_name,
                SPLIT_PART(r.full_name, '/', 1) AS owner_name,
                r.stars,
                r.forks,
                r.language,
                CASE
                    WHEN LOWER(SPLIT_PART(r.full_name, '/', 1)) IN ('microsoft', 'azure', 'google', 'googleapis', 'aws', 'awslabs', 'vercel', 'oven-sh', 'tencent', 'elastic', 'cloudflare', 'getsentry', 'datadog', 'airbytehq', 'calcom', 'supabase', 'stripe', 'shopify', 'meta', 'facebook', 'ibm', 'redhat', 'oracle', 'intel', 'nvidia')
                        THEN '1_Enterprise_BigTech_Cloud_Vendor'
                    WHEN LOWER(SPLIT_PART(r.full_name, '/', 1)) IN ('apache', 'julialang', 'owasp', 'git', 'dotnet', 'rust-lang', 'python', 'golang', 'kubernetes', 'cncf', 'linux', 'llvm', 'eclipse', 'mozilla', 'freebsd', 'open-telemetry', 'modelcontextprotocol', 'thealgorithms')
                        THEN '2_OSS_Foundation_Standards_Consortium'
                    WHEN LOWER(SPLIT_PART(r.full_name, '/', 1)) IN ('langchain-ai', 'significant-gravitas', 'promptfoo', 'mastra-ai', 'tracecathq', 'agentops-ai', 'openagentsinc', 'vlm-run', 'giselles-ai', 'crewaiinc', 'autogen', 'llamaindex', 'dify', 'berriai', 'ollama', 'huggingface', 'vllm-project', 'sgl-project', 'all-hands-ai', 'continuedev', 'cline')
                        THEN '3_AI_Native_Agent_Tooling_Org'
                    WHEN r.stars >= 2500
                        THEN '4_High_Traction_Community_Org_2500plus_Stars'
                    ELSE '5_Standard_Community_or_Individual_Repo'
                END AS org_archetype
            FROM '{parquet_dir}/repository.parquet' r
        ),
        rev_flags AS (
            SELECT
                pr_id,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' THEN 1 ELSE 0 END) AS h_revs,
                SUM(CASE WHEN user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS h_cr,
                ARG_MAX(state, submitted_at) FILTER (WHERE user_type = 'User' AND user NOT LIKE '%[bot]%' AND LOWER(user) NOT LIKE '%-bot' AND state IN ('APPROVED', 'CHANGES_REQUESTED')) AS final_h_state
            FROM '{parquet_dir}/pr_reviews.parquet'
            GROUP BY pr_id
        )
        SELECT
            oc.org_archetype,
            COUNT(DISTINCT oc.repo_id) AS repos_count,
            COUNT(pr.id) AS total_agent_prs,
            ROUND(100.0 * AVG(CASE WHEN pr.merged_at IS NOT NULL THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
            ROUND(100.0 * AVG(CASE WHEN COALESCE(rf.h_revs, 0) > 0 THEN 1.0 ELSE 0.0 END), 2) AS human_reviewed_rate_pct,
            ROUND(100.0 * AVG(CASE WHEN COALESCE(rf.h_revs, 0) = 0 THEN 1.0 ELSE 0.0 END), 2) AS silent_gate_bypass_pct,
            ROUND(100.0 * AVG(CASE WHEN COALESCE(rf.h_cr, 0) > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE COALESCE(rf.h_revs, 0) > 0), 2) AS human_veto_rate_when_reviewed_pct,
            ROUND(100.0 * AVG(CASE WHEN pr.merged_at IS NOT NULL AND rf.final_h_state = 'CHANGES_REQUESTED' THEN 1.0 ELSE 0.0 END) FILTER (WHERE COALESCE(rf.h_cr, 0) > 0), 2) AS human_veto_override_pct
        FROM org_classified oc
        JOIN '{parquet_dir}/pull_request.parquet' pr ON oc.repo_id = pr.repo_id
        LEFT JOIN rev_flags rf ON pr.id = rf.pr_id
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    org_csv = paths.tables_dir / "organization_governance_archetypes_log.csv"
    with open(org_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "org_archetype", "repos_count", "total_agent_prs", "merge_rate_pct",
            "human_reviewed_rate_pct", "silent_gate_bypass_pct",
            "human_veto_rate_when_reviewed_pct", "human_veto_override_pct",
        ])
        w.writerows(org_archetype_rows)

    # Partitioned post-merge incidents
    post_merge_incidents = con.execute(f"""
        SELECT
            CASE
                WHEN LOWER(c.body) LIKE '%backport failed%'
                  OR LOWER(c.body) LIKE '%failed to apply on top of branch%'
                  OR LOWER(c.body) LIKE '%unable to cherry-pick%'
                THEN 'Backport_CherryPick_Failure_Comment'
                ELSE 'Post_Merge_Failure_Comment'
            END AS incident_type,
            pr.id AS pr_id,
            repo.full_name AS repo_full_name,
            pr.number AS pr_number,
            pr.html_url,
            pr.agent,
            pr.merged_at,
            c.created_at AS incident_timestamp,
            c.user AS actor,
            REPLACE(REPLACE(SUBSTRING(c.body, 1, 240), CHR(10), ' '), CHR(13), ' ') AS details
        FROM '{parquet_dir}/pull_request.parquet' pr
        JOIN '{parquet_dir}/repository.parquet' repo ON pr.repo_id = repo.id
        JOIN '{parquet_dir}/pr_comments.parquet' c ON pr.id = c.pr_id
        WHERE pr.merged_at IS NOT NULL
          AND c.created_at > pr.merged_at
          AND c.user_type = 'User'
          AND c.user NOT LIKE '%[bot]%'
          AND LOWER(c.user) NOT LIKE '%-bot'
          AND (LOWER(c.body) LIKE '%revert%' OR LOWER(c.body) LIKE '%broke%' OR LOWER(c.body) LIKE '%regression%' OR LOWER(c.body) LIKE '%bug%' OR LOWER(c.body) LIKE '%fail%' OR LOWER(c.body) LIKE '%broken%')

        UNION ALL

        SELECT
            'Explicit_Revert_PR' AS incident_type,
            pr.id AS pr_id,
            repo.full_name AS repo_full_name,
            pr.number AS pr_number,
            pr.html_url,
            pr.agent,
            pr.merged_at,
            pr.created_at AS incident_timestamp,
            pr.user AS actor,
            REPLACE(REPLACE(SUBSTRING(pr.title || ' | ' || COALESCE(pr.body, ''), 1, 240), CHR(10), ' '), CHR(13), ' ') AS details
        FROM '{parquet_dir}/pull_request.parquet' pr
        JOIN '{parquet_dir}/repository.parquet' repo ON pr.repo_id = repo.id
        WHERE LOWER(pr.title) LIKE 'revert %' OR LOWER(pr.title) LIKE '%revert "%' OR LOWER(pr.body) LIKE '%this reverts commit%'

        UNION ALL

        SELECT
            'Linked_Issue_Still_Open_After_Merge' AS incident_type,
            pr.id AS pr_id,
            repo.full_name AS repo_full_name,
            pr.number AS pr_number,
            pr.html_url,
            pr.agent,
            pr.merged_at,
            i.created_at AS incident_timestamp,
            i.user AS actor,
            REPLACE(REPLACE(SUBSTRING('Issue #' || CAST(i.number AS VARCHAR) || ' (' || i.state || '): ' || COALESCE(i.title, ''), 1, 240), CHR(10), ' '), CHR(13), ' ') AS details
        FROM '{parquet_dir}/related_issue.parquet' ri
        JOIN '{parquet_dir}/issue.parquet' i ON ri.issue_id = i.id
        JOIN '{parquet_dir}/pull_request.parquet' pr ON ri.pr_id = pr.id
        JOIN '{parquet_dir}/repository.parquet' repo ON pr.repo_id = repo.id
        WHERE pr.merged_at IS NOT NULL AND i.state = 'open'
    """).fetchall()

    post_merge_breakdown: dict[str, int] = {}
    post_merge_distinct_prs: dict[str, set] = {}
    for row in post_merge_incidents:
        itype = row[0]
        post_merge_breakdown[itype] = post_merge_breakdown.get(itype, 0) + 1
        post_merge_distinct_prs.setdefault(itype, set()).add(row[1])
    post_merge_distinct_prs_counts = {k: len(v) for k, v in post_merge_distinct_prs.items()}

    post_merge_csv = paths.tables_dir / "post_merge_failures_and_reverts_log.csv"
    with open(post_merge_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "incident_type", "pr_id", "repo_full_name", "pr_number", "html_url",
            "agent", "merged_at", "incident_timestamp", "actor", "details",
        ])
        w.writerows(post_merge_incidents)

    # 7. Anonymous Live GitHub `.patch` & Post-Merge Issue Verification on High-Risk Merged PRs
    live_targets = [
        ("J-Tech-Japan/Sekiban", 706, "2025-07-19T06:28:11Z"),
        ("oven-sh/bun", 19766, "2025-05-22T01:41:44Z"),
        ("Tencent/ncnn", 6204, "2025-07-23T06:06:15Z"),
        ("Edgenesis/shifu", 1202, "2025-06-05T07:53:40Z"),
        ("DaveSkender/Stock.Indicators", 1371, "2025-07-17T06:54:28Z"),
    ]
    live_verifications = [
        fetch_live_github_patch_and_postmerge(repo, num, m_at)
        for repo, num, m_at in live_targets
    ]

    output = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dataset_attribution": "H. Li, H. Zhang, and A. E. Hassan, 'AIDev: Studying AI coding agents on GitHub,' Proc. MSR 2026, doi: 10.1145/3793302.3797249 (Zenodo: 10.5281/zenodo.16899501)",
        "generated_audit_logs": {
            "unaddressed_patch_warnings_csv": "raw_patch_unaddressed_warnings_log.csv",
            "unaddressed_patch_warnings_count": len(unaddressed_rows),
            "human_veto_overrides_and_dismissals_csv": "human_veto_overrides_and_dismissals_log.csv",
            "human_veto_overrides_and_dismissals_count": len(veto_and_dismissed_rows),
            "post_merge_failures_and_reverts_csv": "post_merge_failures_and_reverts_log.csv",
            "post_merge_failures_and_reverts_count": len(post_merge_incidents),
            "post_merge_incidents_breakdown_by_type": post_merge_breakdown,
            "post_merge_incidents_distinct_prs_by_type": post_merge_distinct_prs_counts,
            "explicit_revert_prs_count": post_merge_breakdown.get("Explicit_Revert_PR", 0),
            "genuine_post_merge_failure_comments_distinct_prs": post_merge_distinct_prs_counts.get("Post_Merge_Failure_Comment", 0),
            "review_bot_reputation_and_brain_csv": "review_bot_reputation_and_brain_log.csv",
            "review_bot_reputation_and_brain_count": len(bot_reputation_rows),
            "organization_governance_archetypes_csv": "organization_governance_archetypes_log.csv",
            "organization_governance_archetypes_count": len(org_archetype_rows),
            "normalized_post_merge_hazard_csv": "normalized_post_merge_hazard_log.csv",
            "normalized_post_merge_hazard_rows_count": len(normalized_hazard_rows) + len(within_shared_repo_rows),
        },
        "raw_code_patch_analysis": {
            "total_inline_patch_reviews": raw_patch_summary[0],
            "distinct_prs_with_patches": raw_patch_summary[1],
            "distinct_files_patched": raw_patch_summary[2],
            "bot_inline_patch_comments": raw_patch_summary[3],
            "human_inline_patch_comments": raw_patch_summary[4],
            "avg_diff_hunk_chars": round(float(raw_patch_summary[5]), 1),
            "linter_type_suppressions_in_patch": raw_patch_summary[6],
            "broad_exception_handlers_in_patch": raw_patch_summary[7],
            "skipped_tests_in_patch": raw_patch_summary[8],
            "security_and_bug_warnings_on_patch": raw_patch_summary[9],
            "security_and_bug_warnings_on_merged_prs": raw_patch_summary[10],
            "machine_to_machine_agent_prompts_in_comments": raw_patch_summary[11],
            "unaddressed_warnings_merged_as_is_by_actor": [
                {
                    "actor_type": r[0],
                    "total_merged_patch_comments": r[1],
                    "unaddressed_merged_as_is": r[2],
                    "unaddressed_rate_pct": r[3],
                    "unaddressed_security_or_bug_merged_as_is": r[4],
                }
                for r in unaddressed_by_actor
            ],
        },
        "human_veto_overrides_and_dismissals": {
            "by_cohort": [
                {
                    "cohort": r[0],
                    "prs_with_human_changes_requested": r[1],
                    "merged_total": r[2],
                    "merged_overriding_final_human_cr": r[3],
                    "merged_with_zero_human_approval": r[4],
                    "veto_override_rate_pct": r[5],
                }
                for r in override_by_cohort
            ],
            "timeline_review_dismissed_total_events": int(timeline_counts[0]),
            "timeline_review_dismissed_distinct_prs": int(timeline_counts[1]),
            "timeline_review_dismissed_merged_events": int(timeline_counts[2]),
            "timeline_head_ref_force_pushed_events": int(timeline_counts[3]),
        },
        "conway_centralization_and_reviewer_burnout": conway_metrics,
        "post_merge_multi_horizon_regression_velocity_7d_14d_30d_90d": [
            {
                "review_regime": r[0],
                "merged_prs": r[1],
                "uncensored_90d_n": r[2],
                "fix_7d_pct": r[3],
                "fix_14d_pct": r[4],
                "fix_30d_pct": r[5],
                "fix_90d_pct": r[6],
                "reg_7d_pct": r[7],
                "reg_14d_pct": r[8],
                "reg_30d_pct": r[9],
                "reg_90d_pct": r[10],
                "reg_90d_strictly_uncensored_pct": r[11],
            }
            for r in regime_regression_rows
        ],
        "normalized_post_merge_hazard_analysis": {
            "repo_volume_confound_note": "Silent_Gate repos host higher median PR velocity than reviewed repos; normalized per-100-repo-PRs, direct post-merge bug comments, and within-shared-repo controls resolve this confound.",
            "by_regime_normalized": [
                {
                    "review_regime": r[0],
                    "merged_prs": int(r[1]),
                    "median_repo_agent_prs": float(r[2]),
                    "mean_repo_agent_prs": float(r[3]),
                    "mean_repo_prs_per_day": float(r[4]),
                    "raw_reg_14d_pct": float(r[5]),
                    "reg_14d_per_100_repo_prs": float(r[6]),
                    "direct_post_merge_bug_comm_pct": float(r[7]),
                    "reopened_pct": float(r[8]),
                }
                for r in normalized_hazard_rows
            ],
            "within_shared_repo_matched_control": [
                {
                    "cohort": r[0],
                    "shared_repos": int(r[1]),
                    "merged_prs": int(r[2]),
                    "fix_14d_pct": float(r[3]),
                    "reg_14d_pct": float(r[4]),
                    "reg_30d_pct": float(r[5]),
                    "mean_reg_14d_cnt": float(r[6]),
                }
                for r in within_shared_repo_rows
            ],
        },
        "review_bot_reputation_matrix": [
            {
                "bot_name": r[0],
                "brain_family": r[1],
                "total_inline_comments": r[2],
                "distinct_prs_reviewed": r[3],
                "comments_on_merged_prs": r[4],
                "addressed_before_merge": r[5],
                "ignored_merged_untouched": r[6],
                "developer_action_reputation_pct": r[7],
                "silent_ignore_rate_pct": r[8],
                "avg_comment_chars": r[9],
            }
            for r in bot_reputation_rows
        ],
        "review_bot_brain_family_impact": [
            {
                "brain_family": r[0],
                "total_prs": r[1],
                "merged_prs": r[2],
                "merge_rate_pct": r[3],
                "human_veto_rate_when_human_reviewed_pct": r[4],
                "post_merge_fix_14d_pct": r[5],
                "post_merge_fix_90d_pct": r[6],
                "post_merge_reg_14d_pct": r[7],
                "post_merge_reg_90d_pct": r[8],
            }
            for r in brain_family_impact_rows
        ],
        "organization_governance_archetypes": [
            {
                "org_archetype": r[0],
                "repos_count": r[1],
                "total_agent_prs": r[2],
                "merge_rate_pct": r[3],
                "human_reviewed_rate_pct": r[4],
                "silent_gate_bypass_pct": r[5],
                "human_veto_rate_when_reviewed_pct": r[6],
                "human_veto_override_pct": r[7],
            }
            for r in org_archetype_rows
        ],
        "live_github_patch_and_postmerge_probes": live_verifications,
    }

    out_json = paths.results_dir / "raw_patch_and_sociotechnical_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(
        "Raw Code Patches Inspected: %d diff_hunks across %d PRs and %d files (avg %.1f chars)",
        raw_patch_summary[0], raw_patch_summary[1], raw_patch_summary[2], float(raw_patch_summary[5]),
    )
    logger.info("Wrote %d unaddressed warnings to %s", len(unaddressed_rows), unaddressed_csv)
    logger.info("Wrote %d veto override/dismissal rows to %s", len(veto_and_dismissed_rows), overrides_csv)
    logger.info("Wrote %d post-merge incident rows to %s", len(post_merge_incidents), post_merge_csv)
    logger.info("Wrote %d bot reputation rows to %s", len(bot_reputation_rows), bot_rep_csv)
    logger.info("Wrote %d org governance rows to %s", len(org_archetype_rows), org_csv)
    logger.info("Wrote %d normalized hazard rows to %s", len(normalized_hazard_rows) + len(within_shared_repo_rows), norm_hazard_csv)
    logger.info("Wrote summary JSON to %s", out_json)


if __name__ == "__main__":
    main()
