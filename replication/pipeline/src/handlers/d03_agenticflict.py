#!/usr/bin/env python3
import csv
import os
from typing import Any, Dict, List, Optional

import numpy as np

from src.handlers.base import BaseDatasetHandler


class AgenticFlictHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_3_agenticflict"

    @property
    def dataset_name(self) -> str:
        return "AgenticFlict"

    @property
    def primary_entity(self) -> str:
        return "Deterministic 3-Way Git Merge Simulation"

    @property
    def lemon_market_implication(self) -> str:
        return "Cleaned evaluated PRs exhibit elevated merge conflicts, super-linear conflict blast-radius escalation, and rising conflict rates at high commit churn"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/agenticflict/data/clean/agenticflict_pr_clean.csv",
            "scratch/agenticflict/data/clean/agenticflict_regions_clean.csv",
            "scratch/agenticflict/data/clean/agenticflict_conflict_files_clean.csv",
            "scratch/agenticflict/data/clean/agentflict_repo_clean.csv",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p02_explore_raw_data.py",
            "p05_multicorpus_triangulation.py",
            "p13_research_vector_probes.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["git_merge_conflicts", "debt_velocity_acceleration", "agent_conflict_profiles"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_af = self.scratch_path("agenticflict")
        scratch_aidev = self.scratch_path("aidev")
        af_pr_csv = os.path.join(scratch_af, "data", "clean", "agenticflict_pr_clean.csv")
        af_repo_csv = os.path.join(scratch_af, "data", "clean", "agentflict_repo_clean.csv")
        af_files_csv = os.path.join(scratch_af, "data", "clean", "agenticflict_conflict_files_clean.csv")

        # 1. Status code audit separating valid evaluations from ERR_REPO_FETCH / NULLs
        status_rows = con.execute(f"""
            SELECT
                COALESCE(status_code, 'NULL') AS status_code,
                COUNT(*) AS total_rows,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS conf_true,
                SUM(CASE WHEN conflict_label = false THEN 1 ELSE 0 END) AS conf_false,
                SUM(CASE WHEN conflict_label IS NULL THEN 1 ELSE 0 END) AS conf_null
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            GROUP BY 1
            ORDER BY total_rows DESC
        """).fetchall()

        # 2. Cleaned macro metrics excluding NULL conflict_label (true evaluated cohort)
        af_overall = con.execute(f"""
            SELECT
                COUNT(*) AS total_raw_rows,
                SUM(CASE WHEN conflict_label IS NOT NULL THEN 1 ELSE 0 END) AS total_evaluated_prs,
                SUM(CASE WHEN conflict_label IS NULL THEN 1 ELSE 0 END) AS excluded_null_rows,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS total_conflicts,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN conflict_label IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS eval_conflict_rate_pct,
                ROUND(AVG(num_conflict_files) FILTER (WHERE conflict_label IS NOT NULL), 2) AS avg_conflict_files,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label IS NOT NULL), 1) AS avg_conflict_lines,
                ROUND(MEDIAN(conflict_lines) FILTER (WHERE conflict_label IS NOT NULL), 1) AS median_conflict_lines,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label = true), 1) AS avg_conflict_lines_given_conflict
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
        """).fetchone()

        # 3. Per-agent conflict profile strictly over non-NULL evaluated rows
        af_agents = con.execute(f"""
            SELECT
                agent,
                COUNT(*) AS total_raw,
                SUM(CASE WHEN conflict_label IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_n,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN conflict_label IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS conflict_rate_pct,
                ROUND(AVG(num_conflict_files) FILTER (WHERE conflict_label IS NOT NULL), 2) AS avg_conflict_files,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label IS NOT NULL), 1) AS avg_conflict_lines,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label = true), 1) AS avg_conflict_lines_given_conflict
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            GROUP BY agent
            ORDER BY evaluated_n DESC
        """).fetchall()

        # 4. AIDev cross-match (strictly 3-way git merge overlap, separated by NULL/non-NULL)
        af_match = con.execute(f"""
            WITH sample_prs AS (
                SELECT DISTINCT (r.full_name || '#' || CAST(p.number AS VARCHAR)) AS pr_key
                FROM read_parquet('{scratch_aidev}/pull_request.parquet') p
                JOIN read_parquet('{scratch_aidev}/repository.parquet') r ON p.repo_id = r.id
            )
            SELECT
                COUNT(*) AS matched_prs_raw,
                SUM(CASE WHEN af.conflict_label IS NOT NULL THEN 1 ELSE 0 END) AS matched_prs_evaluated,
                SUM(CASE WHEN af.conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN af.conflict_label = true THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN af.conflict_label IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS eval_conflict_rate_pct,
                ROUND(AVG(af.conflict_lines) FILTER (WHERE af.conflict_label IS NOT NULL), 1) AS avg_conflict_lines,
                ROUND(AVG(af.conflict_lines) FILTER (WHERE af.conflict_label = true), 1) AS avg_conflict_lines_given_conflict
            FROM sample_prs sp
            JOIN read_csv('{af_pr_csv}', quote='"', escape='"', header=true) af ON sp.pr_key = af.pr_key
        """).fetchone()

        # 5. Cleaned 3-tier churn brackets (non-NULL evaluated)
        brackets_coarse = con.execute(f"""
            SELECT
                CASE
                    WHEN pr_churn < 500 THEN '<500 lines'
                    WHEN pr_churn >= 500 AND pr_churn < 5000 THEN '500-5000 lines'
                    ELSE '>=5000 lines'
                END AS bracket,
                COUNT(*) AS total_evaluated,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS conflict_rate_pct,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label = true), 1) AS avg_conflict_lines_given_conflict
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            WHERE conflict_label IS NOT NULL
            GROUP BY bracket
            ORDER BY MIN(pr_churn) ASC
        """).fetchall()

        # 6. Fine 6-tier churn escalation showing true Blast Radius scaling
        brackets_fine = con.execute(f"""
            SELECT
                CASE
                    WHEN pr_churn < 50 THEN '01_<50'
                    WHEN pr_churn < 200 THEN '02_50-200'
                    WHEN pr_churn < 500 THEN '03_200-500'
                    WHEN pr_churn < 1000 THEN '04_500-1k'
                    WHEN pr_churn < 5000 THEN '05_1k-5k'
                    ELSE '06_5k+'
                END AS bracket,
                COUNT(*) AS n_evaluated,
                ROUND(AVG(pr_churn), 1) AS mean_churn,
                ROUND(AVG(pr_changed_files), 2) AS mean_files,
                ROUND(AVG(pr_commits), 2) AS mean_commits,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS conflict_rate_pct,
                ROUND(AVG(conflict_lines) FILTER (WHERE conflict_label = true), 1) AS avg_conf_lines_if_conf,
                ROUND(AVG(max_region_lines) FILTER (WHERE conflict_label = true), 1) AS avg_max_region_if_conf
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            WHERE conflict_label IS NOT NULL
            GROUP BY bracket
            ORDER BY bracket ASC
        """).fetchall()

        # Fit empirical log-log blast-radius scaling exponent: log1p(conflict_lines) vs log1p(pr_churn)
        blast_pairs = con.execute(f"""
            SELECT pr_churn, conflict_lines
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            WHERE conflict_label = true AND pr_churn > 0 AND conflict_lines > 0
        """).fetchall()
        if len(blast_pairs) >= 2:
            arr_churn = np.array([r[0] for r in blast_pairs], dtype=float)
            arr_conf_lines = np.array([r[1] for r in blast_pairs], dtype=float)
            alpha_blast_slope, _blast_intercept = np.polyfit(np.log1p(arr_churn), np.log1p(arr_conf_lines), 1)
        else:
            alpha_blast_slope = 0.0

        # 7. Curated Active Repositories (>= 100 stars) monotonic conflict rate escalation
        curated_star_tiers = con.execute(f"""
            SELECT
                CASE
                    WHEN p.pr_churn < 500 THEN '<500 lines'
                    WHEN p.pr_churn <= 5000 THEN '500-5000 lines'
                    ELSE '>5000 lines'
                END AS tier,
                COUNT(*) AS evaluated_n,
                SUM(CASE WHEN p.conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN p.conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS conflict_rate_pct,
                ROUND(AVG(p.conflict_lines) FILTER (WHERE p.conflict_label = true), 1) AS avg_conf_lines_if_conf
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true) p
            JOIN read_csv('{af_repo_csv}', quote='"', escape='"', header=true) r
              ON p.repo_full_name = r.repo_full_name
            WHERE r.stargazer_count >= 100
              AND p.status_code IN ('OK_CONFLICT', 'OK_MERGE_CLEAN')
            GROUP BY 1
            ORDER BY MIN(p.pr_churn) ASC
        """).fetchall()

        # 8. Multi-turn commit thrashing escalation (1 -> 16+ commits)
        commit_thrash_rows = con.execute(f"""
            SELECT
                CASE
                    WHEN pr_commits <= 1 THEN '01_1_commit'
                    WHEN pr_commits <= 3 THEN '02_2-3_commits'
                    WHEN pr_commits <= 7 THEN '03_4-7_commits'
                    WHEN pr_commits <= 15 THEN '04_8-15_commits'
                    ELSE '05_16+_commits'
                END AS commit_bucket,
                COUNT(*) AS n_eval,
                ROUND(AVG(pr_churn), 1) AS mean_churn,
                ROUND(AVG(pr_changed_files), 2) AS mean_files,
                SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) AS conflicts,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS conflict_pct
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            WHERE conflict_label IS NOT NULL
            GROUP BY 1
            ORDER BY 1 ASC
        """).fetchall()

        # 9. File-spread escalation
        file_spread_rows = con.execute(f"""
            SELECT
                CASE
                    WHEN pr_changed_files <= 1 THEN '01_1_file'
                    WHEN pr_changed_files <= 3 THEN '02_2-3_files'
                    WHEN pr_changed_files <= 10 THEN '03_4-10_files'
                    WHEN pr_changed_files <= 30 THEN '04_11-30_files'
                    ELSE '05_31+_files'
                END AS file_bucket,
                COUNT(*) AS n_eval,
                ROUND(100.0 * SUM(CASE WHEN conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS conflict_pct,
                ROUND(AVG(num_conflict_files) FILTER (WHERE conflict_label = true), 2) AS avg_conf_files_if_conf
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true)
            WHERE conflict_label IS NOT NULL
            GROUP BY 1
            ORDER BY 1 ASC
        """).fetchall()

        # 10. Language & File Extension Conflict Hotspots
        lang_rows = con.execute(f"""
            SELECT
                COALESCE(r.primary_language, 'Unknown') AS primary_language,
                COUNT(*) AS evaluated_n,
                ROUND(100.0 * SUM(CASE WHEN p.conflict_label = true THEN 1 ELSE 0 END) / COUNT(*), 2) AS eval_conflict_pct,
                ROUND(AVG(p.pr_churn), 1) AS avg_churn,
                ROUND(AVG(p.pr_changed_files), 2) AS avg_files,
                ROUND(AVG(p.pr_commits), 2) AS avg_commits
            FROM read_csv('{af_pr_csv}', quote='"', escape='"', header=true) p
            JOIN read_csv('{af_repo_csv}', quote='"', escape='"', header=true) r
              ON p.repo_full_name = r.repo_full_name
            WHERE p.conflict_label IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 500
            ORDER BY evaluated_n DESC
        """).fetchall()

        ext_rows = con.execute(f"""
            SELECT
                COALESCE(file_ext, 'none') AS file_ext,
                COUNT(*) AS conflict_file_events,
                ROUND(AVG(conflict_lines_in_file), 1) AS avg_lines_in_file
            FROM read_csv('{af_files_csv}', quote='"', escape='"', header=true)
            GROUP BY 1
            ORDER BY conflict_file_events DESC
            LIMIT 15
        """).fetchall()

        csv_path = self.table_path("agenticflict_cleaned_scaling_log.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["dimension", "bucket_or_group", "evaluated_prs", "conflicts", "conflict_rate_pct", "avg_conflict_lines_if_conf", "notes"])
            for r in brackets_fine:
                w.writerow(["fine_churn_eval", r[0], r[1], r[5], r[6], r[7], f"mean_churn={r[2]}, mean_files={r[3]}, mean_commits={r[4]}"])
            for r in curated_star_tiers:
                w.writerow(["curated_100plus_stars", r[0], r[1], r[2], r[3], r[4], "stargazer_count >= 100"])
            for r in commit_thrash_rows:
                w.writerow(["commit_thrash_eval", r[0], r[1], r[4], r[5], "N/A", f"mean_churn={r[2]}, mean_files={r[3]}"])
            for r in file_spread_rows:
                w.writerow(["file_spread_eval", r[0], r[1], "N/A", r[2], "N/A", f"avg_conf_files_if_conf={r[3]}"])
            for r in lang_rows:
                w.writerow(["language_eval", r[0], r[1], "N/A", r[2], "N/A", f"avg_churn={r[3]}, avg_files={r[4]}, avg_commits={r[5]}"])

        return {
            "total_simulated_prs": af_overall[0],
            "total_evaluated_prs": af_overall[1],
            "excluded_null_rows": af_overall[2],
            "total_conflicts": af_overall[3],
            "macro_conflict_rate_pct": af_overall[4],
            "avg_conflict_files": af_overall[5],
            "avg_conflict_lines": af_overall[6],
            "median_conflict_lines": af_overall[7],
            "avg_conflict_lines_given_conflict": af_overall[8],
            "blast_radius_loglog_exponent": round(float(alpha_blast_slope), 4),
            "blast_radius_sample_n": len(blast_pairs),
            "status_code_breakdown": [
                {"status_code": r[0], "rows": r[1], "conf_true": r[2], "conf_false": r[3], "conf_null": r[4]}
                for r in status_rows
            ],
            "per_agent_conflict_profile": [
                {
                    "agent": r[0],
                    "total_raw": r[1],
                    "total_simulated": r[2],
                    "conflicts": r[3],
                    "conflict_rate_pct": r[4],
                    "avg_conflict_files": r[5],
                    "avg_conflict_lines": r[6],
                    "avg_conflict_lines_given_conflict": r[7],
                }
                for r in af_agents
            ],
            "aidev_sample_cross_match": {
                "matched_prs": af_match[1],
                "matched_prs_raw": af_match[0],
                "conflicts": af_match[2],
                "conflict_rate_pct": af_match[3],
                "avg_conflict_lines": af_match[4],
                "avg_conflict_lines_given_conflict": af_match[5],
                "modality_note": "Deterministic 3-way git merge simulation on AIDev curated repos (>=100 stars), excluding NULL evaluations",
            },
            "churn_bracket_acceleration": [
                {
                    "bracket": r[0],
                    "total_simulated": r[1],
                    "conflicts": r[2],
                    "conflict_rate_pct": r[3],
                    "avg_conflict_lines_given_conflict": r[4],
                }
                for r in brackets_coarse
            ],
            "churn_bracket_fine_blast_radius": [
                {
                    "bracket": r[0],
                    "n_evaluated": r[1],
                    "mean_churn": r[2],
                    "mean_files": r[3],
                    "mean_commits": r[4],
                    "conflicts": r[5],
                    "conflict_rate_pct": r[6],
                    "avg_conf_lines_if_conf": r[7],
                    "avg_max_region_if_conf": r[8],
                }
                for r in brackets_fine
            ],
            "curated_100plus_stars_acceleration": [
                {
                    "tier": r[0],
                    "evaluated_n": r[1],
                    "conflicts": r[2],
                    "conflict_rate_pct": r[3],
                    "avg_conf_lines_if_conf": r[4],
                }
                for r in curated_star_tiers
            ],
            "commit_thrash_escalation": [
                {
                    "commit_bucket": r[0],
                    "n_eval": r[1],
                    "mean_churn": r[2],
                    "mean_files": r[3],
                    "conflicts": r[4],
                    "conflict_pct": r[5],
                }
                for r in commit_thrash_rows
            ],
            "file_spread_escalation": [
                {"file_bucket": r[0], "n_eval": r[1], "conflict_pct": r[2], "avg_conf_files_if_conf": r[3]}
                for r in file_spread_rows
            ],
            "language_conflict_profile": [
                {"language": r[0], "evaluated_n": r[1], "eval_conflict_pct": r[2], "avg_churn": r[3], "avg_files": r[4], "avg_commits": r[5]}
                for r in lang_rows
            ],
            "top_conflict_file_extensions": [
                {"file_ext": r[0], "conflict_file_events": r[1], "avg_lines_in_file": r[2]}
                for r in ext_rows
            ],
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        cur = result.get("curated_100plus_stars_acceleration", [])
        cur_str = " -> ".join(f"{c['conflict_rate_pct']}%" for c in cur) if cur else "N/A"
        return [
            self.primary_entity,
            f"{result['total_evaluated_prs']:,} evaluated PRs ({result['total_simulated_prs']:,} raw rows)",
            f"Evaluated Conflict Rate: {result['macro_conflict_rate_pct']}% ({result['total_conflicts']:,} conflicts)",
            f"Star>=100 Churn: {cur_str}; Blast Slope={result['blast_radius_loglog_exponent']}",
            self.lemon_market_implication,
        ]
