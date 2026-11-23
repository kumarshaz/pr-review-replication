#!/usr/bin/env python3
"""
Dataset 17 Handler: Code Review Bench (Martian, 2026) & Qodo PR-Review-Bench
=============================================================================
Extracts real bot precision, recall, F1, diff-size sensitivity, language gaps,
and expert human accuracy/actionability ratings across 15 prose AI review bots
and 1,135 GHArchive-scraped PRs (plus 136 offline golden issues and 100 Qodo PRs).
"""
import csv
import json
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class CodeReviewBenchHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_17_code_review_bench_and_qodo"

    @property
    def dataset_name(self) -> str:
        return "Code Review Bench & Qodo PR-Review-Bench (15 Review Tools)"

    @property
    def primary_entity(self) -> str:
        return "Paired Multi-Bot PR Review Precision/Recall & Human Quality Audit"

    @property
    def lemon_market_implication(self) -> str:
        return "Across multi-tool prose AI code reviewers, recall and F1 remain bounded while human-audited factual accuracy and actionability diverge sharply across diff-size strata"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/code_review_bench/online_sample.parquet",
            "scratch/code_review_bench/offline_golden_issues.parquet",
            "scratch/code_review_bench/human_annotations_task1.parquet",
            "scratch/code_review_bench/human_annotations_task2.parquet",
            "scratch/qodo_pr_review_bench/git_code_review_bench_100_w_open_prs.jsonl",
            "scratch/qodo_pr_review_bench/rules_for_repo.jsonl",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py", "p12_jev_vs_prose_tollgates.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["code_review_benchmark", "bot_comment_density"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        crb_dir = self.scratch_path("code_review_bench")
        qodo_dir = self.scratch_path("qodo_pr_review_bench")
        f_online = os.path.join(crb_dir, "online_sample.parquet")
        f_offline = os.path.join(crb_dir, "offline_golden_issues.parquet")
        f_t1 = os.path.join(crb_dir, "human_annotations_task1.parquet")
        f_t2 = os.path.join(crb_dir, "human_annotations_task2.parquet")
        f_qodo_prs = os.path.join(qodo_dir, "git_code_review_bench_100_w_open_prs.jsonl")
        f_qodo_rules = os.path.join(qodo_dir, "rules_for_repo.jsonl")

        overall = con.execute(f"""
            SELECT
                COUNT(*) AS n_rows,
                COUNT(DISTINCT pr_url) AS n_prs,
                COUNT(DISTINCT repo) AS n_repos,
                COUNT(DISTINCT tool) AS n_tools,
                ROUND(AVG(precision), 4) AS avg_prec,
                ROUND(AVG(recall), 4) AS avg_rec,
                ROUND(AVG(f1), 4) AS avg_f1,
                ROUND(AVG(diff_lines), 1) AS avg_diff_lines
            FROM read_parquet('{f_online}')
        """).fetchone()

        by_tool = con.execute(f"""
            SELECT
                tool,
                COUNT(*) AS n_prs,
                ROUND(AVG(precision), 4) AS avg_prec,
                ROUND(AVG(recall), 4) AS avg_rec,
                ROUND(AVG(f1), 4) AS avg_f1,
                ROUND(AVG(f0_5), 4) AS avg_f0_5,
                ROUND(AVG(diff_lines), 1) AS avg_diff_lines
            FROM read_parquet('{f_online}')
            GROUP BY tool
            ORDER BY avg_f1 DESC, n_prs DESC
        """).fetchall()

        by_size = con.execute(f"""
            SELECT
                COALESCE(size_bucket, 'unknown') AS size_bucket,
                COUNT(*) AS n_prs,
                ROUND(AVG(precision), 4) AS avg_prec,
                ROUND(AVG(recall), 4) AS avg_rec,
                ROUND(AVG(f1), 4) AS avg_f1,
                ROUND(AVG(diff_lines), 1) AS avg_diff_lines
            FROM read_parquet('{f_online}')
            GROUP BY 1
            ORDER BY avg_diff_lines ASC
        """).fetchall()

        by_lang = con.execute(f"""
            SELECT
                COALESCE(language, 'Unknown') AS language,
                COUNT(*) AS n_prs,
                ROUND(AVG(precision), 4) AS avg_prec,
                ROUND(AVG(recall), 4) AS avg_rec,
                ROUND(AVG(f1), 4) AS avg_f1
            FROM read_parquet('{f_online}')
            GROUP BY 1
            HAVING COUNT(*) >= 10
            ORDER BY n_prs DESC
        """).fetchall()

        offline_cnt = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT pr_url), COUNT(DISTINCT source_repo) FROM read_parquet('{f_offline}')"
        ).fetchone()
        t1_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n,
                ROUND(100.0 * AVG(CASE WHEN judge_matched THEN 1.0 ELSE 0.0 END), 2) AS judge_match_pct,
                ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_match_decision, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2) AS human_match_pct,
                ROUND(100.0 * AVG(CASE WHEN (judge_matched AND LOWER(COALESCE(human_match_decision, '')) = 'yes')
                                            OR (NOT judge_matched AND LOWER(COALESCE(human_match_decision, '')) != 'yes') THEN 1.0 ELSE 0.0 END), 2) AS judge_human_agreement_pct
            FROM read_parquet('{f_t1}')
        """).fetchone()

        t2_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n,
                ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_factual_accuracy, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2) AS factual_yes_pct,
                ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_relevant_to_pr, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2) AS relevant_yes_pct,
                ROUND(100.0 * AVG(CASE WHEN LOWER(COALESCE(human_actionable, '')) = 'yes' THEN 1.0 ELSE 0.0 END), 2) AS actionable_yes_pct,
                ROUND(AVG(human_overall_quality), 3) AS avg_quality_score
            FROM read_parquet('{f_t2}')
        """).fetchone()

        qodo_prs_n = 0
        qodo_issues_total = 0
        if os.path.exists(f_qodo_prs):
            with open(f_qodo_prs, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        qodo_prs_n += 1
                        obj = json.loads(line)
                        qodo_issues_total += int(obj.get("num_of_issues", 0))
        qodo_rules_n = 0
        if os.path.exists(f_qodo_rules):
            with open(f_qodo_rules, "r", encoding="utf-8") as f:
                qodo_rules_n = sum(1 for ln in f if ln.strip())

        csv_path = self.table_path("code_review_bench_15tools_log.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["table_type", "stratum", "n_prs", "avg_precision", "avg_recall", "avg_f1", "avg_f0_5", "avg_diff_lines"])
            for r in by_tool:
                w.writerow(["by_tool", r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
            for r in by_size:
                w.writerow(["by_size_bucket", r[0], r[1], r[2], r[3], r[4], "", r[5]])
            for r in by_lang:
                w.writerow(["by_language", r[0], r[1], r[2], r[3], r[4], "", ""])

        return {
            "dataset_name": "Code Review Bench (Martian) + Qodo PR-Review-Bench",
            "sample_size_n": int(overall[0]),
            "unique_prs": int(overall[1]),
            "unique_repos": int(overall[2]),
            "unique_tools": int(overall[3]),
            "overall_precision": float(overall[4]),
            "overall_recall": float(overall[5]),
            "overall_f1": float(overall[6]),
            "avg_diff_lines": float(overall[7]),
            "offline_golden_issues": {"issues": int(offline_cnt[0]), "prs": int(offline_cnt[1]), "repos": int(offline_cnt[2])},
            "human_annotations_task1": {
                "n": int(t1_stats[0]),
                "judge_match_pct": float(t1_stats[1]),
                "human_match_pct": float(t1_stats[2]),
                "judge_human_agreement_pct": float(t1_stats[3]),
            },
            "human_annotations_task2": {
                "n": int(t2_stats[0]),
                "factual_yes_pct": float(t2_stats[1]),
                "relevant_yes_pct": float(t2_stats[2]),
                "actionable_yes_pct": float(t2_stats[3]),
                "avg_quality_score": float(t2_stats[4]),
            },
            "qodo_pr_review_bench": {"n_prs": qodo_prs_n, "total_issues": qodo_issues_total, "repo_rule_specs": qodo_rules_n},
            "by_tool": [
                {"tool": r[0], "n_prs": int(r[1]), "precision": float(r[2]), "recall": float(r[3]), "f1": float(r[4]), "f0_5": float(r[5]), "avg_diff_lines": float(r[6])}
                for r in by_tool
            ],
            "by_size_bucket": [
                {"size_bucket": r[0], "n_prs": int(r[1]), "precision": float(r[2]), "recall": float(r[3]), "f1": float(r[4]), "avg_diff_lines": float(r[5])}
                for r in by_size
            ],
            "by_language": [
                {"language": r[0], "n_prs": int(r[1]), "precision": float(r[2]), "recall": float(r[3]), "f1": float(r[4])}
                for r in by_lang
            ],
            "status": "verified_on_disk",
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        return [
            self.primary_entity,
            f"{result['sample_size_n']:,} bot PRs ({result['unique_tools']} tools) + {result['qodo_pr_review_bench']['n_prs']} Qodo PRs",
            f"Mean P={result['overall_precision']:.3f}, R={result['overall_recall']:.3f}, F1={result['overall_f1']:.3f}",
            f"Human factual={result['human_annotations_task2']['factual_yes_pct']:.1f}%, actionable={result['human_annotations_task2']['actionable_yes_pct']:.1f}%",
            self.lemon_market_implication,
        ]
