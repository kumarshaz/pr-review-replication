#!/usr/bin/env python3
import os
import sqlite3
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class DevGPTHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_4_devgpt"

    @property
    def dataset_name(self) -> str:
        return "DevGPT"

    @property
    def primary_entity(self) -> str:
        return "Developer-ChatGPT Shared Conversations"

    @property
    def lemon_market_implication(self) -> str:
        return "Externalized prompt rationale reduces Intent Debt and enables verifiable maintainer attestation"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/devgpt/devgpt.sqlite"]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p02_explore_raw_data.py",
            "p05_multicorpus_triangulation.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return [
            "pr_acceptance",
            "review_latency",
            "paired_control",
            "fix_churn",
            "defect_survival",
            "rationale_sharing",
            "conversation_turns",
            "prompt_typologies",
        ]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        devgpt_path = self.scratch_path("devgpt", "devgpt.sqlite")
        scon = sqlite3.connect(devgpt_path)
        try:
            pr_decision_stats = scon.execute("""
                SELECT
                    COUNT(CASE WHEN state IN ('MERGED', 'CLOSED') THEN 1 END) as decided_prs,
                    COUNT(CASE WHEN state = 'MERGED' THEN 1 END) as merged_prs,
                    COUNT(CASE WHEN state = 'CLOSED' THEN 1 END) as closed_prs,
                    COUNT(CASE WHEN state = 'OPEN' THEN 1 END) as open_prs,
                    COUNT(*) as total_prs,
                    ROUND(AVG(commits_total_count), 2) as avg_commits,
                    SUM(commits_total_count) as total_commits
                FROM pull_request
            """).fetchone()
            decided_prs, merged_prs, closed_prs, open_prs, total_prs, avg_commits, total_commits = pr_decision_stats
            devgpt_merge_rate = round(merged_prs * 100.0 / decided_prs, 2) if decided_prs else 0.0

            # Turnaround / Review Latency for decided PRs
            pr_latencies = scon.execute("""
                SELECT
                    (julianday(replace(replace(COALESCE(merged_at, closed_at), "('", ""), "',)", "")) - julianday(created_at)) * 24.0 * 60.0 as turnaround_mins
                FROM pull_request
                WHERE created_at IS NOT NULL AND (merged_at IS NOT NULL OR closed_at IS NOT NULL)
            """).fetchall()
            valid_lat_m = sorted([r[0] for r in pr_latencies if r[0] is not None and r[0] >= 0])
            med_lat_mins = round(valid_lat_m[len(valid_lat_m) // 2], 1) if valid_lat_m else 0.0
            med_lat_hours = round(med_lat_mins / 60.0, 2)

            # Repositories for Paired Control
            shared_prs = scon.execute("""
                SELECT repo_name, COUNT(*) as pr_count, COUNT(CASE WHEN state = 'MERGED' THEN 1 END) as merged_count
                FROM pull_request
                WHERE repo_name IS NOT NULL
                GROUP BY repo_name
            """).fetchall()
            shared_repo_prs = [
                {"repo_name": r[0], "total_prs": r[1], "merged_prs": r[2]}
                for r in shared_prs
            ]

            issue_stats = scon.execute("""
                SELECT
                    COUNT(*) as total_issues,
                    COUNT(CASE WHEN closed_at IS NOT NULL AND closed_at != 'None' AND closed_at != '(nan,)' THEN 1 END) as closed_issues,
                    ROUND(AVG(julianday(replace(replace(closed_at, "('", ""), "',)", "")) - julianday(created_at)), 2) as avg_resolution_days
                FROM issue
            """).fetchone()
            closed_issue_days = scon.execute("""
                SELECT
                    julianday(replace(replace(closed_at, "('", ""), "',)", "")) - julianday(created_at)
                FROM issue
                WHERE closed_at IS NOT NULL AND closed_at != 'None' AND closed_at != '(nan,)'
            """).fetchall()
            c_days = sorted([r[0] for r in closed_issue_days if r[0] is not None and r[0] >= 0])
            med_resolution_days = round(c_days[len(c_days) // 2], 2) if c_days else 0.0

            d4_sharing_types = scon.execute("SELECT type, COUNT(*) FROM sharing GROUP BY type ORDER BY COUNT(*) DESC").fetchall()
            d4_pr_states = scon.execute("""
                SELECT p.state, COUNT(DISTINCT p.id) as pr_count,
                       ROUND(AVG(p.commits_total_count), 2) as avg_commits,
                       ROUND(AVG(p.additions), 1) as avg_additions,
                       ROUND(AVG(p.deletions), 1) as avg_deletions,
                       ROUND(AVG(s.numberofprompts), 2) as avg_prompts
                FROM pull_request p
                JOIN sharing s ON p.id = s.pull_request_id
                GROUP BY p.state
                ORDER BY pr_count DESC
            """).fetchall()

            d4_conv_stats_raw = scon.execute("""
                SELECT
                    COUNT(*) as total_conversation_turns,
                    ROUND(AVG(LENGTH(Prompt)), 1) as avg_prompt_len,
                    ROUND(AVG(LENGTH(Answer)), 1) as avg_answer_len,
                    ROUND(100.0 * SUM(CASE WHEN ListOfCode IS NOT NULL AND LENGTH(ListOfCode) > 10 THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_turns_with_code
                FROM conversation
            """).fetchone()

            all_lens = scon.execute("SELECT LENGTH(Prompt), LENGTH(Answer) FROM conversation").fetchall()
            p_lens = sorted([r[0] for r in all_lens if r[0] is not None])
            a_lens = sorted([r[1] for r in all_lens if r[1] is not None])
            med_p = round(p_lens[len(p_lens) // 2], 1) if p_lens else 0
            med_a = round(a_lens[len(a_lens) // 2], 1) if a_lens else 0
        finally:
            scon.close()

        return {
            "dataset_name": "DevGPT Developer-ChatGPT Conversations (SQLite)",
            "sample_size_n": decided_prs,
            "merged_count": merged_prs,
            "closed_count": closed_prs,
            "open_count": open_prs,
            "total_prs": total_prs,
            "merge_rate_pct": devgpt_merge_rate,
            "median_turnaround_minutes": med_lat_mins,
            "median_turnaround_hours": med_lat_hours,
            "review_latency": {
                "sample_size_n": len(valid_lat_m),
                "median_turnaround_minutes": med_lat_mins,
                "median_turnaround_hours": med_lat_hours,
            },
            "shared_repo_prs": shared_repo_prs,
            "fix_churn": {
                "pr_count": total_prs,
                "avg_commits_per_pr": avg_commits,
                "total_commits": total_commits,
            },
            "defect_survival": {
                "total_issues": issue_stats[0],
                "closed_issues": issue_stats[1],
                "avg_resolution_days": issue_stats[2],
                "median_resolution_days": med_resolution_days,
            },
            "sharing_links_by_entity": [{"entity": r[0], "count": r[1]} for r in d4_sharing_types],
            "pr_externalization_cohorts": [
                {
                    "state": r[0],
                    "pr_count": r[1],
                    "avg_commits": r[2],
                    "avg_additions": r[3],
                    "avg_deletions": r[4],
                    "avg_prompts_per_session": r[5],
                }
                for r in d4_pr_states
            ],
            "conversation_turn_metrics": {
                "total_turns": d4_conv_stats_raw[0],
                "avg_prompt_chars": d4_conv_stats_raw[1],
                "median_prompt_chars": med_p,
                "avg_answer_chars": d4_conv_stats_raw[2],
                "median_answer_chars": med_a,
                "pct_turns_with_code_generation": d4_conv_stats_raw[3],
            },
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        tot_turns = result["conversation_turn_metrics"]["total_turns"]
        pr_links = 0
        for e in result["sharing_links_by_entity"]:
            if e["entity"] == "pr":
                pr_links = e["count"]
        cohorts = {c["state"]: c for c in result.get("pr_externalization_cohorts", [])}
        merged_c = cohorts.get("MERGED", {})
        closed_c = cohorts.get("CLOSED", {})
        return [
            self.primary_entity,
            f"{tot_turns:,} turns across {pr_links:,} PRs",
            f"Merged PRs: avg {merged_c.get('avg_prompts_per_session', 0)} prompts, {merged_c.get('avg_additions', 0):,.1f} additions",
            f"Closed/Failed PRs: {closed_c.get('avg_additions', 0):,.1f} additions (unintegrated churn)",
            self.lemon_market_implication,
        ]
