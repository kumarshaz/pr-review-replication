#!/usr/bin/env python3
import csv
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class SWEPRBenchHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_2_swe_prbench"

    @property
    def dataset_name(self) -> str:
        return "SWE-PRBench"

    @property
    def primary_entity(self) -> str:
        return "Autonomous Code Review Benchmark"

    @property
    def lemon_market_implication(self) -> str:
        return "Commercial AI review bots generate substantial hallucinated/superficial noise across performance and feature PRs requiring human filtering"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/swebench/swe_prbench_prs.parquet",
            "scratch/swebench/swe_prbench_eval.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["code_review_benchmark"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_swe = self.scratch_path("swebench")
        prb_prs_path = os.path.join(scratch_swe, "swe_prbench_prs.parquet")
        prb_eval_path = os.path.join(scratch_swe, "swe_prbench_eval.parquet")

        prb_row = con.execute(f"""
            SELECT
                COUNT(*) AS n_prs,
                COUNT(DISTINCT repo) AS n_repos,
                ROUND(AVG(rvs_score), 3) AS mean_rvs,
                ROUND(MEDIAN(rvs_score), 3) AS median_rvs,
                ROUND(AVG(num_substantive_comments), 2) AS mean_substantive_comments,
                ROUND(AVG(ai_comments_removed), 2) AS mean_ai_removed,
                SUM(ai_comments_removed) AS total_ai_removed,
                SUM(num_substantive_comments) AS total_substantive_comments,
                ROUND(100.0 * SUM(CASE WHEN ai_comments_removed > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS prs_with_ai_noise_pct,
                ROUND(100.0 * SUM(CASE WHEN has_requested_changes THEN 1 ELSE 0 END) / COUNT(*), 2) AS requested_changes_pct,
                ROUND(AVG(lines_added), 1) AS avg_additions,
                ROUND(AVG(lines_removed), 1) AS avg_deletions,
                ROUND(AVG(files_changed), 1) AS avg_files_changed,
                ROUND(AVG(rvs_breakdown.review_depth), 3) AS mean_review_depth,
                ROUND(AVG(rvs_breakdown.code_complexity), 3) AS mean_code_complexity,
                ROUND(AVG(rvs_breakdown.discussion_signal), 3) AS mean_discussion_signal,
                ROUND(AVG(rvs_breakdown.test_change_signal), 3) AS mean_test_change_signal,
                ROUND(AVG(rvs_breakdown.bug_fix_signal), 3) AS mean_bug_fix_signal,
                ROUND(AVG(num_unique_reviewers), 2) AS mean_unique_reviewers
            FROM read_parquet('{prb_prs_path}')
        """).fetchone()

        prb_eval_cnt = con.execute(f"SELECT COUNT(*) FROM read_parquet('{prb_eval_path}')").fetchone()[0]

        by_lang_rows = con.execute(f"""
            SELECT
                language,
                COUNT(*) AS n_prs,
                ROUND(AVG(rvs_score), 3) AS mean_rvs,
                ROUND(AVG(rvs_breakdown.review_depth), 3) AS review_depth,
                ROUND(AVG(rvs_breakdown.code_complexity), 3) AS code_complexity,
                ROUND(AVG(rvs_breakdown.test_change_signal), 3) AS test_change_signal,
                ROUND(AVG(num_substantive_comments), 2) AS mean_substantive_comments,
                ROUND(AVG(ai_comments_removed), 2) AS mean_ai_removed,
                ROUND(100.0 * AVG(CASE WHEN has_requested_changes THEN 1.0 ELSE 0.0 END), 2) AS requested_changes_pct
            FROM read_parquet('{prb_prs_path}')
            GROUP BY language
            ORDER BY n_prs DESC
        """).fetchall()

        by_type_rows = con.execute(f"""
            SELECT
                pr_type,
                COUNT(*) AS n_prs,
                ROUND(AVG(rvs_score), 3) AS mean_rvs,
                ROUND(AVG(rvs_breakdown.review_depth), 3) AS review_depth,
                ROUND(AVG(rvs_breakdown.code_complexity), 3) AS code_complexity,
                ROUND(AVG(rvs_breakdown.bug_fix_signal), 3) AS bug_fix_signal,
                ROUND(AVG(num_substantive_comments), 2) AS mean_substantive_comments,
                ROUND(AVG(ai_comments_removed), 2) AS mean_ai_removed,
                ROUND(100.0 * AVG(CASE WHEN has_requested_changes THEN 1.0 ELSE 0.0 END), 2) AS requested_changes_pct
            FROM read_parquet('{prb_prs_path}')
            GROUP BY pr_type
            ORDER BY n_prs DESC
        """).fetchall()

        by_diff_rows = con.execute(f"""
            SELECT
                difficulty,
                COUNT(*) AS n_prs,
                ROUND(AVG(rvs_score), 3) AS mean_rvs,
                ROUND(AVG(num_substantive_comments), 2) AS mean_substantive_comments,
                ROUND(AVG(ai_comments_removed), 2) AS mean_ai_removed,
                ROUND(100.0 * AVG(CASE WHEN has_requested_changes THEN 1.0 ELSE 0.0 END), 2) AS requested_changes_pct
            FROM read_parquet('{prb_prs_path}')
            GROUP BY difficulty
            ORDER BY n_prs DESC
        """).fetchall()

        csv_path = self.table_path("swe_prbench_rvs_breakdown_log.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "dimension", "group_value", "n_prs", "mean_rvs",
                "mean_review_depth_or_na", "mean_code_complexity_or_na",
                "mean_substantive_comments", "mean_ai_removed", "requested_changes_pct",
            ])
            for r in by_lang_rows:
                w.writerow(["language", r[0], r[1], r[2], r[3], r[4], r[6], r[7], r[8]])
            for r in by_type_rows:
                w.writerow(["pr_type", r[0], r[1], r[2], r[3], r[4], r[6], r[7], r[8]])
            for r in by_diff_rows:
                w.writerow(["difficulty", r[0], r[1], r[2], "N/A", "N/A", r[3], r[4], r[5]])

        return {
            "n_benchmark_prs": prb_row[0],
            "n_unique_repositories": prb_row[1],
            "n_eval_tasks": prb_eval_cnt,
            "mean_rvs_score": prb_row[2],
            "median_rvs_score": prb_row[3],
            "mean_substantive_comments_per_pr": prb_row[4],
            "total_substantive_comments": prb_row[7],
            "mean_ai_comments_removed_per_pr": prb_row[5],
            "total_ai_comments_removed": prb_row[6],
            "prs_with_ai_noise_filtered_pct": prb_row[8],
            "prs_requiring_changes_pct": prb_row[9],
            "avg_lines_added": prb_row[10],
            "avg_lines_removed": prb_row[11],
            "avg_files_changed": prb_row[12],
            "mean_unique_reviewers": prb_row[18],
            "rvs_breakdown_means": {
                "review_depth": prb_row[13],
                "code_complexity": prb_row[14],
                "discussion_signal": prb_row[15],
                "test_change_signal": prb_row[16],
                "bug_fix_signal": prb_row[17],
            },
            "by_language": [
                {
                    "language": r[0], "n_prs": r[1], "mean_rvs": r[2],
                    "review_depth": r[3], "code_complexity": r[4], "test_change_signal": r[5],
                    "mean_substantive_comments": r[6], "mean_ai_removed": r[7], "requested_changes_pct": r[8],
                }
                for r in by_lang_rows
            ],
            "by_pr_type": [
                {
                    "pr_type": r[0], "n_prs": r[1], "mean_rvs": r[2],
                    "review_depth": r[3], "code_complexity": r[4], "bug_fix_signal": r[5],
                    "mean_substantive_comments": r[6], "mean_ai_removed": r[7], "requested_changes_pct": r[8],
                }
                for r in by_type_rows
            ],
            "by_difficulty": [
                {
                    "difficulty": r[0], "n_prs": r[1], "mean_rvs": r[2],
                    "mean_substantive_comments": r[3], "mean_ai_removed": r[4], "requested_changes_pct": r[5],
                }
                for r in by_diff_rows
            ],
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        rvs_b = result.get("rvs_breakdown_means", {})
        return [
            self.primary_entity,
            f"{result['n_benchmark_prs']} PRs / {result['n_eval_tasks']} eval tasks",
            f"Mean RVS: {result['mean_rvs_score']} (depth={rvs_b.get('review_depth', 0):.3f}, comp={rvs_b.get('code_complexity', 0):.3f})",
            f"AI Noise Removed: {result['total_ai_comments_removed']} ({result['prs_with_ai_noise_filtered_pct']}% PRs)",
            self.lemon_market_implication,
        ]
