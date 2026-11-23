#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class CodeReviewerHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_6_pre_llm_reviews"

    @property
    def dataset_name(self) -> str:
        return "CodeReviewer & Pre-LLM Baseline"

    @property
    def primary_entity(self) -> str:
        return "Human Code Review Corpora (2020-2022)"

    @property
    def lemon_market_implication(self) -> str:
        return "Pre-LLM human code review actively vetted defects; modern LLM review bots skew heavily toward rubber-stamp approvals"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/codereviewer/codereviewer_gen.parquet",
            "scratch/codereviewer/codereviewer_qual0.parquet",
            "scratch/codereviewer/github_codereview_test.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p02_explore_raw_data.py",
            "p05_multicorpus_triangulation.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["pre_llm_review_scrutiny", "comment_generation", "sentiment_dynamics", "bot_comment_density"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_cr = self.scratch_path("codereviewer")
        cr_gen_path = os.path.join(scratch_cr, "codereviewer_gen.parquet")
        cr_qual_path = os.path.join(scratch_cr, "codereviewer_qual0.parquet")
        gh_cr_path = os.path.join(scratch_cr, "github_codereview_test.parquet")

        cr_gen_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n_samples,
                COUNT(DISTINCT proj) AS n_projects,
                ROUND(AVG(LENGTH(msg)), 1) AS avg_comment_chars,
                ROUND(MEDIAN(LENGTH(msg)), 1) AS median_comment_chars,
                ROUND(AVG(LENGTH(patch)), 1) AS avg_patch_chars
            FROM read_parquet('{cr_gen_path}')
        """).fetchone()

        cr_qual_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n_samples,
                SUM(CASE WHEN y = 1 THEN 1 ELSE 0 END) AS needs_review_positive,
                ROUND(100.0 * SUM(CASE WHEN y = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS needs_review_pct
            FROM read_parquet('{cr_qual_path}')
        """).fetchone()

        gh_cr_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n_samples,
                COUNT(DISTINCT repo_name) AS n_repos,
                ROUND(AVG(comment_length), 1) AS avg_comment_chars,
                ROUND(MEDIAN(comment_length), 1) AS median_comment_chars,
                ROUND(AVG(quality_score), 3) AS avg_quality_score,
                ROUND(100.0 * SUM(CASE WHEN is_negative = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS critical_critique_pct
            FROM read_parquet('{gh_cr_path}')
        """).fetchone()

        return {
            "pre_llm_comment_gen": {
                "n_samples": cr_gen_stats[0],
                "n_projects": cr_gen_stats[1],
                "avg_comment_chars": cr_gen_stats[2],
                "median_comment_chars": cr_gen_stats[3],
                "avg_patch_chars": cr_gen_stats[4],
            },
            "pre_llm_quality_estimation": {
                "n_samples": cr_qual_stats[0],
                "needs_review_count": cr_qual_stats[1],
                "needs_review_pct": cr_qual_stats[2],
            },
            "pre_llm_github_reviews": {
                "n_samples": gh_cr_stats[0],
                "n_repos": gh_cr_stats[1],
                "avg_comment_chars": gh_cr_stats[2],
                "median_comment_chars": gh_cr_stats[3],
                "avg_quality_score": gh_cr_stats[4],
                "critical_critique_pct": gh_cr_stats[5],
            },
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        gh = result["pre_llm_github_reviews"]
        gen = result["pre_llm_comment_gen"]
        return [
            self.primary_entity,
            f"{gh['n_samples']} reviews / {gen['n_samples']} diffs",
            f"Human Comment Length: {gh['avg_comment_chars']} chars (concise, actionable)",
            f"Critical Feedback Rate: {gh['critical_critique_pct']}% (rigorous change requests)",
            self.lemon_market_implication,
        ]
