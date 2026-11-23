#!/usr/bin/env python3
import json
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class LivePRCohortHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_12_live_codebase_pr_cohort"

    @property
    def dataset_name(self) -> str:
        return "Live Codebase PR Cohort"

    @property
    def primary_entity(self) -> str:
        return "Real-Time Mined GitHub PRs (API)"

    @property
    def lemon_market_implication(self) -> str:
        return "Confirms rapid review latency collapse directly on active 2026 open-source pull requests"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/live_pr_sample/live_agent_prs_sample.json"]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p01_verify_raw_datasets.py",
            "p05_multicorpus_triangulation.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["pr_acceptance", "review_latency", "agent_breakdown"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        primary_path = self.scratch_path("live_pr_sample", "live_agent_prs_sample.json")
        archive_candidates = [
            self.archive_path("live_pr_sample", "live_agent_prs_sample.json"),
            self.archive_path("live_agent_prs_sample.json"),
            self.archive_path("live_agent_prs_sample_archive.json"),
        ]

        live_pr_file = None
        source_location = "not_found"
        if os.path.exists(primary_path):
            live_pr_file = primary_path
            source_location = "scratch"
        else:
            for cand in archive_candidates:
                if os.path.exists(cand):
                    live_pr_file = cand
                    source_location = "archive"
                    break

        d12_results: Dict[str, Any] = {
            "dataset_name": "Live Codebase Agent PR Cohort (GitHub REST API)",
            "sample_size_n": 0,
            "merged_count": 0,
            "merge_rate_pct": 0.0,
            "median_turnaround_hours": 0.0,
            "median_turnaround_minutes": 0.0,
            "unreviewed_merged_rate_pct": None,
            "agent_breakdown": [],
            "source_location": source_location,
            "status": "not_found",
        }
        if live_pr_file is not None:
            with open(live_pr_file, "r", encoding="utf-8") as f:
                live_raw = json.load(f)
            live_prs = live_raw.get("prs", [])
            agent_counts: Dict[str, Dict[str, int]] = {}
            for p in live_prs:
                ag = p.get("agent_detected", "Unknown")
                if ag not in agent_counts:
                    agent_counts[ag] = {"pr_count": 0, "merged_count": 0}
                agent_counts[ag]["pr_count"] += 1
                if p.get("is_merged"):
                    agent_counts[ag]["merged_count"] += 1
            live_breakdown = [
                {
                    "agent_name": ag,
                    "pr_count": st["pr_count"],
                    "merged_count": st["merged_count"],
                    "merge_rate_pct": round(100.0 * st["merged_count"] / max(1, st["pr_count"]), 2),
                }
                for ag, st in sorted(agent_counts.items(), key=lambda x: x[1]["pr_count"], reverse=True)
            ]
            d12_results = {
                "dataset_name": "Live Codebase Agent PR Cohort (GitHub REST API)",
                "sample_size_n": live_raw.get("total_live_prs_sampled", 0),
                "detail_enriched_prs_count": live_raw.get("detail_enriched_prs_count", 0),
                "merged_count": live_raw.get("merged_count", 0),
                "enriched_merged_count": live_raw.get("enriched_merged_count", 0),
                "merge_rate_pct": live_raw.get("merge_rate_pct", 0.0),
                "median_turnaround_hours": live_raw.get("median_turnaround_hours", 0.0),
                "median_turnaround_minutes": live_raw.get("median_turnaround_minutes", 0.0),
                "unreviewed_merged_rate_pct": live_raw.get("unreviewed_merged_rate_pct"),
                "agent_breakdown": live_breakdown,
                "source_location": source_location,
                "source_path": live_pr_file,
                "status": "verified_on_disk",
            }
        return d12_results

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        unrev = result.get("unreviewed_merged_rate_pct")
        unrev_str = (
            f"{unrev:.1f}% (enriched merged N={result.get('enriched_merged_count', 0)})"
            if unrev is not None
            else "N/A (detail API unenriched)"
        )
        return [
            self.primary_entity,
            f"{result['sample_size_n']} live PRs (enriched={result.get('detail_enriched_prs_count', 0)}; Claude Code, CodeRabbit, Cursor)",
            f"Median Turnaround: {result['median_turnaround_hours']}h ({result['median_turnaround_minutes']}m)",
            f"Merge Rate: {result['merge_rate_pct']}% | Unreviewed Rate: {unrev_str}",
            self.lemon_market_implication,
        ]
