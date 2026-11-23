#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class SWEBenchHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_7_swebench_and_polybench"

    @property
    def dataset_name(self) -> str:
        return "SWE-bench Verified & SWE-PolyBench"

    @property
    def primary_entity(self) -> str:
        return "Multi-Language Benchmark Patches"

    @property
    def lemon_market_implication(self) -> str:
        return "Validates that CIA AST invariant verification generalizes across multi-language enterprise architectures"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/swebench/swebench_verified.parquet",
            "scratch/swebench/swe_polybench.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p02_explore_raw_data.py",
            "p05_multicorpus_triangulation.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["containerized_pass_rate", "ast_node_retrieval", "cross_module_ast_churn"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_swe = self.scratch_path("swebench")
        swev_path = os.path.join(scratch_swe, "swebench_verified.parquet")
        swepb_path = os.path.join(scratch_swe, "swe_polybench.parquet")

        swev_stats = con.execute(f"""
            SELECT
                COUNT(*) AS n_tasks,
                ROUND(AVG(LENGTH(patch)), 1) AS avg_solution_patch_chars,
                ROUND(AVG(LENGTH(test_patch)), 1) AS avg_test_patch_chars,
                ROUND(AVG(LENGTH(patch) * 1.0 / NULLIF(LENGTH(test_patch), 0)), 2) AS avg_code_to_test_ratio
            FROM read_parquet('{swev_path}')
        """).fetchone()

        swepb_overall = con.execute(f"""
            SELECT
                COUNT(*) AS n_tasks,
                ROUND(100.0 * COUNT(CASE WHEN is_mixed THEN 1 END) / NULLIF(COUNT(*), 0), 2) AS cross_cutting_ast_pct
            FROM read_parquet('{swepb_path}')
        """).fetchone()
        total_poly = int(swepb_overall[0] or 0)
        cross_pct = float(swepb_overall[1] or 0.0)

        swepb_by_lang = con.execute(f"""
            SELECT
                language,
                COUNT(*) AS n_tasks,
                ROUND(AVG(num_func_changes), 2) AS avg_funcs_changed,
                ROUND(AVG(num_class_changes), 2) AS avg_classes_changed,
                ROUND(AVG(LENGTH(patch)), 1) AS avg_patch_chars,
                ROUND(AVG(LENGTH(test_patch)), 1) AS avg_test_patch_chars
            FROM read_parquet('{swepb_path}')
            GROUP BY language
            ORDER BY n_tasks DESC
        """).fetchall()

        return {
            "swebench_verified_python": {
                "n_tasks": swev_stats[0],
                "avg_solution_patch_chars": swev_stats[1],
                "avg_test_patch_chars": swev_stats[2],
                "avg_code_to_test_ratio": swev_stats[3],
            },
            "swe_polybench": {
                "n_tasks": int(total_poly),
                "cross_cutting_ast_pct": round(cross_pct, 2),
            },
            "swe_polybench_multilang": [
                {
                    "language": r[0],
                    "n_tasks": r[1],
                    "avg_funcs_changed": r[2],
                    "avg_classes_changed": r[3],
                    "avg_patch_chars": r[4],
                    "avg_test_patch_chars": r[5],
                }
                for r in swepb_by_lang
            ],
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        py_tasks = result["swebench_verified_python"]["n_tasks"]
        ml_rows = result["swe_polybench_multilang"]
        ml_tasks = sum(r["n_tasks"] for r in ml_rows)
        py_patch = result["swebench_verified_python"]["avg_solution_patch_chars"]
        funcs = [r["avg_funcs_changed"] for r in ml_rows] if ml_rows else [0.0]
        classes = [r["avg_classes_changed"] for r in ml_rows] if ml_rows else [0.0]
        patches = [r["avg_patch_chars"] for r in ml_rows] if ml_rows else [0.0]
        return [
            self.primary_entity,
            f"{py_tasks} Python + {ml_tasks} Multi-Lang (Java, JS, TS)",
            f"Complexity: {min(funcs):.1f} to {max(funcs):.1f} functions, {min(classes):.1f} to {max(classes):.1f} classes changed/task",
            f"Avg Patch Size: {py_patch:.1f} chars Python, {min(patches):,.0f}-{max(patches):,.0f} chars PolyBench",
            self.lemon_market_implication,
        ]
