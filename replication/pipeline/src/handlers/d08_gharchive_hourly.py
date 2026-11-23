#!/usr/bin/env python3
import collections
from datetime import datetime
import gzip
import json
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class GHArchiveHourlyHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_8_gharchive_telemetry"

    @property
    def dataset_name(self) -> str:
        return "GHArchive Event Stream"

    @property
    def primary_entity(self) -> str:
        return "Hourly Longitudinal GitHub Telemetry"

    @property
    def lemon_market_implication(self) -> str:
        return "Live open-source GitHub telemetry separates bot-only vs. human review verdict distributions across a 1-hour global firehose"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/gharchive/gharchive_2025-07-15-15.json.gz"]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["macro_event_stream", "bot_review_ratio", "pr_acceptance", "review_latency", "review_events_volume"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        gha_path = self.scratch_path("gharchive", "gharchive_2025-07-15-15.json.gz")

        counts = collections.Counter()
        bot_events = collections.Counter()
        review_actions = collections.Counter()
        bot_review_actions = collections.Counter()
        human_review_actions = collections.Counter()
        review_lengths: List[int] = []
        turnaround_mins: List[float] = []
        opened_prs_count = 0
        merged_prs_count = 0
        closed_prs_count = 0

        if os.path.exists(gha_path):
            with gzip.open(gha_path, "rt", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                        t = ev.get("type")
                        counts[t] += 1
                        actor = ev.get("actor", {}).get("login", "")
                        is_bot = "[bot]" in actor.lower() or actor.endswith("-bot") or actor.endswith("bot")
                        if is_bot:
                            bot_events[t] += 1
                        if t == "PullRequestEvent":
                            payload = ev.get("payload", {})
                            act = payload.get("action", "")
                            pr_data = payload.get("pull_request", {})
                            if act == "opened":
                                opened_prs_count += 1
                            elif act == "closed":
                                if pr_data.get("merged") is True:
                                    merged_prs_count += 1
                                else:
                                    closed_prs_count += 1
                                c_str = pr_data.get("created_at")
                                cl_str = pr_data.get("closed_at")
                                if c_str and cl_str:
                                    t0 = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
                                    t1 = datetime.fromisoformat(cl_str.replace("Z", "+00:00"))
                                    diff_m = (t1 - t0).total_seconds() / 60.0
                                    if diff_m >= 0:
                                        turnaround_mins.append(diff_m)
                        elif t == "PullRequestReviewEvent":
                            payload = ev.get("payload", {})
                            review = payload.get("review", {})
                            state = (review.get("state") or "unknown").lower()
                            review_actions[state] += 1
                            if is_bot:
                                bot_review_actions[state] += 1
                            else:
                                human_review_actions[state] += 1
                            body = review.get("body") or ""
                            if len(body) > 0:
                                review_lengths.append(len(body))
                    except Exception:
                        pass

        total_events = sum(counts.values())
        decided_prs_count = merged_prs_count + closed_prs_count
        gha_merge_rate = round(merged_prs_count * 100.0 / decided_prs_count, 2) if decided_prs_count else 0.0
        turnaround_mins.sort()
        med_turnaround_m = round(turnaround_mins[len(turnaround_mins) // 2], 1) if turnaround_mins else 0.0
        med_turnaround_h = round(med_turnaround_m / 60.0, 3)

        total_pr_events = counts.get("PullRequestEvent", 0)
        bot_pr_events = bot_events.get("PullRequestEvent", 0)
        total_review_events = counts.get("PullRequestReviewEvent", 0)
        bot_review_events = bot_events.get("PullRequestReviewEvent", 0)
        total_review_comments = counts.get("PullRequestReviewCommentEvent", 0)
        bot_review_comments = bot_events.get("PullRequestReviewCommentEvent", 0)

        bot_app = bot_review_actions.get("approved", 0)
        bot_cr = bot_review_actions.get("changes_requested", 0)
        bot_clearance_pct = round(100.0 * bot_app / (bot_app + bot_cr), 2) if (bot_app + bot_cr) > 0 else 0.0
        bot_skew = round(bot_app / bot_cr, 2) if bot_cr > 0 else float(bot_app)

        return {
            "sample_archive_window": "2025-07-15T15:00:00Z to 2025-07-15T16:00:00Z (1 hour)",
            "is_all_github_firehose_human_plus_bot": True,
            "total_events_in_hour": total_events,
            "opened_prs_in_hour": opened_prs_count,
            "sample_size_n": decided_prs_count,
            "merged_count": merged_prs_count,
            "closed_count": closed_prs_count,
            "merge_rate_pct": gha_merge_rate,
            "median_turnaround_minutes": med_turnaround_m,
            "median_turnaround_hours": med_turnaround_h,
            "review_latency": {
                "sample_size_n": len(turnaround_mins),
                "median_turnaround_minutes": med_turnaround_m,
                "median_turnaround_hours": med_turnaround_h,
            },
            "pull_request_events": {
                "total": total_pr_events,
                "bot_authored": bot_pr_events,
                "bot_share_pct": round(100.0 * bot_pr_events / max(1, total_pr_events), 2),
            },
            "pull_request_review_events": {
                "total": total_review_events,
                "bot_reviewed": bot_review_events,
                "bot_share_pct": round(100.0 * bot_review_events / max(1, total_review_events), 2),
            },
            "pull_request_review_comments": {
                "total": total_review_comments,
                "bot_authored": bot_review_comments,
                "bot_share_pct": round(100.0 * bot_review_comments / max(1, total_review_comments), 2),
            },
            "review_state_distribution": dict(review_actions),
            "bot_only_review_state_distribution": dict(bot_review_actions),
            "human_only_review_state_distribution": dict(human_review_actions),
            "approval_to_rejection_ratio": round(
                review_actions.get("approved", 0) / max(1, review_actions.get("changes_requested", 1)), 2
            ),
            "bot_only_approval_to_rejection_ratio": bot_skew,
            "bot_only_clearance_pct": bot_clearance_pct,
            "mean_review_body_chars": round(sum(review_lengths) / max(1, len(review_lengths)), 1) if review_lengths else 0,
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        pr_bot = result["pull_request_events"]["bot_share_pct"]
        rev_bot = result["pull_request_review_events"]["bot_share_pct"]
        ratio = result["approval_to_rejection_ratio"]
        b_ratio = result.get("bot_only_approval_to_rejection_ratio", 0.0)
        b_dist = result.get("bot_only_review_state_distribution", {})
        return [
            self.primary_entity,
            f"{result['total_events_in_hour']:,} total events (1 hour window)",
            f"Bot PRs: {pr_bot}% | Bot Reviews: {rev_bot}%",
            f"Bot-Only Approve:Reject={b_ratio}:1 ({b_dist.get('approved', 0)} vs {b_dist.get('changes_requested', 0)}, {b_dist.get('commented', 0)} commented) | All-GitHub={ratio}:1",
            self.lemon_market_implication,
        ]
