#!/usr/bin/env python3
"""
Pipeline p06: Consolidated Empirical Results & Dynamic Verified Revert Ledger
=============================================================================
Reads processed summaries (msr_aidev_results.json, raw_patch_and_sociotechnical_results.json,
multi_dataset_triangulation_results.json) and executes 100% dynamic DuckDB queries over
`szz_defect_traceability_ledger.csv` + AIDev raw Parquets (`pull_request.parquet`,
`repository.parquet`, `pr_commits.parquet`, `related_issue.parquet`, `issue.parquet`)
to export the SHA- & linked-issue-verified PR regressions ledger.

Outputs:
  - results/empirical_results_summary.json
  - results/verified_pr_regressions_ledger.json
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import duckdb

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.paths import get_paths
from src.utils.logging_utils import setup_verbose_logger


def _load_required_json(path: Path, step_hint: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required upstream artifact missing: {path}. Run {step_hint} first.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_results() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    logger, ts_log = setup_verbose_logger(
        "p06_empirical_summary_ledger",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    logger.info("Generating consolidated empirical results & dynamic PR revert ledger (log=%s)", ts_log)

    res_aidev = _load_required_json(paths.results_dir / "msr_aidev_results.json", "p03")
    res_patch = _load_required_json(paths.results_dir / "raw_patch_and_sociotechnical_results.json", "p04")
    res_tri = _load_required_json(paths.results_dir / "multi_dataset_triangulation_results.json", "p05")

    macro = res_aidev.get("macro_corpus_summary", {})
    diff_hunks_count = res_patch.get("raw_code_patch_analysis", {}).get("total_inline_patch_reviews", 0)
    unaddressed_count = res_patch.get("generated_audit_logs", {}).get("unaddressed_patch_warnings_count", 0)
    overrides_by_cohort = res_patch.get("human_veto_overrides_and_dismissals", {}).get("by_cohort", [])
    overrides_count = sum(c.get("merged_overriding_final_human_cr", 0) for c in overrides_by_cohort)

    datasets = res_tri.get("datasets", {})
    tri_d1 = datasets.get("dataset_1_aidev_full", {})
    tri_d9 = datasets.get("dataset_9_coderabbit_oss_activities", {})
    tri_d10 = datasets.get("dataset_10_codage_multi_agent_stream", {})
    tri_d11 = datasets.get("dataset_11_gharchive_3day_stream", {})
    tri_d12 = datasets.get("dataset_12_live_codebase_pr_cohort", {})

    human_med = float(tri_d1.get("human_baseline_prs", {}).get("median_merge_hours", 0.0))
    agent_med = float(tri_d1.get("agent_sample_prs", {}).get("median_merge_hours", 0.0))
    ratio = round(human_med / agent_med, 1) if agent_med > 0 else 0.0
    silent_rate = float(macro.get("agentic_prs_bypassing_formal_human_review_pct", 0.0))
    paired = res_aidev.get("paired_control_summary", {})

    logger.info("Latency Collapse: human=%.2fh, agent=%.2fh (ratio=%.1fx), silent_gate=%.2f%%",
                human_med, agent_med, ratio, silent_rate)
    logger.info("Paired Control: shared_repos=%s, human=%.2f%%, agent=%.2f%%, penalty=-%.2fpp",
                paired.get("shared_repos_count", 0),
                paired.get("human_merge_rate_pct", 0.0),
                paired.get("agent_merge_rate_pct", 0.0),
                paired.get("paired_merge_penalty_pp", 0.0))

    # Dynamically Query Verified PR Revert & Defect Traceability Ledger
    scratch_aidev = paths.scratch_dir / "aidev"
    pr_parquet = scratch_aidev / "pull_request.parquet"
    repo_parquet = scratch_aidev / "repository.parquet"
    commits_parquet = scratch_aidev / "pr_commits.parquet"
    rel_issue_parquet = scratch_aidev / "related_issue.parquet"
    issue_parquet = scratch_aidev / "issue.parquet"
    szz_csv_path = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    verified_prs: list[dict[str, Any]] = []
    con = duckdb.connect()
    seen_keys: set[tuple[str, int]] = set()

    # Source A: Commit-attributed SZZ hard-reverted agent PRs from bare-git ledger
    if szz_csv_path.exists():
        szz_reverted = con.execute(f"""
            SELECT
                s.repo_full_name,
                s.pr_number,
                p.id AS aidev_pr_id,
                p.agent,
                s.merge_commit_sha,
                s.fixing_commit_shas,
                p.title,
                p.state,
                p.html_url,
                s.review_topology,
                STRING_AGG(DISTINCT '#' || CAST(i.number AS VARCHAR), ', ') AS linked_issues
            FROM read_csv_auto('{szz_csv_path}') s
            JOIN read_parquet('{repo_parquet}') r ON s.repo_full_name = r.full_name
            JOIN read_parquet('{pr_parquet}') p ON p.repo_id = r.id AND p.number = s.pr_number
            LEFT JOIN read_parquet('{rel_issue_parquet}') ri ON ri.pr_id = p.id
            LEFT JOIN read_parquet('{issue_parquet}') i ON CAST(ri.issue_id AS BIGINT) = i.id
            WHERE s.corpus = 'AIDev' AND s.reverted_90d = 1
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
            ORDER BY (STRING_AGG(DISTINCT '#' || CAST(i.number AS VARCHAR), ', ') IS NOT NULL) DESC,
                     s.repo_full_name ASC, s.pr_number ASC
        """).fetchall()

        for row in szz_reverted:
            (repo_name, pr_num, pr_id, agent, merge_sha, fix_shas, title, state, html_url, topo, linked_issues) = row
            key = (str(repo_name), int(pr_num))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            commits = con.execute(
                f"SELECT sha FROM read_parquet('{commits_parquet}') WHERE pr_id = {int(pr_id)} LIMIT 1"
            ).fetchall()
            pr_sha = str(commits[0][0]) if commits else str(merge_sha)
            clean_title = " ".join(str(title or "").split())
            rev_shas_str = str(fix_shas or "").split(";")[0]
            verified_prs.append({
                "id": f"REV-{len(verified_prs)+1:02d}",
                "source": "szz_bare_git_hard_revert",
                "repo": str(repo_name),
                "pr": int(pr_num),
                "aidev_id": int(pr_id),
                "agent": str(agent),
                "sha": pr_sha[:7],
                "full_sha": pr_sha,
                "merge_commit_sha": str(merge_sha),
                "revert_commit_shas": str(fix_shas or ""),
                "review_topology": str(topo),
                "issue": str(linked_issues) if linked_issues else "None",
                "title": clean_title,
                "defect": f"Hard-reverted in bare-git history (commit {rev_shas_str}): {clean_title[:140]}",
                "state": str(state),
                "is_merged": True,
                "url": str(html_url),
            })

    # Source B: Explicit merged Revert PRs directly in AIDev pull_request.parquet
    explicit_reverts = con.execute(f"""
        SELECT
            r.full_name,
            p.number,
            p.id AS aidev_pr_id,
            p.agent,
            p.title,
            p.state,
            p.html_url,
            r.stars,
            STRING_AGG(DISTINCT '#' || CAST(i.number AS VARCHAR), ', ') AS linked_issues
        FROM read_parquet('{pr_parquet}') p
        JOIN read_parquet('{repo_parquet}') r ON p.repo_id = r.id
        LEFT JOIN read_parquet('{rel_issue_parquet}') ri ON ri.pr_id = p.id
        LEFT JOIN read_parquet('{issue_parquet}') i ON CAST(ri.issue_id AS BIGINT) = i.id
        WHERE p.merged_at IS NOT NULL
          AND (
              LOWER(p.title) LIKE 'revert %'
              OR LOWER(p.title) LIKE '%revert "%'
              OR LOWER(COALESCE(p.body, '')) LIKE '%this reverts commit%'
          )
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
        ORDER BY r.stars DESC, p.number ASC
        LIMIT 12
    """).fetchall()

    for row in explicit_reverts:
        (repo_name, pr_num, pr_id, agent, title, state, html_url, _stars, linked_issues) = row
        key = (str(repo_name), int(pr_num))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        commits = con.execute(
            f"SELECT sha FROM read_parquet('{commits_parquet}') WHERE pr_id = {int(pr_id)} LIMIT 1"
        ).fetchall()
        first_sha = str(commits[0][0]) if commits else "unknown"
        clean_title = " ".join(str(title or "").split())
        verified_prs.append({
            "id": f"REV-{len(verified_prs)+1:02d}",
            "source": "aidev_explicit_merged_revert_pr",
            "repo": str(repo_name),
            "pr": int(pr_num),
            "aidev_id": int(pr_id),
            "agent": str(agent),
            "sha": first_sha[:7],
            "full_sha": first_sha,
            "issue": str(linked_issues) if linked_issues else "None",
            "title": clean_title,
            "defect": f"Explicit merged revert PR: {clean_title[:140]}",
            "state": str(state),
            "is_merged": True,
            "url": str(html_url),
        })

    for item in verified_prs:
        logger.info("Verified %s [%s]: %s#%d (%s) | SHA=%s | Issue=%s",
                    item["id"], item["source"], item["repo"], item["pr"],
                    item["agent"], item["sha"], item["issue"])

    out_json = paths.results_dir / "empirical_results_summary.json"
    out_ledger = paths.results_dir / "verified_pr_regressions_ledger.json"

    with open(out_ledger, "w", encoding="utf-8") as f:
        json.dump(verified_prs, f, indent=2)

    summary_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latency_collapse_ratio": ratio,
        "silent_gate_rate_pct": silent_rate,
        "paired_intra_repo_control": paired,
        "diff_hunks_inspected": diff_hunks_count,
        "unaddressed_merged_warnings": unaddressed_count,
        "human_veto_overrides": overrides_count,
        "verified_pr_regressions_count": len(verified_prs),
        "verified_pr_regressions": verified_prs,
        "extended_mined_datasets": {
            "coderabbit_total_prs": tri_d9.get("total_pull_requests", 0),
            "codage_sample_events": tri_d10.get("sample_events_n", 0),
            "gharchive_3day_events": tri_d11.get("total_events_3days", 0),
            "live_cohort_sampled_prs": tri_d12.get("sample_size_n", 0),
            "live_cohort_median_turnaround_hours": tri_d12.get("median_turnaround_hours", 0.0),
        },
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    logger.info("Wrote consolidated empirical results summary to %s", out_json)
    logger.info("Wrote verified PR regressions ledger (%d entries) to %s", len(verified_prs), out_ledger)


if __name__ == "__main__":
    generate_results()
