#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class AIDevHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_1_aidev_full"

    @property
    def dataset_name(self) -> str:
        return "AIDev-Full & AIDev"

    @property
    def primary_entity(self) -> str:
        return "Pull Requests (Human vs Agent)"

    @property
    def lemon_market_implication(self) -> str:
        return "Agents emit verbose superficial markdown but trigger high post-merge defect induction"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/aidev/pull_request.parquet",
            "scratch/aidev/human_pull_request.parquet",
            "scratch/aidev/pr_timeline.parquet",
            "scratch/aidev/human_pr_task_type.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p02_explore_raw_data.py",
            "p03_aidev_macro_telemetry.py",
            "p04_diff_hunks_sociotech.py",
            "p05_multicorpus_triangulation.py",
            "p06_empirical_summary_ledger.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return [
            "pr_acceptance",
            "review_latency",
            "paired_control",
            "bot_comment_density",
            "supervisory_collapse",
            "agent_breakdown",
            "fix_churn",
            "defect_survival",
            "sentiment_dynamics",
        ]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_aidev = self.scratch_path("aidev")
        human_pr_path = os.path.join(scratch_aidev, "human_pull_request.parquet")
        agent_pr_path = os.path.join(scratch_aidev, "pull_request.parquet")

        h_metrics = con.execute(f"""
            SELECT
                COUNT(*) AS total_prs,
                SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
                ROUND(100.0 * SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS merge_rate_pct,
                ROUND(MEDIAN(EPOCH(CAST(merged_at AS TIMESTAMP) - CAST(created_at AS TIMESTAMP)) / 3600.0), 3) AS median_merge_hours,
                ROUND(AVG(LENGTH(COALESCE(body, ''))), 1) AS avg_body_chars,
                ROUND(MEDIAN(LENGTH(COALESCE(body, ''))), 1) AS median_body_chars,
                ROUND(100.0 * SUM(CASE WHEN LENGTH(TRIM(COALESCE(body, ''))) < 50 THEN 1 ELSE 0 END) / COUNT(*), 2) AS thin_rationale_pct
            FROM read_parquet('{human_pr_path}')
        """).fetchone()

        a_metrics = con.execute(f"""
            SELECT
                COUNT(*) AS total_prs,
                SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) AS merged_prs,
                ROUND(100.0 * SUM(CASE WHEN merged_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS merge_rate_pct,
                ROUND(MEDIAN(EPOCH(CAST(merged_at AS TIMESTAMP) - CAST(created_at AS TIMESTAMP)) / 3600.0), 3) AS median_merge_hours,
                ROUND(AVG(LENGTH(COALESCE(body, ''))), 1) AS avg_body_chars,
                ROUND(MEDIAN(LENGTH(COALESCE(body, ''))), 1) AS median_body_chars,
                ROUND(100.0 * SUM(CASE WHEN LENGTH(TRIM(COALESCE(body, ''))) < 50 THEN 1 ELSE 0 END) / COUNT(*), 2) AS thin_rationale_pct
            FROM read_parquet('{agent_pr_path}')
        """).fetchone()

        h_task_path = os.path.join(scratch_aidev, "human_pr_task_type.parquet")
        h_tasks = con.execute(f"""
            SELECT type, COUNT(*) AS count, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
            FROM read_parquet('{h_task_path}')
            GROUP BY type ORDER BY count DESC
        """).fetchall()

        agents_covered = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT agent FROM read_parquet('{agent_pr_path}') WHERE agent IS NOT NULL ORDER BY agent"
            ).fetchall()
        ]

        repo_path = os.path.join(scratch_aidev, "aidev_all_repo.parquet")
        user_path = os.path.join(scratch_aidev, "aidev_all_user.parquet")
        repo_cnt = (
            con.execute(f"SELECT COUNT(*) FROM read_parquet('{repo_path}')").fetchone()[0]
            if os.path.exists(repo_path)
            else 0
        )
        user_cnt = (
            con.execute(f"SELECT COUNT(*) FROM read_parquet('{user_path}')").fetchone()[0]
            if os.path.exists(user_path)
            else 0
        )

        return {
            "dataset_name": "AIDev-Full & AIDev Empirical Repository Benchmark",
            "sample_size_n": a_metrics[0],
            "merged_count": a_metrics[1],
            "merge_rate_pct": a_metrics[2],
            "human_baseline_prs": {
                "n": h_metrics[0],
                "merged_n": h_metrics[1],
                "merge_rate_pct": h_metrics[2],
                "median_merge_hours": h_metrics[3],
                "avg_body_chars": h_metrics[4],
                "median_body_chars": h_metrics[5],
                "thin_rationale_pct": h_metrics[6],
            },
            "agent_sample_prs": {
                "n": a_metrics[0],
                "merged_n": a_metrics[1],
                "merge_rate_pct": a_metrics[2],
                "median_merge_hours": a_metrics[3],
                "avg_body_chars": a_metrics[4],
                "median_body_chars": a_metrics[5],
                "thin_rationale_pct": a_metrics[6],
            },
            "human_task_types": [{"type": r[0], "count": r[1], "pct": r[2]} for r in h_tasks],
            "aidev_full_registry": {
                "repositories_indexed": repo_cnt,
                "users_indexed": user_cnt,
                "agents_covered": agents_covered,
            },
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        h = result["human_baseline_prs"]
        a = result["agent_sample_prs"]
        ratio = (
            round(h["median_merge_hours"] / a["median_merge_hours"], 1)
            if a.get("median_merge_hours", 0) > 0
            else 0.0
        )
        return [
            self.primary_entity,
            f"{h['n']} human / {a['n']} agent",
            f"Merge Time: {h['median_merge_hours']}h human vs {a['median_merge_hours']}h agent ({ratio:.1f}x raw; see Mode I/II split)",
            f"Thin Rationale: {h['thin_rationale_pct']}% human vs {a['thin_rationale_pct']}% agent",
            self.lemon_market_implication,
        ]
