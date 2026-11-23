#!/usr/bin/env python3
"""
Dataset 14 Handler: GitHub-Agentic-PR-Dataset (Abujadallah et al. / arXiv:2601.15195 & 2606.13468)
Contains 334,039 real-world AI coding agent pull requests and 49,042 polyglot test quality evaluations.
Mines merged vs. rejected blast-radius cliffs, test-adaptedness gaps, symbol-coupling bounds,
and silent zero-review test merges.
"""
import csv
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class AgenticPRsHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_14_agentic_prs_mabujadallah"

    @property
    def dataset_name(self) -> str:
        return "GitHub-Agentic-PR-Dataset"

    @property
    def primary_entity(self) -> str:
        return "Autonomous Agent PRs & Test Quality Across 15 Languages"

    @property
    def lemon_market_implication(self) -> str:
        return "Exposes a steep file-spread rejection cliff between merged and rejected agentic PRs alongside test-adaptedness deficits in dynamic languages and security-sensitive domains"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/agentic_prs/pr_review_comments.parquet",
            "scratch/agentic_prs/pr_test_quality.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return [
            "pr_acceptance",
            "fix_churn",
            "review_events_volume",
            "cross_module_ast_churn",
            "supervisory_collapse",
            "bot_comment_density",
            "containerized_pass_rate",
        ]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        f_reviews = self.scratch_path("agentic_prs", "pr_review_comments.parquet")
        f_tests = self.scratch_path("agentic_prs", "pr_test_quality.parquet")

        d14_results: Dict[str, Any] = {
            "dataset_name": "GitHub-Agentic-PR-Dataset (Abujadallah et al. / Hugging Face)",
            "sample_size_n": 0,
            "merged_count": 0,
            "merge_rate_pct": 0.0,
            "avg_additions": 0.0,
            "avg_deletions": 0.0,
            "avg_changed_files": 0.0,
            "avg_comments_per_pr": 0.0,
            "unreviewed_merge_count": 0,
            "unreviewed_merge_pct": 0.0,
            "test_quality_evaluated_prs": 0,
            "test_quality_languages_count": 0,
            "status": "not_found",
        }

        if not os.path.exists(f_reviews):
            return d14_results

        res = con.execute(f"""
            SELECT
                count(*),
                count(CASE WHEN merged THEN 1 END),
                round(count(CASE WHEN merged THEN 1 END) * 100.0 / count(*), 2),
                round(avg(additions), 1),
                round(avg(deletions), 1),
                round(avg(changed_files), 2),
                round(avg(n_comments_total), 2),
                count(CASE WHEN n_reviews = 0 AND merged THEN 1 END),
                round(count(CASE WHEN n_reviews = 0 AND merged THEN 1 END) * 100.0 / nullif(count(CASE WHEN merged THEN 1 END), 0), 2)
            FROM read_parquet('{f_reviews}')
        """).fetchone()

        # Merged vs Rejected blast-radius cliff across all PRs
        blast_rows = con.execute(f"""
            SELECT
                merged,
                count(*) AS n,
                round(avg(n_reviews), 2) AS avg_reviews,
                round(avg(n_review_threads), 2) AS avg_threads,
                round(avg(n_issue_comments), 2) AS avg_issue_comm,
                round(avg(n_participants), 2) AS avg_participants,
                round(avg(additions), 1) AS avg_additions,
                round(avg(deletions), 1) AS avg_deletions,
                round(avg(changed_files), 2) AS avg_changed_files,
                count(CASE WHEN n_reviews = 0 THEN 1 END) AS zero_review_n,
                round(100.0 * avg(CASE WHEN n_reviews = 0 THEN 1.0 ELSE 0.0 END), 2) AS zero_review_pct
            FROM read_parquet('{f_reviews}')
            GROUP BY merged
            ORDER BY merged DESC
        """).fetchall()

        file_buckets = con.execute(f"""
            SELECT
                CASE
                    WHEN changed_files <= 1 THEN '1_file'
                    WHEN changed_files <= 5 THEN '2-5_files'
                    WHEN changed_files <= 20 THEN '6-20_files'
                    ELSE '21+_files'
                END AS file_bucket,
                count(*) AS n,
                round(avg(CASE WHEN merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
                round(avg(CASE WHEN n_reviews = 0 AND merged THEN 100.0 ELSE 0.0 END), 2) AS silent_merge_of_all_pct,
                round(avg(n_reviews), 2) AS avg_reviews,
                round(avg(n_participants), 2) AS avg_participants,
                round(avg(n_comments_total), 2) AS avg_comments
            FROM read_parquet('{f_reviews}')
            GROUP BY 1
            ORDER BY MIN(changed_files) ASC
        """).fetchall()

        test_count = 0
        lang_count = 0
        tq_overall = []
        tq_by_lang = []
        tq_by_btype = []
        tq_zero_rev_join = []
        tq_symbol_coupling = []

        if os.path.exists(f_tests):
            t_res = con.execute(
                f"SELECT count(*), count(distinct language) FROM read_parquet('{f_tests}')"
            ).fetchone()
            test_count = t_res[0]
            lang_count = t_res[1]

            tq_overall = con.execute(f"""
                SELECT
                    is_agent,
                    count(*) AS n,
                    round(avg(CASE WHEN merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
                    round(avg(CASE WHEN trivial THEN 100.0 ELSE 0.0 END), 2) AS trivial_pct,
                    round(avg(CASE WHEN relevant THEN 100.0 ELSE 0.0 END), 2) AS relevant_pct,
                    round(avg(CASE WHEN specific THEN 100.0 ELSE 0.0 END), 2) AS specific_pct,
                    round(avg(CASE WHEN adapted THEN 100.0 ELSE 0.0 END), 2) AS adapted_pct,
                    round(avg(assertion_count), 2) AS avg_assert,
                    round(avg(test_lines_added), 1) AS avg_test_lines,
                    round(avg(n_shared_symbols), 2) AS avg_shared_sym,
                    round(avg(n_new_symbols_used), 2) AS avg_new_sym
                FROM read_parquet('{f_tests}')
                GROUP BY is_agent
                ORDER BY is_agent DESC
            """).fetchall()

            tq_by_lang = con.execute(f"""
                SELECT
                    language, is_agent, count(*) AS n,
                    round(avg(CASE WHEN merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
                    round(avg(CASE WHEN trivial THEN 100.0 ELSE 0.0 END), 2) AS trivial_pct,
                    round(avg(CASE WHEN adapted THEN 100.0 ELSE 0.0 END), 2) AS adapted_pct,
                    round(avg(assertion_count), 1) AS avg_assert
                FROM read_parquet('{f_tests}')
                GROUP BY 1, 2
                HAVING count(*) >= 200
                ORDER BY language ASC, is_agent DESC
            """).fetchall()

            tq_by_btype = con.execute(f"""
                SELECT
                    btype, is_agent, count(*) AS n,
                    round(avg(CASE WHEN merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
                    round(avg(CASE WHEN trivial THEN 100.0 ELSE 0.0 END), 2) AS trivial_pct,
                    round(avg(CASE WHEN adapted THEN 100.0 ELSE 0.0 END), 2) AS adapted_pct
                FROM read_parquet('{f_tests}')
                GROUP BY 1, 2
                ORDER BY n DESC
            """).fetchall()

            tq_zero_rev_join = con.execute(f"""
                SELECT
                    t.is_agent,
                    (r.n_reviews = 0) AS zero_reviews,
                    count(*) AS n,
                    count(CASE WHEN t.merged THEN 1 END) AS merged_n,
                    round(avg(CASE WHEN t.merged THEN 100.0 ELSE 0.0 END), 2) AS merge_pct,
                    round(avg(CASE WHEN t.trivial THEN 100.0 ELSE 0.0 END), 2) AS trivial_pct,
                    round(avg(CASE WHEN t.adapted THEN 100.0 ELSE 0.0 END), 2) AS adapted_pct,
                    round(avg(r.additions + r.deletions), 1) AS avg_churn,
                    round(avg(r.changed_files), 2) AS avg_files
                FROM read_parquet('{f_tests}') t
                JOIN read_parquet('{f_reviews}') r
                  ON t.repo_name = r.repo_name AND t.number = r.number
                GROUP BY 1, 2
                ORDER BY 1 DESC, 2 ASC
            """).fetchall()

            tq_symbol_coupling = con.execute(f"""
                SELECT
                    is_agent, merged, count(*) AS n,
                    round(avg(n_shared_symbols), 2) AS avg_shared_sym,
                    round(avg(n_new_symbols_used), 2) AS avg_new_sym,
                    round(avg(test_lines_added), 1) AS avg_test_lines,
                    round(avg(assertion_count), 2) AS avg_assert,
                    round(avg(CASE WHEN adapted THEN 100.0 ELSE 0.0 END), 2) AS adapted_pct,
                    round(avg(CASE WHEN trivial THEN 100.0 ELSE 0.0 END), 2) AS trivial_pct
                FROM read_parquet('{f_tests}')
                GROUP BY 1, 2
                ORDER BY 1 DESC, 2 DESC
            """).fetchall()

        csv_path = self.table_path("agentic_prs_test_quality_and_blast_radius_log.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["section", "cohort_key", "sub_key", "n", "merge_pct", "adapted_pct", "trivial_pct", "avg_changed_files_or_shared_sym", "notes"])
            for r in blast_rows:
                w.writerow(["blast_radius_cliff", "merged" if r[0] else "rejected", "all_prs", r[1], "100.0" if r[0] else "0.0", "N/A", "N/A", r[8], f"add={r[6]}, del={r[7]}, zero_rev_n={r[9]} ({r[10]}%)"])
            for r in file_buckets:
                w.writerow(["file_spread_buckets", r[0], "all_prs", r[1], r[2], "N/A", "N/A", r[0], f"silent_merge_of_all={r[3]}%, avg_reviews={r[4]}"])
            for r in tq_overall:
                w.writerow(["test_quality_overall", "agent" if r[0] else "human", "all", r[1], r[2], r[6], r[3], r[9], f"relevant={r[4]}%, specific={r[5]}%, new_sym={r[10]}"])
            for r in tq_by_lang:
                w.writerow(["test_quality_language", r[0], "agent" if r[1] else "human", r[2], r[3], r[5], r[4], "N/A", f"avg_assert={r[6]}"])
            for r in tq_zero_rev_join:
                w.writerow(["test_quality_zero_rev", "agent" if r[0] else "human", "zero_rev" if r[1] else "reviewed", r[2], r[4], r[6], r[5], r[8], f"merged_n={r[3]}, avg_churn={r[7]}"])
            for r in tq_symbol_coupling:
                w.writerow(["test_quality_coupling", "agent" if r[0] else "human", "merged" if r[1] else "rejected", r[2], "N/A", r[7], r[8], r[3], f"new_sym={r[4]}, test_lines={r[5]}"])

        d14_results = {
            "dataset_name": "GitHub-Agentic-PR-Dataset (Abujadallah et al. / Hugging Face)",
            "sample_size_n": res[0],
            "merged_count": res[1],
            "merge_rate_pct": res[2],
            "avg_additions": res[3],
            "avg_deletions": res[4],
            "avg_changed_files": res[5],
            "avg_comments_per_pr": res[6],
            "unreviewed_merge_count": res[7],
            "unreviewed_merge_pct": res[8],
            "test_quality_evaluated_prs": test_count,
            "test_quality_languages_count": lang_count,
            "merged_vs_rejected_blast_radius": [
                {
                    "merged": bool(r[0]), "n": r[1], "avg_reviews": r[2],
                    "avg_threads": r[3], "avg_issue_comments": r[4], "avg_participants": r[5],
                    "avg_additions": r[6], "avg_deletions": r[7], "avg_changed_files": r[8],
                    "zero_review_n": r[9], "zero_review_pct": r[10],
                }
                for r in blast_rows
            ],
            "file_spread_buckets": [
                {
                    "file_bucket": r[0], "n": r[1], "merge_pct": r[2],
                    "silent_merge_of_all_pct": r[3], "avg_reviews": r[4],
                    "avg_participants": r[5], "avg_comments": r[6],
                }
                for r in file_buckets
            ],
            "test_quality_agent_vs_human": [
                {
                    "is_agent": bool(r[0]), "n": r[1], "merge_pct": r[2],
                    "trivial_pct": r[3], "relevant_pct": r[4], "specific_pct": r[5],
                    "adapted_pct": r[6], "avg_assert": r[7], "avg_test_lines": r[8],
                    "avg_shared_sym": r[9], "avg_new_sym": r[10],
                }
                for r in tq_overall
            ],
            "test_quality_by_language_agent": [
                {
                    "language": r[0], "is_agent": bool(r[1]), "n": r[2],
                    "merge_pct": r[3], "trivial_pct": r[4], "adapted_pct": r[5], "avg_assert": r[6],
                }
                for r in tq_by_lang
            ],
            "test_quality_by_btype_agent": [
                {
                    "btype": r[0], "is_agent": bool(r[1]), "n": r[2],
                    "merge_pct": r[3], "trivial_pct": r[4], "adapted_pct": r[5],
                }
                for r in tq_by_btype
            ],
            "test_quality_zero_review_join": [
                {
                    "is_agent": bool(r[0]), "zero_reviews": bool(r[1]), "n": r[2],
                    "merged_n": r[3], "merge_pct": r[4], "trivial_pct": r[5],
                    "adapted_pct": r[6], "avg_churn": r[7], "avg_files": r[8],
                }
                for r in tq_zero_rev_join
            ],
            "test_quality_symbol_coupling": [
                {
                    "is_agent": bool(r[0]), "merged": bool(r[1]), "n": r[2],
                    "avg_shared_sym": r[3], "avg_new_sym": r[4], "avg_test_lines": r[5],
                    "avg_assert": r[6], "adapted_pct": r[7], "trivial_pct": r[8],
                }
                for r in tq_symbol_coupling
            ],
            "status": "verified_on_disk",
        }
        return d14_results

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        n = result.get("sample_size_n", 0)
        rate = result.get("merge_rate_pct", 0.0)
        blast = result.get("merged_vs_rejected_blast_radius", [])
        m_files = next((b["avg_changed_files"] for b in blast if b["merged"]), 0.0)
        r_files = next((b["avg_changed_files"] for b in blast if not b["merged"]), 0.0)
        return [
            self.primary_entity,
            f"{n:,} PRs across {result.get('test_quality_languages_count', 0)} languages ({result.get('test_quality_evaluated_prs', 0):,} test evals)",
            f"Merge Rate: {rate:.2f}% | Files: {m_files:.2f} merged vs {r_files:.2f} rejected",
            f"Avg Churn: +{result.get('avg_additions', 0):.0f}/-{result.get('avg_deletions', 0):.0f} lines",
            self.lemon_market_implication,
        ]
