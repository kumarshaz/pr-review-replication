#!/usr/bin/env python3
"""
Dataset 16 Handler: Mined Production Jev Decision-Model PR Reviews
==================================================================
Processes real GitHub pull requests gated by TypeSafe Jev decision-model bots:
  1. `getsentry/sentry` `decision-model-linter` (`typesafe/jev-1.13-20260917`)
  2. Craftmill / OSS `<!-- pr-risk -->` calibrated risk histograms (`jev-1.14.0`)
  3. `mirrorstack-ai/mirrorstack-cli` `<!-- jev-review -->` hybrid fleet/policy gates

Compares Jev tollgates against paired Prose Review Bots (`cursor[bot]`, `coderabbitai[bot]`,
`veria-ai[bot]`, `chatgpt-codex-connector[bot]`, etc.), Static SAST Bots, and Human-Only
controls stratified by `author_origin` (`Coding_Agent` vs `Human_Engineer`).
"""
import csv
import os
from typing import Any, Dict, List, Optional

from config.bot_catalog import (
    EXCLUDED_AUTHOR_BOT_ACTORS,
    JEV_EXTRA_BOT_LOGINS,
    clean_jev_author_origin_sql,
    sql_in_list,
)
from src.handlers.base import BaseDatasetHandler


class JevPRReviewsHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_16_jev_pr_reviews"

    @property
    def dataset_name(self) -> str:
        return "Mined Production Jev Decision-Model PR Reviews (Sentry, Craftmill, Mirrorstack)"

    @property
    def primary_entity(self) -> str:
        return "Production Decision-Model PR Tollgates vs. Prose Bots (Human & Agent PRs)"

    @property
    def lemon_market_implication(self) -> str:
        return "Decision models compress review verbosity relative to prose bots and separate human merge outcomes on human PRs, while advisory flags alone do not deter autonomous agent merges"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/jev_pr_reviews/jev_pull_requests.parquet",
            "scratch/jev_pr_reviews/jev_bot_signals_and_comments.parquet",
            "scratch/jev_pr_reviews/jev_formal_reviews.parquet",
            "scratch/jev_pr_reviews/jev_git_commits.parquet",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p05_multicorpus_triangulation.py",
            "p12_jev_vs_prose_tollgates.py",
            "p16_jev_judgment_and_szz_outcomes.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["decision_model_tollgate", "bot_comment_density"]

    def _resolve_signals_parquet(self, jev_dir: str) -> tuple[str, str]:
        """Prefer enriched Jev signals written by p00_reparse_jev_offline.py without mutating scratch/."""
        reparsed_results = os.path.join(self.results_dir, "jev_bot_signals_reparsed.parquet")
        reparsed_tables = os.path.join(self.tables_dir, "jev_bot_signals_reparsed.parquet")
        raw_comms = os.path.join(jev_dir, "jev_bot_signals_and_comments.parquet")
        if os.path.exists(reparsed_results):
            return reparsed_results, "results_reparsed"
        if os.path.exists(reparsed_tables):
            return reparsed_tables, "tables_reparsed"
        return raw_comms, "raw_scratch"

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        jev_dir = self.scratch_path("jev_pr_reviews")
        f_prs = os.path.join(jev_dir, "jev_pull_requests.parquet")
        f_comms, comms_source = self._resolve_signals_parquet(jev_dir)
        f_commits = os.path.join(jev_dir, "jev_git_commits.parquet")

        clean_origin_sql = clean_jev_author_origin_sql("author_login", "author_origin")
        overall = con.execute(f"""
            WITH prs_clean AS (
                SELECT
                    *,
                    {clean_origin_sql} AS clean_author_origin
                FROM read_parquet('{f_prs}')
            )
            SELECT
                COUNT(*) AS total_prs,
                COUNT(DISTINCT repo_full_name) AS unique_repos,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_prs,
                ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
                SUM(CASE WHEN clean_author_origin = 'Coding_Agent' THEN 1 ELSE 0 END) AS coding_agent_prs,
                SUM(CASE WHEN clean_author_origin = 'Human_Engineer' THEN 1 ELSE 0 END) AS human_engineer_prs
            FROM prs_clean
        """).fetchone()

        extra_bots_lower = sorted(
            {b.lower() for b in JEV_EXTRA_BOT_LOGINS}
            | {b.lower() for b in EXCLUDED_AUTHOR_BOT_ACTORS}
        )
        extra_bots_sql = sql_in_list(extra_bots_lower)
        human_bot_exclusion_cond = (
            "LOWER(COALESCE(author_login, '')) LIKE '%[bot]' "
            "OR LOWER(COALESCE(author_login, '')) LIKE '%-bot' "
            f"OR LOWER(COALESCE(author_login, '')) IN ({extra_bots_sql})"
        )

        bot_families = con.execute(f"""
            WITH clean_comms AS (
                SELECT
                    *,
                    CASE
                        WHEN bot_family = 'human_comment' AND ({human_bot_exclusion_cond})
                        THEN 'other_bot'
                        ELSE bot_family
                    END AS clean_bot_family
                FROM read_parquet('{f_comms}')
            )
            SELECT
                clean_bot_family AS bot_family,
                COUNT(*) AS comment_rows,
                COUNT(DISTINCT repo_full_name || '#' || CAST(pr_number AS VARCHAR)) AS distinct_prs,
                ROUND(AVG(comment_chars), 1) AS avg_chars,
                ROUND(MEDIAN(comment_chars), 1) AS med_chars,
                ROUND(AVG(risk_score_normalized), 3) AS mean_risk_score,
                SUM(calls_count) AS total_calls,
                SUM(input_tokens) AS total_input_tokens,
                ROUND(SUM(cost_usd), 4) AS total_cost_usd
            FROM clean_comms
            GROUP BY clean_bot_family
            ORDER BY comment_rows DESC
        """).fetchall()

        clean_p_origin_sql = clean_jev_author_origin_sql("p.author_login", "p.author_origin")
        sentry_strat = con.execute(f"""
            WITH p_sig AS (
                SELECT
                    p.pr_number,
                    {clean_p_origin_sql} AS author_origin,
                    p.is_merged,
                    p.state,
                    MAX(CASE WHEN c.bot_family = 'jev_decision_model_linter' THEN 1 ELSE 0 END) AS has_dml,
                    MAX(CASE WHEN c.bot_family = 'jev_decision_model_linter' AND c.alerts_count > 0 THEN 1 ELSE 0 END) AS dml_flagged,
                    MAX(CASE WHEN c.bot_family = 'prose_review_bot_control' THEN 1 ELSE 0 END) AS has_prose,
                    SUM(
                        CASE
                            WHEN c.bot_family = 'human_comment'
                             AND LOWER(COALESCE(c.author_login, '')) NOT LIKE '%[bot]'
                             AND LOWER(COALESCE(c.author_login, '')) NOT LIKE '%-bot'
                             AND LOWER(COALESCE(c.author_login, '')) NOT IN ({extra_bots_sql})
                            THEN 1
                            ELSE 0
                        END
                    ) AS human_comms,
                    MAX(CASE WHEN c.bot_family = 'jev_decision_model_linter' THEN c.alerts_count ELSE 0 END) AS alerts_cnt
                FROM read_parquet('{f_prs}') p
                LEFT JOIN read_parquet('{f_comms}') c
                  ON p.repo_full_name = c.repo_full_name AND p.pr_number = c.pr_number
                WHERE p.repo_full_name = 'getsentry/sentry'
                  AND {clean_p_origin_sql} IN ('Coding_Agent', 'Human_Engineer')
                GROUP BY 1, 2, 3, 4
            )
            SELECT
                author_origin,
                CASE
                    WHEN has_dml = 1 AND dml_flagged = 1 THEN '1_Jev_DML_Flagged'
                    WHEN has_dml = 1 AND dml_flagged = 0 THEN '2_Jev_DML_Clean'
                    WHEN has_prose = 1 THEN '3_Prose_Bot_Only'
                    ELSE '4_No_Bot_Control'
                END AS gate_regime,
                COUNT(*) AS prs,
                SUM(CASE WHEN is_merged THEN 1 ELSE 0 END) AS merged_prs,
                ROUND(100.0 * AVG(CASE WHEN is_merged THEN 1.0 ELSE 0.0 END), 2) AS merge_rate_pct,
                ROUND(100.0 * AVG(CASE WHEN human_comms > 0 THEN 1.0 ELSE 0.0 END), 2) AS pct_with_human_comm,
                ROUND(AVG(human_comms), 2) AS avg_human_comms,
                ROUND(AVG(alerts_cnt), 2) AS avg_alerts
            FROM p_sig
            GROUP BY 1, 2
            ORDER BY 1, 2
        """).fetchall()

        commits_total = con.execute(f"SELECT COUNT(*) FROM read_parquet('{f_commits}')").fetchone()[0]

        csv_path = self.table_path("jev_decision_model_tollgate_log.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["table_type", "stratum_a", "stratum_b", "count_prs_or_rows", "metric_1", "metric_2", "metric_3", "notes"])
            for r in bot_families:
                w.writerow(["bot_family_summary", r[0], f"distinct_prs={r[2]}", r[1], r[3], r[5] or "", r[8], f"calls={r[6]}; tokens={r[7]}"])
            for r in sentry_strat:
                w.writerow(["sentry_2x2_regime", r[0], r[1], r[2], r[4], r[5], r[6], f"merged={r[3]}; avg_alerts={r[7]}"])

        fam_map = {
            r[0]: {
                "comment_rows": int(r[1]),
                "distinct_prs": int(r[2]),
                "avg_chars": float(r[3]),
                "med_chars": float(r[4]),
                "mean_risk_score": float(r[5]) if r[5] is not None else None,
                "total_calls": int(r[6]),
                "total_input_tokens": int(r[7]),
                "total_cost_usd": float(r[8]),
            }
            for r in bot_families
        }

        dml = fam_map.get("jev_decision_model_linter", {})
        prose = fam_map.get("prose_review_bot_control", {})
        dml_rows = dml.get("comment_rows", 0)
        dml_avg_chars = dml.get("avg_chars", 0.0)

        return {
            "dataset_name": "Mined Production Jev Decision-Model PR Reviews",
            "signals_source": comms_source,
            "signals_path": f_comms,
            "sample_size_n": int(overall[0]),
            "unique_repositories": int(overall[1]),
            "merged_count": int(overall[2]),
            "merge_rate_pct": float(overall[3]),
            "coding_agent_prs": int(overall[4]),
            "human_engineer_prs": int(overall[5]),
            "git_commits_logged": int(commits_total),
            "jev_signal_comments_total": sum(
                v["comment_rows"] for k, v in fam_map.items() if k.startswith("jev_")
            ),
            "jev_dml_cost_per_pr_usd": round(dml.get("total_cost_usd", 0.0) / dml_rows, 4) if dml_rows > 0 else 0.0,
            "jev_dml_calls_per_pr": round(dml.get("total_calls", 0) / dml_rows, 1) if dml_rows > 0 else 0.0,
            "prose_to_dml_verbosity_ratio": (
                round(prose.get("avg_chars", 0.0) / dml_avg_chars, 2) if dml_avg_chars > 0 else 0.0
            ),
            "bot_family_breakdown": fam_map,
            "sentry_2x2_stratification": [
                {
                    "author_origin": r[0],
                    "gate_regime": r[1],
                    "prs": int(r[2]),
                    "merged_prs": int(r[3]),
                    "merge_rate_pct": float(r[4]),
                    "pct_with_human_comm": float(r[5]),
                    "avg_human_comms": float(r[6]),
                    "avg_alerts": float(r[7]),
                }
                for r in sentry_strat
            ],
            "status": "verified_on_disk",
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        return [
            self.primary_entity,
            f"{result['sample_size_n']:,} PRs / {result['jev_signal_comments_total']:,} Jev signals ({result['unique_repositories']} repos)",
            f"DML cost=${result['jev_dml_cost_per_pr_usd']:.4f}/PR ({result['jev_dml_calls_per_pr']} calls); Compression={result['prose_to_dml_verbosity_ratio']:.1f}x",
            f"Agent PRs={result['coding_agent_prs']:,} vs Human PRs={result['human_engineer_prs']:,}",
            self.lemon_market_implication,
        ]
