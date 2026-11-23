#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class GHArchive3DayHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_11_gharchive_3day_stream"

    @property
    def dataset_name(self) -> str:
        return "GHArchive 3-Day Stream"

    @property
    def primary_entity(self) -> str:
        return "Multi-Day GitHub Macro Firehose"

    @property
    def lemon_market_implication(self) -> str:
        return "Demonstrates temporal stability of agent activity and review volume over multi-day windows"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/gharchive_3days"]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["multi_day_macro_stream", "review_events_volume", "pr_acceptance"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_gha3 = self.scratch_path("gharchive_3days")

        d11_results: Dict[str, Any] = {
            "dataset_name": "GHArchive 3-Day Longitudinal Stream (Nov 1-3, 2026)",
            "is_all_github_firehose_human_plus_bot": True,
            "total_events_3days": 0,
            "pull_request_events": 0,
            "review_events": 0,
            "inline_comment_events": 0,
            "sample_size_n": 0,
            "merged_count": 0,
            "closed_count": 0,
            "merge_rate_pct": 0.0,
            "status": "not_found",
        }
        if os.path.exists(scratch_gha3) and [f for f in os.listdir(scratch_gha3) if f.endswith(".json.gz")]:
            gha3_stats = con.execute(f"""
                SELECT
                    count(*),
                    count(CASE WHEN type = 'PullRequestEvent' THEN 1 END),
                    count(CASE WHEN type = 'PullRequestReviewEvent' THEN 1 END),
                    count(CASE WHEN type = 'PullRequestReviewCommentEvent' THEN 1 END),
                    count(CASE WHEN type = 'PullRequestEvent' AND json_extract_string(payload, '$.action') = 'merged' THEN 1 END),
                    count(CASE WHEN type = 'PullRequestEvent' AND json_extract_string(payload, '$.action') = 'closed' THEN 1 END)
                FROM read_ndjson('{scratch_gha3}/*.json.gz', columns={{'type': 'VARCHAR', 'payload': 'VARCHAR'}})
            """).fetchone()
            decided_pr_events = gha3_stats[4] + gha3_stats[5]
            gha_merge_rate = round(gha3_stats[4] * 100.0 / decided_pr_events, 2) if decided_pr_events else 0.0
            d11_results = {
                "dataset_name": "GHArchive 3-Day Longitudinal Stream (Nov 1-3, 2026)",
                "is_all_github_firehose_human_plus_bot": True,
                "total_events_3days": gha3_stats[0],
                "pull_request_events": gha3_stats[1],
                "review_events": gha3_stats[2],
                "inline_comment_events": gha3_stats[3],
                "sample_size_n": decided_pr_events,
                "merged_count": gha3_stats[4],
                "closed_count": gha3_stats[5],
                "merge_rate_pct": gha_merge_rate,
                "status": "verified_on_disk",
            }
        return d11_results

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        return [
            self.primary_entity,
            f"{result['total_events_3days']:,} events across Nov 1-3, 2026",
            f"PR Decisions: {result.get('sample_size_n', 0):,} ({result.get('merge_rate_pct', 0.0)}% merged)",
            f"Review Events: {result['review_events']:,} | Inline: {result['inline_comment_events']:,}",
            self.lemon_market_implication,
        ]
