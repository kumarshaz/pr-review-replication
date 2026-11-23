#!/usr/bin/env python3
"""
Pipeline 17: Full Net-New Open Questions Empirical Engine (NQ-01 through NQ-08).

100% grounded in real on-disk Parquet, CSV, and bare-git SZZ ledgers.
Zero GitHub API token required, zero fabricated metrics, zero silent defaults.

Ingests NQ-01 & NQ-02 from p16 (`jev_judgment_and_szz_outcomes.json`) and computes:
  - NQ-03: PR Description Bloat / "Walkthrough Theater" vs. Scrutiny & SZZ
  - NQ-04: Bot-to-Agent "Review Ping-Pong Thrashing" & Force-Push Rework vs. SZZ
  - NQ-05: "Fast LGTM" vs. Stalled Review Queue Bimodality & Bot-First Arrival Ordering
  - NQ-06: "Assertion Theater" in Production: Test Adaptedness vs. Real SZZ Bugfixes
  - NQ-07: Language-Regime Asymmetry & 14-Day Code Turnover as DORA Counter-Metric
  - NQ-08: Acute Reviewer Queue Burstiness, Maintainer Tenure & 60-Day CodeRabbit Alert-Fatigue

Outputs:
  - paths.results_dir / "open_questions_nq01_nq08_results.json"
  - paths.tables_dir / "nq03_pr_description_bloat_log.csv"
  - paths.tables_dir / "nq04_pingpong_rework_szz_log.csv"
  - paths.tables_dir / "nq05_review_speed_bimodality_log.csv"
  - paths.tables_dir / "nq06_assertion_theater_szz_log.csv"
  - paths.tables_dir / "nq07_language_turnover_szz_log.csv"
  - paths.tables_dir / "nq08_queue_burst_and_fatigue_log.csv"
  - paths.results_dir / "OPEN_QUESTIONS_NQ01_NQ08_REPORT.md"
"""

from __future__ import annotations

import csv
import datetime
import json
import math
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from scipy import stats

_PR_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
if str(_PR_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_PR_ANALYSIS_ROOT))

from config.bot_catalog import (  # noqa: E402
    DETERMINISTIC_SAST_BOTS,
    EXCLUDED_AUTHOR_BOT_ACTORS,
    TIER1_PR_COMMENTS_BOTS,
    TIER1_REVIEW_BOTS,
    classify_bot_brain_family,
    sql_in_list,
)
from config.paths import PathConfig, get_paths  # noqa: E402
from src.pipelines.p16_jev_judgment_and_szz_outcomes import run_p16  # noqa: E402
from src.utils.logging_utils import setup_verbose_logger  # noqa: E402
from src.utils.stats_utils import (  # noqa: E402
    bh_fdr,
    fisher_exact_2x2,
    gini_coefficient,
    two_prop_z_test,
    wilson_ci,
    yaml_frontmatter,
)


def _wilson_pct(k: int, n: int) -> list[float]:
    lo, hi = wilson_ci(int(k), int(n))
    return [round(100.0 * lo, 2), round(100.0 * hi, 2)]


def _safe_rate(k: int, n: int) -> float:
    return round(100.0 * k / n, 2) if n > 0 else 0.0


def _spearman(x: list[float], y: list[float]) -> dict[str, Any]:
    if len(x) < 5 or len(set(x)) < 2 or len(set(y)) < 2:
        return {"n": len(x), "rho": None, "p_value": None}
    rho, p_val = stats.spearmanr(x, y)
    return {
        "n": len(x),
        "rho": round(float(rho), 4) if not math.isnan(rho) else None,
        "p_value": float(p_val) if not math.isnan(p_val) else None,
    }


def _mann_whitney(vals_a: list[float], vals_b: list[float]) -> dict[str, Any]:
    if len(vals_a) < 2 or len(vals_b) < 2:
        return {"n_a": len(vals_a), "n_b": len(vals_b), "u_stat": None, "p_value": None}
    u_stat, p_val = stats.mannwhitneyu(vals_a, vals_b, alternative="two-sided")
    return {
        "n_a": len(vals_a),
        "n_b": len(vals_b),
        "median_a": round(float(np.median(vals_a)), 3),
        "median_b": round(float(np.median(vals_b)), 3),
        "u_stat": round(float(u_stat), 2),
        "p_value": float(p_val),
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _human_user_sql(col: str) -> str:
    excluded = sorted(
        {b.lower() for b in EXCLUDED_AUTHOR_BOT_ACTORS}
        | {b.lower() for b in TIER1_REVIEW_BOTS}
        | {b.lower() for b in DETERMINISTIC_SAST_BOTS}
    )
    in_clause = sql_in_list(excluded)
    return (
        f"LOWER(COALESCE({col}, '')) NOT LIKE '%[bot]' "
        f"AND LOWER(COALESCE({col}, '')) NOT LIKE '%-bot' "
        f"AND LOWER(COALESCE({col}, '')) NOT IN ({in_clause})"
    )


def _parse_coderabbit_profiles(zip_path: Path) -> dict[str, str]:
    """Parse .coderabbit.yaml profile (chill | default | assertive) keyed by lower(repo)."""
    profiles: dict[str, str] = {}
    if not zip_path.exists():
        return profiles
    with zipfile.ZipFile(zip_path) as zf:
        for entry in sorted(zf.namelist()):
            if not entry.endswith((".yaml", ".yml")):
                continue
            parts = entry.split("/")
            if len(parts) < 2 or "__" not in parts[1]:
                continue
            repo_slug = parts[1].replace("__", "/").lower()
            raw_txt = zf.read(entry).decode("utf-8", errors="ignore").lower()
            cleaned = "\n".join(
                re.sub(r"(^|\s)#.*$", "", ln)
                for ln in raw_txt.splitlines()
                if re.sub(r"(^|\s)#.*$", "", ln).strip()
            )
            if re.search(r"^\s*profile\s*:\s*['\"]?assertive['\"]?\b", cleaned, flags=re.MULTILINE):
                profiles[repo_slug] = "assertive"
            elif re.search(r"^\s*profile\s*:\s*['\"]?chill['\"]?\b", cleaned, flags=re.MULTILINE):
                profiles[repo_slug] = "chill"
            else:
                profiles[repo_slug] = "default"
    return profiles


def _map_language_regime(lang: str | None) -> str:
    l = (lang or "").strip()
    if l in {"Rust", "Go", "C", "C++"}:
        return "Compiled_Systems"
    if l in {"Java", "C#"}:
        return "Managed_OO"
    if l in {"Python", "TypeScript", "JavaScript", "Ruby"}:
        return "Dynamic_Gradual"
    return "Other"


def _compute_nq03(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    has_hotspot: bool,
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-03: Computing PR Description Bloat / Walkthrough Theater vs Scrutiny & SZZ")
    aidev_dir = paths.scratch_dir / "aidev"
    f_pr = aidev_dir / "pull_request.parquet"
    f_hpr = aidev_dir / "human_pull_request.parquet"
    f_coh = paths.tables_dir / "analyzed_human_reviewed_prs_log.csv"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    hs_expr = "COALESCE(s.pre_pr_30d_hotspot_fixes, 0)" if has_hotspot else "NULL::BIGINT"

    # 3A: Human Scrutiny (N=6,004)
    scrutiny_rows = con.execute(f"""
        WITH base AS (
            SELECT
                c.pr_id,
                c.cohort,
                CASE WHEN c.human_changes_req > 0 THEN 1 ELSE 0 END AS has_cr,
                CAST(c.rubber_stamp_approval AS BIGINT) AS is_rs,
                LENGTH(COALESCE(p.body, '')) AS body_chars,
                (CASE WHEN COALESCE(p.body, '') LIKE '%## %' OR COALESCE(p.body, '') LIKE '# %' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%- [%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%|---%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%```%' THEN 1 ELSE 0 END) AS structure_score,
                CASE WHEN COALESCE(p.body, '') LIKE '%- [%' THEN 1 ELSE 0 END AS has_checklist,
                CASE WHEN COALESCE(p.body, '') LIKE '%|---%' THEN 1 ELSE 0 END AS has_table
            FROM read_csv_auto('{f_coh.as_posix()}', header=true) c
            JOIN read_parquet('{f_pr.as_posix()}') p ON c.pr_id = p.id
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN body_chars < 100 THEN '1_<100'
                    WHEN body_chars < 500 THEN '2_100-499'
                    WHEN body_chars < 1500 THEN '3_500-1499'
                    WHEN body_chars < 3000 THEN '4_1500-2999'
                    ELSE '5_3000+'
                END AS body_bucket,
                *
            FROM base
        )
        SELECT
            body_bucket,
            COUNT(*) AS n,
            SUM(has_cr) AS cr_k,
            SUM(is_rs) AS rs_k,
            SUM(CASE WHEN body_chars >= 1500 AND structure_score >= 2 THEN 1 ELSE 0 END) AS theater_n,
            ROUND(AVG(body_chars), 1) AS mean_chars,
            ROUND(MEDIAN(body_chars), 1) AS med_chars
        FROM bucketed
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    scrutiny_pts = con.execute(f"""
        SELECT
            LENGTH(COALESCE(p.body, '')) AS body_chars,
            CASE WHEN c.human_changes_req > 0 THEN 1.0 ELSE 0.0 END AS has_cr,
            CAST(c.rubber_stamp_approval AS DOUBLE) AS is_rs,
            CASE WHEN LENGTH(COALESCE(p.body, '')) >= 1500 AND (
                (CASE WHEN COALESCE(p.body, '') LIKE '%## %' OR COALESCE(p.body, '') LIKE '# %' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%- [%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%|---%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(p.body, '') LIKE '%```%' THEN 1 ELSE 0 END)
            ) >= 2 THEN 1 ELSE 0 END AS walkthrough_theater
        FROM read_csv_auto('{f_coh.as_posix()}', header=true) c
        JOIN read_parquet('{f_pr.as_posix()}') p ON c.pr_id = p.id
    """).fetchall()

    # 3B: SZZ Outcomes (u30 Agent & Human)
    szz_rows = con.execute(f"""
        WITH ai_pr AS (
            SELECT LOWER(r.full_name) AS repo_l, p.number AS pr_number, p.body
            FROM read_parquet('{f_pr.as_posix()}') p
            JOIN read_parquet('{ (aidev_dir / 'repository.parquet').as_posix() }') r ON p.repo_id = r.id
        ),
        hu_pr AS (
            SELECT LOWER(REPLACE(repo_url, 'https://api.github.com/repos/', '')) AS repo_l, number AS pr_number, body
            FROM read_parquet('{f_hpr.as_posix()}')
        ),
        joined AS (
            SELECT
                s.corpus,
                s.uncensored_14d,
                s.uncensored_30d,
                s.szz_bugfix_14d,
                s.szz_bugfix_30d,
                s.file_survival_30d_pct,
                {hs_expr} AS pre_hotspot,
                LENGTH(COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '')) AS body_chars,
                (CASE WHEN COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '') LIKE '%## %'
                        OR COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '') LIKE '# %' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '') LIKE '%- [%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '') LIKE '%|---%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(CASE WHEN s.corpus = 'AIDev' THEN a.body ELSE h.body END, '') LIKE '%```%' THEN 1 ELSE 0 END) AS structure_score
            FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
            LEFT JOIN ai_pr a ON s.corpus = 'AIDev' AND LOWER(s.repo_full_name) = a.repo_l AND s.pr_number = a.pr_number
            LEFT JOIN hu_pr h ON s.corpus = 'AIDev_HumanBaseline' AND LOWER(s.repo_full_name) = h.repo_l AND s.pr_number = h.pr_number
            WHERE s.corpus IN ('AIDev', 'AIDev_HumanBaseline')
              AND s.uncensored_30d = 1
        ),
        bucketed AS (
            SELECT
                corpus,
                CASE
                    WHEN body_chars < 100 THEN '1_<100'
                    WHEN body_chars < 500 THEN '2_100-499'
                    WHEN body_chars < 1500 THEN '3_500-1499'
                    WHEN body_chars < 3000 THEN '4_1500-2999'
                    ELSE '5_3000+'
                END AS body_bucket,
                *
            FROM joined
        )
        SELECT
            corpus,
            body_bucket,
            COUNT(*) AS n,
            SUM(szz_bugfix_14d) AS bug14,
            SUM(szz_bugfix_30d) AS bug30,
            ROUND(AVG(file_survival_30d_pct), 2) AS mean_surv30,
            SUM(CASE WHEN pre_hotspot = 0 THEN 1 ELSE 0 END) AS cold_n,
            SUM(CASE WHEN pre_hotspot = 0 THEN szz_bugfix_30d ELSE 0 END) AS cold_bug30,
            SUM(CASE WHEN body_chars >= 1500 AND structure_score >= 2 THEN 1 ELSE 0 END) AS theater_n,
            SUM(CASE WHEN body_chars >= 1500 AND structure_score >= 2 THEN szz_bugfix_30d ELSE 0 END) AS theater_bug30
        FROM bucketed
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).fetchall()

    # Theater vs non-theater direct comparison on Agent SZZ
    theater_szz_rows = con.execute(f"""
        WITH ai_pr AS (
            SELECT LOWER(r.full_name) AS repo_l, p.number AS pr_number, p.body
            FROM read_parquet('{f_pr.as_posix()}') p
            JOIN read_parquet('{ (aidev_dir / 'repository.parquet').as_posix() }') r ON p.repo_id = r.id
        ),
        joined AS (
            SELECT
                s.szz_bugfix_30d,
                {hs_expr} AS pre_hotspot,
                LENGTH(COALESCE(a.body, '')) AS body_chars,
                (CASE WHEN COALESCE(a.body, '') LIKE '%## %' OR COALESCE(a.body, '') LIKE '# %' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(a.body, '') LIKE '%- [%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(a.body, '') LIKE '%|---%' THEN 1 ELSE 0 END)
                + (CASE WHEN COALESCE(a.body, '') LIKE '%```%' THEN 1 ELSE 0 END) AS structure_score
            FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
            JOIN ai_pr a ON LOWER(s.repo_full_name) = a.repo_l AND s.pr_number = a.pr_number
            WHERE s.corpus = 'AIDev' AND s.uncensored_30d = 1
        )
        SELECT
            CASE WHEN body_chars >= 1500 AND structure_score >= 2 THEN 'Walkthrough_Theater' ELSE 'Standard_Description' END AS grp,
            COUNT(*) AS n,
            SUM(szz_bugfix_30d) AS bug30,
            SUM(CASE WHEN pre_hotspot = 0 THEN 1 ELSE 0 END) AS cold_n,
            SUM(CASE WHEN pre_hotspot = 0 THEN szz_bugfix_30d ELSE 0 END) AS cold_bug30
        FROM joined
        GROUP BY 1
    """).fetchall()

    csv_rows: list[dict[str, Any]] = []
    scrutiny_list: list[dict[str, Any]] = []
    scrutiny_map: dict[str, tuple[int, int, int]] = {}
    for r in scrutiny_rows:
        bk, n, cr_k, rs_k = str(r[0]), int(r[1]), int(r[2]), int(r[3])
        scrutiny_map[bk] = (n, cr_k, rs_k)
        rec = {
            "panel": "Human_Scrutiny_N6004",
            "body_bucket": bk,
            "n": n,
            "human_cr_veto_pct": _safe_rate(cr_k, n),
            "human_cr_ci95_pct": _wilson_pct(cr_k, n),
            "rubber_stamp_pct": _safe_rate(rs_k, n),
            "rubber_stamp_ci95_pct": _wilson_pct(rs_k, n),
            "median_body_chars": float(r[6]),
        }
        scrutiny_list.append(rec)
        csv_rows.append({
            "panel": "Human_Scrutiny_N6004",
            "body_bucket": bk,
            "n": n,
            "human_cr_veto_pct": rec["human_cr_veto_pct"],
            "rubber_stamp_pct": rec["rubber_stamp_pct"],
            "szz_14d_pct": "",
            "szz_30d_pct": "",
            "szz_30d_ci95_low": "",
            "szz_30d_ci95_high": "",
            "cold_file_szz_30d_pct": "",
            "file_survival_30d_pct": "",
        })

    szz_by_corpus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    szz_bucket_map: dict[tuple[str, str], tuple[int, int, int]] = {}
    for r in szz_rows:
        corp, bk, n, b14, b30 = str(r[0]), str(r[1]), int(r[2]), int(r[3]), int(r[4])
        cold_n = int(r[6]) if has_hotspot else 0
        cold_b30 = int(r[7]) if has_hotspot else 0
        ci30 = _wilson_pct(b30, n)
        szz_bucket_map[(corp, bk)] = (n, b14, b30)
        rec = {
            "body_bucket": bk,
            "n": n,
            "szz_14d_pct": _safe_rate(b14, n),
            "szz_30d_pct": _safe_rate(b30, n),
            "szz_30d_ci95_pct": ci30,
            "file_survival_30d_pct": float(r[5]) if r[5] is not None else None,
            "cold_file_n": cold_n if has_hotspot else None,
            "cold_file_szz_30d_pct": _safe_rate(cold_b30, cold_n) if has_hotspot and cold_n > 0 else None,
        }
        szz_by_corpus[corp].append(rec)
        csv_rows.append({
            "panel": f"SZZ_u30::{corp}",
            "body_bucket": bk,
            "n": n,
            "human_cr_veto_pct": "",
            "rubber_stamp_pct": "",
            "szz_14d_pct": rec["szz_14d_pct"],
            "szz_30d_pct": rec["szz_30d_pct"],
            "szz_30d_ci95_low": ci30[0],
            "szz_30d_ci95_high": ci30[1],
            "cold_file_szz_30d_pct": rec["cold_file_szz_30d_pct"] if rec["cold_file_szz_30d_pct"] is not None else "",
            "file_survival_30d_pct": rec["file_survival_30d_pct"] if rec["file_survival_30d_pct"] is not None else "",
        })

    _write_csv(
        paths.tables_dir / "nq03_pr_description_bloat_log.csv",
        [
            "panel", "body_bucket", "n", "human_cr_veto_pct", "rubber_stamp_pct",
            "szz_14d_pct", "szz_30d_pct", "szz_30d_ci95_low", "szz_30d_ci95_high",
            "cold_file_szz_30d_pct", "file_survival_30d_pct",
        ],
        csv_rows,
    )

    tests_d: dict[str, Any] = {
        "spearman_body_chars_vs_human_cr": _spearman([float(x[0]) for x in scrutiny_pts], [float(x[1]) for x in scrutiny_pts]),
        "spearman_body_chars_vs_rubber_stamp": _spearman([float(x[0]) for x in scrutiny_pts], [float(x[2]) for x in scrutiny_pts]),
    }
    if "1_<100" in scrutiny_map and "5_3000+" in scrutiny_map:
        n1, cr1, rs1 = scrutiny_map["1_<100"]
        n5, cr5, rs5 = scrutiny_map["5_3000+"]
        tests_d["scrutiny_cr_lt100_vs_3000plus"] = two_prop_z_test(cr1, n1, cr5, n5)
        tests_d["scrutiny_rubber_stamp_lt100_vs_3000plus"] = two_prop_z_test(rs1, n1, rs5, n5)
    if ("AIDev", "1_<100") in szz_bucket_map and ("AIDev", "5_3000+") in szz_bucket_map:
        n1, _, b1 = szz_bucket_map[("AIDev", "1_<100")]
        n5, _, b5 = szz_bucket_map[("AIDev", "5_3000+")]
        tests_d["agent_szz30_lt100_vs_3000plus"] = two_prop_z_test(b1, n1, b5, n5)
    if ("AIDev", "3_500-1499") in szz_bucket_map and ("AIDev", "5_3000+") in szz_bucket_map:
        n3, _, b3 = szz_bucket_map[("AIDev", "3_500-1499")]
        n5, _, b5 = szz_bucket_map[("AIDev", "5_3000+")]
        tests_d["agent_szz30_500_1499_vs_3000plus"] = two_prop_z_test(b3, n3, b5, n5)

    t_map = {r[0]: r for r in theater_szz_rows}
    if "Walkthrough_Theater" in t_map and "Standard_Description" in t_map:
        wt, st = t_map["Walkthrough_Theater"], t_map["Standard_Description"]
        tests_d["walkthrough_theater_vs_standard_agent_szz30"] = two_prop_z_test(
            int(st[2]), int(st[1]), int(wt[2]), int(wt[1])
        )

    return {
        "human_scrutiny_by_body_chars": scrutiny_list,
        "szz_u30_by_body_chars": dict(szz_by_corpus),
        "statistical_tests": tests_d,
    }, csv_rows


def _compute_nq04(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    has_hotspot: bool,
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-04: Computing Review Ping-Pong Thrashing & Force-Push Rework vs SZZ")
    aidev_dir = paths.scratch_dir / "aidev"
    f_pr = aidev_dir / "pull_request.parquet"
    f_repo = aidev_dir / "repository.parquet"
    f_rev = aidev_dir / "pr_reviews.parquet"
    f_rc2 = aidev_dir / "pr_review_comments_v2.parquet"
    f_tl = aidev_dir / "pr_timeline.parquet"
    f_coh = paths.tables_dir / "analyzed_human_reviewed_prs_log.csv"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    # Compute exact reply-thread depth in Python over pr_review_comments_v2
    rc2_edges = con.execute(f"""
        SELECT
            r.pr_id,
            rc.id,
            CAST(rc.in_reply_to_id AS BIGINT) AS parent_id,
            CASE WHEN rc.commit_id IS NOT NULL
                  AND rc.original_commit_id IS NOT NULL
                  AND rc.commit_id != rc.original_commit_id
                 THEN 1 ELSE 0 END AS is_rework
        FROM read_parquet('{f_rc2.as_posix()}') rc
        JOIN read_parquet('{f_rev.as_posix()}') r
          ON rc.pull_request_review_id = r.id
    """).fetchall()

    parent_of: dict[int, int] = {}
    pr_comments: dict[int, list[tuple[int, int | None, int]]] = defaultdict(list)
    for pr_id, cid, pid, rew in rc2_edges:
        c_int = int(cid)
        p_int = int(pid) if pid is not None and not math.isnan(pid) else None
        if p_int is not None:
            parent_of[c_int] = p_int
        pr_comments[int(pr_id)].append((c_int, p_int, int(rew)))

    depth_cache: dict[int, int] = {}

    def _depth(cid: int) -> int:
        if cid in depth_cache:
            return depth_cache[cid]
        seen = set()
        cur = cid
        d = 0
        while cur in parent_of and cur not in seen:
            seen.add(cur)
            cur = parent_of[cur]
            d += 1
        depth_cache[cid] = d
        return d

    pr_pingpong_rows = []
    for pr_id, items in pr_comments.items():
        n_inline = len(items)
        n_replies = sum(1 for _, p, _ in items if p is not None)
        max_d = max((_depth(c) for c, _, _ in items), default=0)
        rew_cnt = sum(r for _, _, r in items)
        pr_pingpong_rows.append((pr_id, n_inline, n_replies, max_d, 1 if rew_cnt > 0 else 0, rew_cnt))

    con.execute("DROP TABLE IF EXISTS _tmp_nq04_pingpong")
    con.execute("""
        CREATE TEMP TABLE _tmp_nq04_pingpong (
            pr_id BIGINT, inline_comments BIGINT, reply_turns BIGINT,
            max_thread_depth BIGINT, rework_after_inline BIGINT, rework_comments BIGINT
        )
    """)
    if pr_pingpong_rows:
        con.executemany("INSERT INTO _tmp_nq04_pingpong VALUES (?, ?, ?, ?, ?, ?)", pr_pingpong_rows)

    hs_expr = "COALESCE(s.pre_pr_30d_hotspot_fixes, 0)" if has_hotspot else "NULL::BIGINT"
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_nq04_base AS
        WITH fp AS (
            SELECT pr_id, COUNT(*) AS force_push_cnt
            FROM read_parquet('{f_tl.as_posix()}')
            WHERE event = 'head_ref_force_pushed'
            GROUP BY 1
        )
        SELECT
            s.repo_full_name,
            s.pr_number,
            p.id AS pr_id,
            COALESCE(c.cohort, 'Cohort_A_No_Human_Review') AS cohort,
            s.task_type,
            s.uncensored_60d,
            s.szz_bugfix_14d,
            s.szz_bugfix_30d,
            s.file_survival_30d_pct,
            s.fix_induces_fix_k60d,
            {hs_expr} AS pre_hotspot,
            COALESCE(pp.inline_comments, 0) AS inline_comments,
            COALESCE(pp.reply_turns, 0) AS reply_turns,
            COALESCE(pp.max_thread_depth, 0) AS max_thread_depth,
            COALESCE(pp.rework_after_inline, 0) AS rework_after_inline,
            CASE WHEN COALESCE(fp.force_push_cnt, 0) > 0 THEN 1 ELSE 0 END AS force_pushed,
            COALESCE(fp.force_push_cnt, 0) AS force_push_cnt
        FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
        JOIN read_parquet('{f_repo.as_posix()}') r ON LOWER(s.repo_full_name) = LOWER(r.full_name)
        JOIN read_parquet('{f_pr.as_posix()}') p ON p.repo_id = r.id AND p.number = s.pr_number
        LEFT JOIN read_csv_auto('{f_coh.as_posix()}', header=true) c ON p.id = c.pr_id
        LEFT JOIN _tmp_nq04_pingpong pp ON p.id = pp.pr_id
        LEFT JOIN fp ON p.id = fp.pr_id
        WHERE s.corpus = 'AIDev' AND s.uncensored_30d = 1
    """)

    def _agg_dim(dim_name: str, dim_sql: str, scope_label: str, where_sql: str) -> list[dict[str, Any]]:
        rows = con.execute(f"""
            SELECT
                {dim_sql} AS stratum,
                COUNT(*) AS n,
                SUM(szz_bugfix_14d) AS b14,
                SUM(szz_bugfix_30d) AS b30,
                ROUND(AVG(file_survival_30d_pct), 2) AS surv30,
                SUM(CASE WHEN task_type = 'fix' AND uncensored_60d = 1 THEN 1 ELSE 0 END) AS n_fix_u60,
                ROUND(AVG(fix_induces_fix_k60d) FILTER (WHERE task_type = 'fix' AND uncensored_60d = 1), 3) AS mean_k60d,
                SUM(CASE WHEN fix_induces_fix_k60d > 0 THEN 1 ELSE 0 END) FILTER (WHERE task_type = 'fix' AND uncensored_60d = 1) AS k60d_gt0
            FROM v_nq04_base
            WHERE {where_sql}
            GROUP BY 1
            ORDER BY 1
        """).fetchall()
        out = []
        for r in rows:
            n = int(r[1])
            b14, b30 = int(r[2]), int(r[3])
            n_fix_u60 = int(r[5])
            k_gt0 = int(r[7]) if r[7] is not None else 0
            ci30 = _wilson_pct(b30, n)
            out.append({
                "dimension": dim_name,
                "scope": scope_label,
                "stratum": str(r[0]),
                "n": n,
                "szz_14d_pct": _safe_rate(b14, n),
                "szz_30d_pct": _safe_rate(b30, n),
                "szz_30d_ci95_low": ci30[0],
                "szz_30d_ci95_high": ci30[1],
                "file_survival_30d_pct": float(r[4]) if r[4] is not None else None,
                "n_fix_u60": n_fix_u60,
                "mean_fix_induces_fix_k60d": float(r[6]) if r[6] is not None else None,
                "pct_k60d_gt0": _safe_rate(k_gt0, n_fix_u60) if n_fix_u60 > 0 else None,
                "_k30": b30,
                "_n": n,
            })
        return out

    scopes = [
        ("ALL_u30", "1=1"),
        ("Cohort_B_Human_Only", "cohort = 'Cohort_B_Human_Only'"),
        ("Cohort_C_Tier1_Bot_Plus_Human", "cohort = 'Cohort_C_Tier1_Bot_Plus_Human'"),
    ]
    if has_hotspot:
        scopes.append(("Cold_Files_Only", "pre_hotspot = 0"))

    dims = [
        (
            "reply_thread_turns",
            "CASE WHEN reply_turns = 0 THEN '0_turns' WHEN reply_turns <= 2 THEN '1-2_turns' ELSE '3+_turns' END",
        ),
        (
            "rework_after_inline_comment",
            "CASE WHEN rework_after_inline = 1 THEN '1_rework' ELSE '0_no_rework' END",
        ),
        (
            "force_pushed",
            "CASE WHEN force_pushed = 1 THEN '1_force_pushed' ELSE '0_no_force_push' END",
        ),
    ]

    all_records: list[dict[str, Any]] = []
    tests_d: dict[str, Any] = {}
    for dname, dsql in dims:
        for sname, swhere in scopes:
            recs = _agg_dim(dname, dsql, sname, swhere)
            all_records.extend(recs)
            rmap = {x["stratum"]: x for x in recs}
            if dname == "reply_thread_turns" and "0_turns" in rmap and "3+_turns" in rmap:
                a, b = rmap["0_turns"], rmap["3+_turns"]
                tests_d[f"{sname}::reply_0_vs_3plus"] = two_prop_z_test(a["_k30"], a["_n"], b["_k30"], b["_n"])
            elif dname == "rework_after_inline_comment" and "0_no_rework" in rmap and "1_rework" in rmap:
                a, b = rmap["0_no_rework"], rmap["1_rework"]
                tests_d[f"{sname}::rework_0_vs_1"] = two_prop_z_test(a["_k30"], a["_n"], b["_k30"], b["_n"])
            elif dname == "force_pushed" and "0_no_force_push" in rmap and "1_force_pushed" in rmap:
                a, b = rmap["0_no_force_push"], rmap["1_force_pushed"]
                tests_d[f"{sname}::force_push_0_vs_1"] = two_prop_z_test(a["_k30"], a["_n"], b["_k30"], b["_n"])

    csv_rows = [
        {k: v for k, v in rec.items() if not k.startswith("_")}
        for rec in all_records
    ]
    _write_csv(
        paths.tables_dir / "nq04_pingpong_rework_szz_log.csv",
        [
            "dimension", "scope", "stratum", "n", "szz_14d_pct", "szz_30d_pct",
            "szz_30d_ci95_low", "szz_30d_ci95_high", "file_survival_30d_pct",
            "n_fix_u60", "mean_fix_induces_fix_k60d", "pct_k60d_gt0",
        ],
        csv_rows,
    )
    con.execute("DROP TABLE IF EXISTS _tmp_nq04_pingpong")
    return {"strata_outcomes": csv_rows, "statistical_tests": tests_d}, csv_rows


def _compute_nq05(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-05: Computing Review Speed Bimodality & Bot-First Arrival Ordering")
    aidev_dir = paths.scratch_dir / "aidev"
    f_pr = aidev_dir / "pull_request.parquet"
    f_repo = aidev_dir / "repository.parquet"
    f_rev = aidev_dir / "pr_reviews.parquet"
    f_comm = aidev_dir / "pr_comments.parquet"
    f_rc2 = aidev_dir / "pr_review_comments_v2.parquet"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    tier1_all_in = sql_in_list(TIER1_REVIEW_BOTS)
    tier1_comm_in = sql_in_list(TIER1_PR_COMMENTS_BOTS)
    human_rev_sql = _human_user_sql('"user"')

    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_nq05_reviewed AS
        WITH hrev AS (
            SELECT
                pr_id,
                MIN(TRY_CAST(submitted_at AS TIMESTAMPTZ)) AS first_human_ts,
                MAX(CASE WHEN state = 'CHANGES_REQUESTED' THEN 1 ELSE 0 END) AS has_cr,
                MAX(CASE WHEN state = 'APPROVED' AND LENGTH(TRIM(COALESCE(body, ''))) <= 15 THEN 1 ELSE 0 END) AS has_rs_app,
                MAX(CASE WHEN state = 'CHANGES_REQUESTED' OR LENGTH(TRIM(COALESCE(body, ''))) > 15 THEN 1 ELSE 0 END) AS has_sub
            FROM read_parquet('{f_rev.as_posix()}')
            WHERE user_type = 'User' AND {human_rev_sql}
            GROUP BY 1
        ),
        h_inline AS (
            SELECT
                r.pr_id,
                COUNT(rc.id) AS inline_comments
            FROM read_parquet('{f_rc2.as_posix()}') rc
            JOIN read_parquet('{f_rev.as_posix()}') r ON rc.pull_request_review_id = r.id
            WHERE rc.user_type = 'User' AND {human_rev_sql.replace('"user"', 'rc."user"')}
            GROUP BY 1
        ),
        bot_ts AS (
            SELECT pr_id, MIN(ts) AS first_bot_ts
            FROM (
                SELECT pr_id, TRY_CAST(submitted_at AS TIMESTAMPTZ) AS ts
                FROM read_parquet('{f_rev.as_posix()}')
                WHERE "user" IN ({tier1_all_in})
                UNION ALL
                SELECT pr_id, TRY_CAST(created_at AS TIMESTAMPTZ) AS ts
                FROM read_parquet('{f_comm.as_posix()}')
                WHERE "user" IN ({tier1_comm_in})
                UNION ALL
                SELECT r.pr_id, TRY_CAST(rc.created_at AS TIMESTAMPTZ) AS ts
                FROM read_parquet('{f_rc2.as_posix()}') rc
                JOIN read_parquet('{f_rev.as_posix()}') r ON rc.pull_request_review_id = r.id
                WHERE rc."user" IN ({tier1_all_in})
                  AND COALESCE(r."user", '') != 'copilot-swe-agent[bot]'
            ) t
            WHERE ts IS NOT NULL
            GROUP BY 1
        )
        SELECT
            s.repo_full_name,
            s.pr_number,
            p.id AS pr_id,
            TRY_CAST(p.created_at AS TIMESTAMPTZ) AS created_ts,
            TRY_CAST(p.merged_at AS TIMESTAMPTZ) AS merged_ts,
            hr.first_human_ts,
            bt.first_bot_ts,
            DATE_DIFF('second', TRY_CAST(p.created_at AS TIMESTAMPTZ), hr.first_human_ts) / 60.0 AS open_to_first_human_mins,
            DATE_DIFF('second', hr.first_human_ts, TRY_CAST(p.merged_at AS TIMESTAMPTZ)) / 60.0 AS first_human_to_merge_mins,
            hr.has_cr,
            CASE WHEN hr.has_rs_app = 1 AND hr.has_sub = 0 AND COALESCE(hi.inline_comments, 0) = 0 THEN 1 ELSE 0 END AS rubber_stamp_only,
            s.szz_bugfix_14d,
            s.szz_bugfix_30d,
            s.reverted_30d,
            s.file_survival_30d_pct,
            CASE
                WHEN bt.first_bot_ts IS NULL THEN '3_No_Tier1_Bot'
                WHEN bt.first_bot_ts < hr.first_human_ts THEN '1_Bot_First'
                ELSE '2_Human_First'
            END AS arrival_order
        FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
        JOIN read_parquet('{f_repo.as_posix()}') r ON LOWER(s.repo_full_name) = LOWER(r.full_name)
        JOIN read_parquet('{f_pr.as_posix()}') p ON p.repo_id = r.id AND p.number = s.pr_number
        JOIN hrev hr ON p.id = hr.pr_id
        LEFT JOIN h_inline hi ON p.id = hi.pr_id
        LEFT JOIN bot_ts bt ON p.id = bt.pr_id
        WHERE s.corpus = 'AIDev' AND s.uncensored_30d = 1
    """)

    tot_reviewed, neg_open_cnt, neg_merge_cnt = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN open_to_first_human_mins < 0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN first_human_to_merge_mins < 0 THEN 1 ELSE 0 END)
        FROM v_nq05_reviewed
    """).fetchone()

    def _query_bucket(dim_name: str, bucket_sql: str, extra_where: str) -> list[dict[str, Any]]:
        rows = con.execute(f"""
            SELECT
                {bucket_sql} AS bucket,
                COUNT(*) AS n,
                SUM(szz_bugfix_14d) AS b14,
                SUM(szz_bugfix_30d) AS b30,
                SUM(reverted_30d) AS rev30,
                ROUND(AVG(file_survival_30d_pct), 2) AS surv30,
                SUM(has_cr) AS cr_k,
                SUM(rubber_stamp_only) AS rs_k,
                ROUND(MEDIAN(CASE WHEN first_human_to_merge_mins >= 0 THEN first_human_to_merge_mins END), 2) AS med_rev_to_merge_mins
            FROM v_nq05_reviewed
            WHERE {extra_where}
            GROUP BY 1
            ORDER BY 1
        """).fetchall()
        out = []
        for r in rows:
            n = int(r[1])
            b14, b30, rev30, cr_k, rs_k = int(r[2]), int(r[3]), int(r[4]), int(r[6]), int(r[7])
            ci30 = _wilson_pct(b30, n)
            out.append({
                "dimension": dim_name,
                "bucket": str(r[0]),
                "n": n,
                "szz_14d_pct": _safe_rate(b14, n),
                "szz_30d_pct": _safe_rate(b30, n),
                "szz_30d_ci95_low": ci30[0],
                "szz_30d_ci95_high": ci30[1],
                "reverted_30d_pct": _safe_rate(rev30, n),
                "file_survival_30d_pct": float(r[5]) if r[5] is not None else None,
                "human_cr_veto_pct": _safe_rate(cr_k, n),
                "rubber_stamp_pct": _safe_rate(rs_k, n),
                "median_review_to_merge_mins": float(r[8]) if r[8] is not None else None,
                "_b30": b30,
                "_cr_k": cr_k,
                "_rs_k": rs_k,
                "_n": n,
            })
        return out

    open_buckets = _query_bucket(
        "open_to_first_human_review",
        """CASE
            WHEN open_to_first_human_mins < 5.0 THEN '1_<5m_Fast_LGTM'
            WHEN open_to_first_human_mins < 30.0 THEN '2_5-30m'
            WHEN open_to_first_human_mins < 240.0 THEN '3_30m-4h'
            ELSE '4_>4h_Stalled'
        END""",
        "open_to_first_human_mins >= 0",
    )
    merge_buckets = _query_bucket(
        "first_human_review_to_merge",
        """CASE
            WHEN first_human_to_merge_mins < 5.0 THEN '1_<5m'
            WHEN first_human_to_merge_mins <= 60.0 THEN '2_5-60m'
            ELSE '3_>60m'
        END""",
        "first_human_to_merge_mins >= 0",
    )
    arrival_buckets = _query_bucket("bot_vs_human_arrival_order", "arrival_order", "first_human_to_merge_mins >= 0")

    # Mann-Whitney U on review-to-merge latency: Bot_First vs Human_First
    bot_first_lat = [
        float(r[0])
        for r in con.execute(
            "SELECT first_human_to_merge_mins FROM v_nq05_reviewed WHERE arrival_order = '1_Bot_First' AND first_human_to_merge_mins >= 0"
        ).fetchall()
    ]
    human_first_lat = [
        float(r[0])
        for r in con.execute(
            "SELECT first_human_to_merge_mins FROM v_nq05_reviewed WHERE arrival_order = '2_Human_First' AND first_human_to_merge_mins >= 0"
        ).fetchall()
    ]

    all_recs = open_buckets + merge_buckets + arrival_buckets
    csv_rows = [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in all_recs]
    _write_csv(
        paths.tables_dir / "nq05_review_speed_bimodality_log.csv",
        [
            "dimension", "bucket", "n", "szz_14d_pct", "szz_30d_pct",
            "szz_30d_ci95_low", "szz_30d_ci95_high", "reverted_30d_pct",
            "file_survival_30d_pct", "human_cr_veto_pct", "rubber_stamp_pct",
            "median_review_to_merge_mins",
        ],
        csv_rows,
    )

    omap = {x["bucket"]: x for x in open_buckets}
    amap = {x["bucket"]: x for x in arrival_buckets}
    tests_d: dict[str, Any] = {
        "bot_first_vs_human_first_review_to_merge_mw": _mann_whitney(bot_first_lat, human_first_lat),
    }
    if "1_<5m_Fast_LGTM" in omap and "4_>4h_Stalled" in omap:
        a, b = omap["1_<5m_Fast_LGTM"], omap["4_>4h_Stalled"]
        tests_d["fast_lgtm_vs_stalled_szz30"] = two_prop_z_test(a["_b30"], a["_n"], b["_b30"], b["_n"])
        tests_d["fast_lgtm_vs_stalled_cr"] = two_prop_z_test(a["_cr_k"], a["_n"], b["_cr_k"], b["_n"])
    if "1_Bot_First" in amap and "2_Human_First" in amap:
        a, b = amap["1_Bot_First"], amap["2_Human_First"]
        tests_d["bot_first_vs_human_first_cr"] = two_prop_z_test(a["_cr_k"], a["_n"], b["_cr_k"], b["_n"])
        tests_d["bot_first_vs_human_first_rubber_stamp"] = two_prop_z_test(a["_rs_k"], a["_n"], b["_rs_k"], b["_n"])
        tests_d["bot_first_vs_human_first_szz30"] = two_prop_z_test(a["_b30"], a["_n"], b["_b30"], b["_n"])

    return {
        "total_u30_human_reviewed_prs": int(tot_reviewed),
        "disclosed_negative_open_to_review_skew_prs": int(neg_open_cnt),
        "disclosed_negative_review_to_merge_skew_prs": int(neg_merge_cnt),
        "buckets": csv_rows,
        "statistical_tests": tests_d,
    }, csv_rows


def _compute_nq06(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    has_hotspot: bool,
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-06: Computing Assertion Theater (Test Adaptedness vs Real SZZ Bugfixes)")
    f_tq = paths.scratch_dir / "agentic_prs" / "pr_test_quality.parquet"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"

    hs_expr = "COALESCE(s.pre_pr_30d_hotspot_fixes, 0)" if has_hotspot else "NULL::BIGINT"

    # Cross-corpus join: AgenticPRs test quality x SZZ u30 (preserving is_agent & corpus stratification)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_nq06_tq AS
        SELECT
            s.corpus,
            tq.is_agent,
            CASE
                WHEN s.corpus = 'AIDev' AND tq.is_agent = true THEN 'Agent'
                WHEN s.corpus = 'AIDev_HumanBaseline' AND tq.is_agent = false THEN 'Human'
                ELSE 'Other'
            END AS agent_stratum,
            tq.adapted,
            tq.trivial,
            tq.specific,
            tq.relevant,
            tq.assertion_count,
            s.szz_bugfix_14d,
            s.szz_bugfix_30d,
            s.file_survival_30d_pct,
            {hs_expr} AS pre_hotspot
        FROM read_parquet('{f_tq.as_posix()}') tq
        JOIN read_csv_auto('{f_szz.as_posix()}', header=true) s
          ON LOWER(tq.repo_name) = LOWER(s.repo_full_name)
         AND tq.number = s.pr_number
        WHERE s.uncensored_30d = 1
    """)

    csv_rows: list[dict[str, Any]] = []
    cross_tests: dict[str, Any] = {}
    cold_select = (
        "SUM(CASE WHEN pre_hotspot = 0 THEN 1 ELSE 0 END) AS cold_n, "
        "SUM(CASE WHEN pre_hotspot = 0 THEN szz_bugfix_30d ELSE 0 END) AS cold_b30"
        if has_hotspot
        else "0 AS cold_n, 0 AS cold_b30"
    )

    def _run_tq_panel(panel_name: str, where_sql: str, test_prefix: str) -> None:
        for col in ("adapted", "trivial", "specific", "relevant"):
            rows = con.execute(f"""
                SELECT
                    CAST({col} AS VARCHAR) AS val,
                    COUNT(*) AS n,
                    SUM(szz_bugfix_14d) AS b14,
                    SUM(szz_bugfix_30d) AS b30,
                    ROUND(AVG(file_survival_30d_pct), 2) AS surv30,
                    {cold_select}
                FROM v_nq06_tq
                WHERE {where_sql}
                GROUP BY 1
                ORDER BY 1
            """).fetchall()
            rmap = {}
            for r in rows:
                val, n, b14, b30 = str(r[0]), int(r[1]), int(r[2]), int(r[3])
                cold_n = int(r[5]) if has_hotspot else 0
                cold_b30 = int(r[6]) if has_hotspot else 0
                ci30 = _wilson_pct(b30, n)
                rmap[val] = (n, b14, b30)
                csv_rows.append({
                    "panel": panel_name,
                    "dimension": col,
                    "stratum": f"{col}={val}",
                    "n": n,
                    "szz_14d_pct": _safe_rate(b14, n),
                    "szz_30d_pct": _safe_rate(b30, n),
                    "szz_30d_ci95_low": ci30[0],
                    "szz_30d_ci95_high": ci30[1],
                    "file_survival_30d_pct": float(r[4]) if r[4] is not None else None,
                    "cold_file_szz_30d_pct": _safe_rate(cold_b30, cold_n) if has_hotspot and cold_n > 0 else "",
                })
            if "false" in rmap and "true" in rmap:
                nf, _, bf = rmap["false"]
                nt, _, bt = rmap["true"]
                cross_tests[f"{test_prefix}{col}_false_vs_true"] = {
                    **two_prop_z_test(bf, nf, bt, nt),
                    "fisher_p": fisher_exact_2x2(bf, nf, bt, nt),
                }

        for r in con.execute(f"""
            SELECT
                CASE WHEN assertion_count = 0 THEN '0_assertions'
                     WHEN assertion_count <= 5 THEN '1-5_assertions'
                     ELSE '6+_assertions' END AS tier,
                COUNT(*) AS n,
                SUM(szz_bugfix_14d) AS b14,
                SUM(szz_bugfix_30d) AS b30,
                ROUND(AVG(file_survival_30d_pct), 2) AS surv30,
                {cold_select}
            FROM v_nq06_tq
            WHERE {where_sql}
            GROUP BY 1 ORDER BY 1
        """).fetchall():
            n, b14, b30 = int(r[1]), int(r[2]), int(r[3])
            cold_n = int(r[5]) if has_hotspot else 0
            cold_b30 = int(r[6]) if has_hotspot else 0
            ci30 = _wilson_pct(b30, n)
            csv_rows.append({
                "panel": panel_name,
                "dimension": "assertion_count_tier",
                "stratum": str(r[0]),
                "n": n,
                "szz_14d_pct": _safe_rate(b14, n),
                "szz_30d_pct": _safe_rate(b30, n),
                "szz_30d_ci95_low": ci30[0],
                "szz_30d_ci95_high": ci30[1],
                "file_survival_30d_pct": float(r[4]) if r[4] is not None else None,
                "cold_file_szz_30d_pct": _safe_rate(cold_b30, cold_n) if has_hotspot and cold_n > 0 else "",
            })

    _run_tq_panel("AgenticPRs_x_SZZ_u30", "1=1", "")
    _run_tq_panel("AgenticPRs_x_SZZ_u30::Agent", "agent_stratum = 'Agent'", "Agent::")
    _run_tq_panel("AgenticPRs_x_SZZ_u30::Human", "agent_stratum = 'Human'", "Human::")

    # Full-scale SZZ test_files_count > 0 vs == 0
    full_rows = con.execute(f"""
        SELECT
            corpus,
            CASE WHEN test_files_count > 0 THEN 'Has_Tests (>0)' ELSE 'No_Tests (0)' END AS test_presence,
            COUNT(*) AS n,
            SUM(szz_bugfix_14d) AS b14,
            SUM(szz_bugfix_30d) AS b30,
            ROUND(AVG(file_survival_30d_pct), 2) AS surv30,
            SUM(CASE WHEN {hs_expr.replace('s.', '')} = 0 THEN 1 ELSE 0 END) AS cold_n,
            SUM(CASE WHEN {hs_expr.replace('s.', '')} = 0 THEN szz_bugfix_30d ELSE 0 END) AS cold_b30
        FROM read_csv_auto('{f_szz.as_posix()}', header=true)
        WHERE corpus IN ('AIDev', 'AIDev_HumanBaseline')
          AND uncensored_30d = 1
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).fetchall()

    full_tests: dict[str, Any] = {}
    full_map: dict[tuple[str, str], tuple[int, int, int, int]] = {}
    for r in full_rows:
        corp, tp, n, b14, b30 = str(r[0]), str(r[1]), int(r[2]), int(r[3]), int(r[4])
        cold_n = int(r[6]) if has_hotspot else 0
        cold_b30 = int(r[7]) if has_hotspot else 0
        ci30 = _wilson_pct(b30, n)
        full_map[(corp, tp)] = (n, b30, cold_n, cold_b30)
        csv_rows.append({
            "panel": f"Full_SZZ_u30::{corp}",
            "dimension": "test_files_count",
            "stratum": tp,
            "n": n,
            "szz_14d_pct": _safe_rate(b14, n),
            "szz_30d_pct": _safe_rate(b30, n),
            "szz_30d_ci95_low": ci30[0],
            "szz_30d_ci95_high": ci30[1],
            "file_survival_30d_pct": float(r[5]) if r[5] is not None else None,
            "cold_file_szz_30d_pct": _safe_rate(cold_b30, cold_n) if has_hotspot and cold_n > 0 else "",
        })

    for corp in ("AIDev", "AIDev_HumanBaseline"):
        if (corp, "No_Tests (0)") in full_map and (corp, "Has_Tests (>0)") in full_map:
            n0, b0, cn0, cb0 = full_map[(corp, "No_Tests (0)")]
            n1, b1, cn1, cb1 = full_map[(corp, "Has_Tests (>0)")]
            full_tests[f"{corp}::no_tests_vs_has_tests"] = two_prop_z_test(b0, n0, b1, n1)
            if has_hotspot and cn0 > 0 and cn1 > 0:
                full_tests[f"{corp}::cold_no_tests_vs_has_tests"] = two_prop_z_test(cb0, cn0, cb1, cn1)

    _write_csv(
        paths.tables_dir / "nq06_assertion_theater_szz_log.csv",
        [
            "panel", "dimension", "stratum", "n", "szz_14d_pct", "szz_30d_pct",
            "szz_30d_ci95_low", "szz_30d_ci95_high", "file_survival_30d_pct",
            "cold_file_szz_30d_pct",
        ],
        csv_rows,
    )

    matched_tq_n = con.execute("SELECT COUNT(*) FROM v_nq06_tq").fetchone()[0]
    return {
        "matched_agentic_prs_x_szz_u30_n": int(matched_tq_n),
        "cross_corpus_tests": cross_tests,
        "full_szz_test_presence_tests": full_tests,
        "rows": csv_rows,
    }, csv_rows


def _compute_nq07(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    has_hotspot: bool,
    has_surv14: bool,
    has_surv30_all: bool,
    cr_profiles: dict[str, str],
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-07: Computing Language-Regime Asymmetry, 14d/30d Code Turnover, CodeRabbit Labels & AgenticFlict")
    aidev_dir = paths.scratch_dir / "aidev"
    f_repo = aidev_dir / "repository.parquet"
    f_pr = aidev_dir / "pull_request.parquet"
    f_rev = aidev_dir / "pr_reviews.parquet"
    f_comm = aidev_dir / "pr_comments.parquet"
    f_rc2 = aidev_dir / "pr_review_comments_v2.parquet"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"
    f_cr_pr = paths.scratch_dir / "coderabbit" / "pull_requests.parquet"
    f_cr_repo = paths.scratch_dir / "coderabbit" / "repositories.parquet"
    f_af_files = paths.scratch_dir / "agenticflict" / "data" / "clean" / "agenticflict_conflict_files_clean.csv"

    hs_expr = "COALESCE(s.pre_pr_30d_hotspot_fixes, 0)" if has_hotspot else "NULL::BIGINT"
    surv14_expr = "s.file_survival_14d_pct" if has_surv14 else "NULL::DOUBLE"
    surv30_all_expr = "s.file_survival_30d_all_commits_pct" if has_surv30_all else "NULL::DOUBLE"
    bot_sql = sql_in_list(TIER1_REVIEW_BOTS)
    bot_comm_sql = sql_in_list(TIER1_PR_COMMENTS_BOTS)

    lang_rows = con.execute(f"""
        WITH bot_events AS (
            SELECT pr_id, "user" AS bot_user
            FROM read_parquet('{f_rev.as_posix()}')
            WHERE "user" IN ({bot_sql})
            UNION
            SELECT pr_id, "user" AS bot_user
            FROM read_parquet('{f_comm.as_posix()}')
            WHERE "user" IN ({bot_comm_sql})
            UNION
            SELECT rv.pr_id, rc."user" AS bot_user
            FROM read_parquet('{f_rc2.as_posix()}') rc
            JOIN read_parquet('{f_rev.as_posix()}') rv
              ON rc.pull_request_review_id = rv.id
            WHERE rc."user" IN ({bot_sql})
              AND COALESCE(rv."user", '') != 'copilot-swe-agent[bot]'
        ),
        bot_prs AS (
            SELECT pr_id, string_agg(DISTINCT bot_user, ';' ORDER BY bot_user) AS bot_list
            FROM bot_events
            GROUP BY pr_id
        )
        SELECT
            s.corpus,
            COALESCE(r.language, 'Unknown') AS language,
            s.szz_bugfix_14d,
            s.szz_bugfix_30d,
            {surv14_expr} AS surv14,
            s.file_survival_30d_pct AS surv30,
            {surv30_all_expr} AS surv30_all,
            {hs_expr} AS pre_hotspot,
            COALESCE(bp.bot_list, '') AS tier1_bots_list
        FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
        LEFT JOIN read_parquet('{f_repo.as_posix()}') r
          ON LOWER(s.repo_full_name) = LOWER(r.full_name)
        LEFT JOIN read_parquet('{f_pr.as_posix()}') pr
          ON s.corpus = 'AIDev'
         AND pr.repo_id = r.id
         AND pr.number = s.pr_number
        LEFT JOIN bot_prs bp
          ON pr.id = bp.pr_id
        WHERE s.corpus IN ('AIDev', 'AIDev_HumanBaseline')
          AND s.uncensored_30d = 1
    """).fetchall()

    # Aggregate by (panel, corpus, group_key)
    regime_agg: dict[tuple[str, str], list[tuple[Any, ...]]] = defaultdict(list)
    lang_agg: dict[tuple[str, str], list[tuple[Any, ...]]] = defaultdict(list)
    brain_agg: dict[tuple[str, str, str], list[tuple[Any, ...]]] = defaultdict(list)
    lang_counts: Counter = Counter()

    for corp, lang, b14, b30, sv14, sv30, sv30_all, pre_hs, bots_str in lang_rows:
        reg = _map_language_regime(lang)
        item = (b14, b30, sv14, sv30, sv30_all, pre_hs)
        regime_agg[(corp, reg)].append(item)
        lang_agg[(corp, lang)].append(item)
        lang_counts[lang] += 1
        if corp == "AIDev":
            bots = [b.strip() for b in (bots_str or "").split(";") if b.strip()]
            brain = min(classify_bot_brain_family(b) for b in bots) if bots else "0_No_Tier1_Bot"
            brain_agg[(corp, reg, brain)].append(item)

    top10_langs = [l for l, _ in lang_counts.most_common(10) if l != "Unknown"][:10]
    csv_rows: list[dict[str, Any]] = []

    def _summarize(panel: str, corp: str, key: str, items: list[tuple[Any, ...]]) -> dict[str, Any]:
        n = len(items)
        b14 = sum(int(x[0]) for x in items)
        b30 = sum(int(x[1]) for x in items)
        sv14_vals = [float(x[2]) for x in items if x[2] is not None]
        sv30_vals = [float(x[3]) for x in items if x[3] is not None]
        sv30_all_vals = [float(x[4]) for x in items if x[4] is not None]
        turn14 = round(100.0 - float(np.mean(sv14_vals)), 2) if sv14_vals else None
        bugfix_churn30 = round(100.0 - float(np.mean(sv30_vals)), 2) if sv30_vals else None
        turn30_all = round(100.0 - float(np.mean(sv30_all_vals)), 2) if sv30_all_vals else None
        cold_items = [x for x in items if x[5] is not None and int(x[5]) == 0]
        cold_b30 = sum(int(x[1]) for x in cold_items)
        ci30 = _wilson_pct(b30, n)
        return {
            "panel": panel,
            "corpus": corp,
            "group_key": key,
            "n": n,
            "szz_14d_pct": _safe_rate(b14, n),
            "szz_30d_pct": _safe_rate(b30, n),
            "szz_30d_ci95_low": ci30[0],
            "szz_30d_ci95_high": ci30[1],
            "turnover_14d_pct": turn14 if turn14 is not None else "",
            "turnover_30d_all_commits_pct": turn30_all if turn30_all is not None else "",
            "bugfix_file_churn_30d_pct": bugfix_churn30 if bugfix_churn30 is not None else "",
            "cold_file_szz_30d_pct": _safe_rate(cold_b30, len(cold_items)) if has_hotspot and cold_items else "",
        }

    regime_summary = []
    for (corp, reg), items in sorted(regime_agg.items()):
        rec = _summarize("Language_Regime", corp, reg, items)
        regime_summary.append(rec)
        csv_rows.append(rec)

    top_lang_summary = []
    for corp in ("AIDev", "AIDev_HumanBaseline"):
        for lang in top10_langs:
            items = lang_agg.get((corp, lang), [])
            if items:
                rec = _summarize("Top10_Language", corp, lang, items)
                top_lang_summary.append(rec)
                csv_rows.append(rec)

    brain_summary = []
    for (corp, reg, brain), items in sorted(brain_agg.items()):
        if len(items) >= 5:
            rec = _summarize("Regime_x_BotBrain", corp, f"{reg}::{brain}", items)
            brain_summary.append(rec)
            csv_rows.append(rec)

    # CodeRabbit labels by language & YAML profile
    cr_label_by_lang: list[dict[str, Any]] = []
    cr_label_by_profile: list[dict[str, Any]] = []
    if f_cr_pr.exists() and f_cr_repo.exists():
        con.execute("DROP TABLE IF EXISTS _tmp_nq07_cr_prof")
        con.execute("CREATE TEMP TABLE _tmp_nq07_cr_prof (repo_l VARCHAR, profile VARCHAR)")
        if cr_profiles:
            con.executemany("INSERT INTO _tmp_nq07_cr_prof VALUES (?, ?)", list(cr_profiles.items()))

        for r in con.execute(f"""
            WITH base AS (
                SELECT
                    COALESCE(r.language, 'Unknown') AS language,
                    COALESCE(cp.profile, 'unparsed') AS profile,
                    LOWER(array_to_string(COALESCE(p.labels, []::VARCHAR[]), ',')) AS lbl_str
                FROM read_parquet('{f_cr_pr.as_posix()}') p
                LEFT JOIN read_parquet('{f_cr_repo.as_posix()}') r ON p.repo_id = r.repo_id
                LEFT JOIN _tmp_nq07_cr_prof cp ON LOWER(p.repo) = cp.repo_l
            )
            SELECT
                language,
                COUNT(*) AS prs,
                SUM(CASE WHEN lbl_str LIKE '%bug%' THEN 1 ELSE 0 END) AS bug_lbl,
                SUM(CASE WHEN lbl_str LIKE '%regression%' THEN 1 ELSE 0 END) AS reg_lbl,
                SUM(CASE WHEN lbl_str LIKE '%security%' THEN 1 ELSE 0 END) AS sec_lbl
            FROM base
            GROUP BY 1
            ORDER BY prs DESC
            LIMIT 12
        """).fetchall():
            n = int(r[1])
            cr_label_by_lang.append({
                "language": r[0],
                "prs": n,
                "bug_label_pct": _safe_rate(int(r[2]), n),
                "regression_label_pct": _safe_rate(int(r[3]), n),
                "security_label_pct": _safe_rate(int(r[4]), n),
            })

        for r in con.execute(f"""
            WITH base AS (
                SELECT
                    COALESCE(cp.profile, 'unparsed') AS profile,
                    LOWER(array_to_string(COALESCE(p.labels, []::VARCHAR[]), ',')) AS lbl_str
                FROM read_parquet('{f_cr_pr.as_posix()}') p
                JOIN _tmp_nq07_cr_prof cp ON LOWER(p.repo) = cp.repo_l
            )
            SELECT
                profile,
                COUNT(*) AS prs,
                SUM(CASE WHEN lbl_str LIKE '%bug%' THEN 1 ELSE 0 END) AS bug_lbl,
                SUM(CASE WHEN lbl_str LIKE '%regression%' THEN 1 ELSE 0 END) AS reg_lbl,
                SUM(CASE WHEN lbl_str LIKE '%security%' THEN 1 ELSE 0 END) AS sec_lbl
            FROM base
            GROUP BY 1
            ORDER BY prs DESC
        """).fetchall():
            n = int(r[1])
            cr_label_by_profile.append({
                "profile": r[0],
                "prs": n,
                "bug_label_pct": _safe_rate(int(r[2]), n),
                "regression_label_pct": _safe_rate(int(r[3]), n),
                "security_label_pct": _safe_rate(int(r[4]), n),
            })
        con.execute("DROP TABLE IF EXISTS _tmp_nq07_cr_prof")

    # AgenticFlict conflict types by language extension
    af_ext_summary: list[dict[str, Any]] = []
    if f_af_files.exists():
        for r in con.execute(f"""
            SELECT
                CASE
                    WHEN LOWER(file_ext) IN ('.py') THEN 'Python (.py)'
                    WHEN LOWER(file_ext) IN ('.ts', '.tsx') THEN 'TypeScript (.ts/.tsx)'
                    WHEN LOWER(file_ext) IN ('.js', '.jsx') THEN 'JavaScript (.js/.jsx)'
                    WHEN LOWER(file_ext) IN ('.go') THEN 'Go (.go)'
                    WHEN LOWER(file_ext) IN ('.rs') THEN 'Rust (.rs)'
                    WHEN LOWER(file_ext) IN ('.java') THEN 'Java (.java)'
                    WHEN LOWER(file_ext) IN ('.cs') THEN 'C# (.cs)'
                    WHEN LOWER(file_ext) IN ('.c', '.cpp', '.cc', '.h', '.hpp') THEN 'C/C++'
                    WHEN LOWER(file_ext) IN ('.rb') THEN 'Ruby (.rb)'
                    ELSE 'Other'
                END AS lang_ext,
                COUNT(*) AS total_conflict_files,
                SUM(CASE WHEN conflict_type = 'both_modified' THEN 1 ELSE 0 END) AS both_modified,
                SUM(CASE WHEN conflict_type IN ('deleted_by_us', 'deleted_by_them') THEN 1 ELSE 0 END) AS delete_conflicts,
                SUM(CASE WHEN conflict_type IN ('added_by_us', 'added_by_them', 'both_added') THEN 1 ELSE 0 END) AS add_conflicts,
                ROUND(AVG(conflict_lines_in_file), 2) AS mean_conflict_lines
            FROM read_csv_auto('{f_af_files.as_posix()}', quote='"', escape='"', header=true)
            GROUP BY 1
            ORDER BY total_conflict_files DESC
        """).fetchall():
            af_ext_summary.append({
                "lang_ext": r[0],
                "total_conflict_files": int(r[1]),
                "both_modified": int(r[2]),
                "delete_conflicts": int(r[3]),
                "add_conflicts": int(r[4]),
                "mean_conflict_lines": float(r[5]) if r[5] is not None else None,
            })

    _write_csv(
        paths.tables_dir / "nq07_language_turnover_szz_log.csv",
        [
            "panel", "corpus", "group_key", "n", "szz_14d_pct", "szz_30d_pct",
            "szz_30d_ci95_low", "szz_30d_ci95_high", "turnover_14d_pct",
            "turnover_30d_all_commits_pct", "bugfix_file_churn_30d_pct",
            "cold_file_szz_30d_pct",
        ],
        csv_rows,
    )

    return {
        "language_regime_szz_and_turnover": regime_summary,
        "top10_languages_szz_and_turnover": top_lang_summary,
        "regime_x_bot_brain": brain_summary,
        "coderabbit_labels_by_language": cr_label_by_lang,
        "coderabbit_labels_by_profile": cr_label_by_profile,
        "agenticflict_conflict_types_by_ext": af_ext_summary,
    }, csv_rows


def _compute_nq08(
    con: duckdb.DuckDBPyConnection,
    paths: PathConfig,
    cr_profiles: dict[str, str],
    log: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log.info("NQ-08: Computing Acute Reviewer Queue Burstiness, Maintainer Tenure & 60-Day CodeRabbit Fatigue")
    aidev_dir = paths.scratch_dir / "aidev"
    f_rev = aidev_dir / "pr_reviews.parquet"
    f_pr = aidev_dir / "pull_request.parquet"
    f_repo = aidev_dir / "repository.parquet"
    f_user = aidev_dir / "user.parquet"
    f_auser = aidev_dir / "aidev_all_user.parquet"
    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"
    f_cr_pr = paths.scratch_dir / "coderabbit" / "pull_requests.parquet"

    human_rev_sql = _human_user_sql('"user"')
    if f_auser.exists():
        user_meta_union_sql = f"""
            SELECT login, followers, created_at FROM read_parquet('{f_user.as_posix()}')
            UNION ALL
            SELECT login, followers, created_at FROM read_parquet('{f_auser.as_posix()}')
        """
    else:
        log.warning("Optional aidev_all_user.parquet absent (%s); using user.parquet only.", f_auser)
        user_meta_union_sql = f"SELECT login, followers, created_at FROM read_parquet('{f_user.as_posix()}')"

    rev_rows = con.execute(f"""
        WITH user_meta AS (
            SELECT login, MAX(followers) AS followers, MIN(TRY_CAST(created_at AS TIMESTAMPTZ)) AS acct_created
            FROM (
                {user_meta_union_sql}
            ) u
            GROUP BY 1
        )
        SELECT
            r.id AS review_id,
            r.pr_id,
            r."user" AS reviewer,
            r.state,
            EPOCH(TRY_CAST(r.submitted_at AS TIMESTAMPTZ)) AS sub_epoch,
            LENGTH(TRIM(COALESCE(r.body, ''))) AS body_chars,
            um.followers,
            EPOCH(um.acct_created) AS acct_epoch
        FROM read_parquet('{f_rev.as_posix()}') r
        LEFT JOIN user_meta um ON r."user" = um.login
        WHERE r.user_type = 'User'
          AND {human_rev_sql.replace('"user"', 'r."user"')}
          AND TRY_CAST(r.submitted_at AS TIMESTAMPTZ) IS NOT NULL
        ORDER BY r."user", sub_epoch
    """).fetchall()

    # Sliding two-pointer queue burstiness per reviewer (strictly prior 24h & prior 7d)
    by_user: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rev_rows:
        by_user[str(row[2])].append(row)

    reviewer_total_counts = [float(len(v)) for v in by_user.values()]
    workload_gini = round(gini_coefficient(reviewer_total_counts), 4)

    enriched_revs: list[tuple[Any, ...]] = []
    pr_max_24h_load: dict[int, int] = {}
    for _user, items in by_user.items():
        items.sort(key=lambda x: float(x[4]))
        p24 = 0
        p7d = 0
        for idx, it in enumerate(items):
            ts = float(it[4])
            while p24 < idx and ts - float(items[p24][4]) > 86400.0:
                p24 += 1
            while p7d < idx and ts - float(items[p7d][4]) > 604800.0:
                p7d += 1
            load_24h = (idx - p24) + 1  # inclusive of current review: 1, 2-4, 5+
            load_7d = (idx - p7d) + 1
            pr_id = int(it[1])
            if load_24h > pr_max_24h_load.get(pr_id, 0):
                pr_max_24h_load[pr_id] = load_24h
            tenure_yrs = (ts - float(it[7])) / (86400.0 * 365.25) if it[7] is not None else None
            enriched_revs.append((
                int(it[0]), pr_id, str(it[3]), int(it[5]),
                load_24h, load_7d,
                float(it[6]) if it[6] is not None else None,
                tenure_yrs,
            ))

    # Map PR SZZ 30d status
    szz_pr_map: dict[int, int] = {}
    for pr_id, b30 in con.execute(f"""
        SELECT p.id, s.szz_bugfix_30d
        FROM read_csv_auto('{f_szz.as_posix()}', header=true) s
        JOIN read_parquet('{f_repo.as_posix()}') r ON LOWER(s.repo_full_name) = LOWER(r.full_name)
        JOIN read_parquet('{f_pr.as_posix()}') p ON p.repo_id = r.id AND p.number = s.pr_number
        WHERE s.corpus = 'AIDev' AND s.uncensored_30d = 1
    """).fetchall():
        szz_pr_map[int(pr_id)] = int(b30)

    burst_buckets: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    tenure_buckets: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    pr_burst_szz: dict[str, list[int]] = defaultdict(list)

    for _rid, pr_id, state, bchars, l24, _l7, followers, ten_yrs in enriched_revs:
        bk = "1_Low (1/24h)" if l24 == 1 else ("2_Medium (2-4/24h)" if l24 <= 4 else "3_High (5+/24h)")
        burst_buckets[bk].append((state, bchars, l24))
        if ten_yrs is not None:
            tb = "<2y_Tenure" if ten_yrs < 2.0 else ("2-6y_Tenure" if ten_yrs < 6.0 else "6y+_Veteran")
            tenure_buckets[tb].append((state, bchars, l24))

    for pr_id, b30 in szz_pr_map.items():
        if pr_id in pr_max_24h_load:
            l24 = pr_max_24h_load[pr_id]
            bk = "1_Low (1/24h)" if l24 == 1 else ("2_Medium (2-4/24h)" if l24 <= 4 else "3_High (5+/24h)")
            pr_burst_szz[bk].append(b30)

    csv_rows: list[dict[str, Any]] = []
    burst_summary: list[dict[str, Any]] = []
    for bk in sorted(burst_buckets.keys()):
        items = burst_buckets[bk]
        n = len(items)
        cr_k = sum(1 for st, _, _ in items if st == "CHANGES_REQUESTED")
        app_k = sum(1 for st, _, _ in items if st == "APPROVED")
        rs_k = sum(1 for st, bc, _ in items if st == "APPROVED" and bc <= 20)
        szz_vals = pr_burst_szz.get(bk, [])
        szz_n = len(szz_vals)
        szz_k = sum(szz_vals)
        rec = {
            "panel": "Reviewer_Queue_Burst_24h",
            "stratum": bk,
            "n_reviews_or_prs": n,
            "n_repos": "",
            "cr_veto_pct": _safe_rate(cr_k, n),
            "approval_pct": _safe_rate(app_k, n),
            "rubber_stamp_pct": _safe_rate(rs_k, n),
            "mean_body_chars": round(float(np.mean([bc for _, bc, _ in items])), 1),
            "szz_30d_pct": _safe_rate(szz_k, szz_n) if szz_n > 0 else "",
            "mean_comments_per_pr": "",
            "zero_comment_pct": "",
            "median_close_hours": "",
            "bug_label_pct": "",
        }
        burst_summary.append({**rec, "szz_n": szz_n, "szz_k": szz_k, "_cr_k": cr_k, "_rs_k": rs_k, "_n": n})
        csv_rows.append(rec)

    tenure_summary = []
    for tb in sorted(tenure_buckets.keys()):
        items = tenure_buckets[tb]
        n = len(items)
        cr_k = sum(1 for st, _, _ in items if st == "CHANGES_REQUESTED")
        rs_k = sum(1 for st, bc, _ in items if st == "APPROVED" and bc <= 20)
        tenure_summary.append({
            "tenure_bucket": tb,
            "n_reviews": n,
            "cr_veto_pct": _safe_rate(cr_k, n),
            "rubber_stamp_pct": _safe_rate(rs_k, n),
            "mean_body_chars": round(float(np.mean([bc for _, bc, _ in items])), 1),
        })

    # Part 8B: CodeRabbit 60-day longitudinal alert-fatigue curve
    cr_cols = {
        str(r[0])
        for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f_cr_pr.as_posix()}')").fetchall()
    }
    has_cr_merged = ("merged_at" in cr_cols) or ("merged" in cr_cols)

    con.execute("DROP TABLE IF EXISTS _tmp_nq08_cr_prof")
    con.execute("CREATE TEMP TABLE _tmp_nq08_cr_prof (repo_l VARCHAR, profile VARCHAR)")
    if cr_profiles:
        con.executemany("INSERT INTO _tmp_nq08_cr_prof VALUES (?, ?)", list(cr_profiles.items()))

    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_nq08_cr AS
        WITH repo_first AS (
            SELECT LOWER(repo) AS repo_l, MIN(TRY_CAST(created_at AS TIMESTAMPTZ)) AS first_ts
            FROM read_parquet('{f_cr_pr.as_posix()}')
            GROUP BY 1
        ),
        base AS (
            SELECT
                LOWER(p.repo) AS repo_l,
                COALESCE(cp.profile, 'unparsed') AS profile,
                p.number_comments,
                DATE_DIFF('second', rf.first_ts, TRY_CAST(p.created_at AS TIMESTAMPTZ)) / 86400.0 AS days_since_adopt,
                DATE_DIFF('second', TRY_CAST(p.created_at AS TIMESTAMPTZ), TRY_CAST(p.closed_at AS TIMESTAMPTZ)) / 3600.0 AS close_hours,
                CASE WHEN LOWER(array_to_string(COALESCE(p.labels, []::VARCHAR[]), ',')) LIKE '%bug%' THEN 1 ELSE 0 END AS is_bug_lbl
            FROM read_parquet('{f_cr_pr.as_posix()}') p
            JOIN repo_first rf ON LOWER(p.repo) = rf.repo_l
            LEFT JOIN _tmp_nq08_cr_prof cp ON LOWER(p.repo) = cp.repo_l
        )
        SELECT
            *,
            CASE
                WHEN days_since_adopt <= 15.0 THEN '1_Days_0_15'
                WHEN days_since_adopt <= 30.0 THEN '2_Days_16_30'
                WHEN days_since_adopt <= 60.0 THEN '3_Days_31_60'
                WHEN days_since_adopt <= 180.0 THEN '4_Days_61_180'
                ELSE '5_Days_181_Plus'
            END AS tenure_bucket
        FROM base
    """)

    cr_overall_rows = con.execute("""
        SELECT
            tenure_bucket,
            COUNT(*) AS prs,
            COUNT(DISTINCT repo_l) AS repos,
            ROUND(AVG(number_comments), 3) AS mean_comm,
            ROUND(MEDIAN(number_comments), 1) AS med_comm,
            ROUND(100.0 * AVG(CASE WHEN number_comments = 0 THEN 1.0 ELSE 0.0 END), 2) AS zero_comm_pct,
            ROUND(MEDIAN(CASE WHEN close_hours >= 0 THEN close_hours END), 2) AS med_close_hrs,
            ROUND(100.0 * AVG(is_bug_lbl), 2) AS bug_lbl_pct
        FROM v_nq08_cr
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    cr_profile_rows = con.execute("""
        SELECT
            profile,
            tenure_bucket,
            COUNT(*) AS prs,
            COUNT(DISTINCT repo_l) AS repos,
            ROUND(AVG(number_comments), 3) AS mean_comm,
            ROUND(100.0 * AVG(CASE WHEN number_comments = 0 THEN 1.0 ELSE 0.0 END), 2) AS zero_comm_pct,
            ROUND(MEDIAN(CASE WHEN close_hours >= 0 THEN close_hours END), 2) AS med_close_hrs,
            ROUND(100.0 * AVG(is_bug_lbl), 2) AS bug_lbl_pct
        FROM v_nq08_cr
        WHERE profile IN ('chill', 'default', 'assertive')
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).fetchall()

    # Fixed-cohort sensitivity check: repos active in BOTH Days_0_15 AND Days_61_180
    cr_fixed_cohort_rows = con.execute("""
        WITH mature_repos AS (
            SELECT repo_l
            FROM v_nq08_cr
            GROUP BY 1
            HAVING SUM(CASE WHEN tenure_bucket = '1_Days_0_15' THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN tenure_bucket = '4_Days_61_180' THEN 1 ELSE 0 END) > 0
        )
        SELECT
            tenure_bucket,
            COUNT(*) AS prs,
            COUNT(DISTINCT repo_l) AS repos,
            ROUND(AVG(number_comments), 3) AS mean_comm,
            ROUND(100.0 * AVG(CASE WHEN number_comments = 0 THEN 1.0 ELSE 0.0 END), 2) AS zero_comm_pct,
            ROUND(MEDIAN(CASE WHEN close_hours >= 0 THEN close_hours END), 2) AS med_close_hrs
        FROM v_nq08_cr
        WHERE repo_l IN (SELECT repo_l FROM mature_repos)
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    cr_fatigue_overall = []
    for r in cr_overall_rows:
        rec = {
            "panel": "CodeRabbit_Tenure_Overall",
            "stratum": r[0],
            "n_reviews_or_prs": int(r[1]),
            "n_repos": int(r[2]),
            "cr_veto_pct": "",
            "approval_pct": "",
            "rubber_stamp_pct": "",
            "mean_body_chars": "",
            "szz_30d_pct": "",
            "mean_comments_per_pr": float(r[3]),
            "zero_comment_pct": float(r[5]),
            "median_close_hours": float(r[6]) if r[6] is not None else "",
            "bug_label_pct": float(r[7]),
        }
        cr_fatigue_overall.append({**rec, "median_comments_per_pr": float(r[4]), "merge_rate_pct": None})
        csv_rows.append(rec)

    cr_fatigue_by_profile = []
    for r in cr_profile_rows:
        rec = {
            "panel": f"CodeRabbit_Profile::{r[0]}",
            "stratum": r[1],
            "n_reviews_or_prs": int(r[2]),
            "n_repos": int(r[3]),
            "cr_veto_pct": "",
            "approval_pct": "",
            "rubber_stamp_pct": "",
            "mean_body_chars": "",
            "szz_30d_pct": "",
            "mean_comments_per_pr": float(r[4]),
            "zero_comment_pct": float(r[5]),
            "median_close_hours": float(r[6]) if r[6] is not None else "",
            "bug_label_pct": float(r[7]),
        }
        cr_fatigue_by_profile.append({**rec, "profile": r[0], "merge_rate_pct": None})
        csv_rows.append(rec)

    _write_csv(
        paths.tables_dir / "nq08_queue_burst_and_fatigue_log.csv",
        [
            "panel", "stratum", "n_reviews_or_prs", "n_repos", "cr_veto_pct",
            "approval_pct", "rubber_stamp_pct", "mean_body_chars", "szz_30d_pct",
            "mean_comments_per_pr", "zero_comment_pct", "median_close_hours",
            "bug_label_pct",
        ],
        csv_rows,
    )

    bmap = {x["stratum"]: x for x in burst_summary}
    burst_tests: dict[str, Any] = {}
    if "1_Low (1/24h)" in bmap and "3_High (5+/24h)" in bmap:
        lo, hi = bmap["1_Low (1/24h)"], bmap["3_High (5+/24h)"]
        burst_tests["low_vs_high_burst_cr_veto"] = two_prop_z_test(lo["_cr_k"], lo["_n"], hi["_cr_k"], hi["_n"])
        burst_tests["low_vs_high_burst_rubber_stamp"] = two_prop_z_test(lo["_rs_k"], lo["_n"], hi["_rs_k"], hi["_n"])
        if lo["szz_n"] > 0 and hi["szz_n"] > 0:
            burst_tests["low_vs_high_burst_szz30"] = two_prop_z_test(lo["szz_k"], lo["szz_n"], hi["szz_k"], hi["szz_n"])

    con.execute("DROP TABLE IF EXISTS _tmp_nq08_cr_prof")
    return {
        "reviewer_workload_gini": workload_gini,
        "distinct_human_reviewers": len(by_user),
        "queue_burst_24h_summary": [
            {k: v for k, v in x.items() if not k.startswith("_")}
            for x in burst_summary
        ],
        "maintainer_tenure_summary": tenure_summary,
        "burst_statistical_tests": burst_tests,
        "coderabbit_schema_has_merged_status": has_cr_merged,
        "coderabbit_merge_rate_disclosure": (
            "computed" if has_cr_merged
            else "merge_status_absent_in_zenodo_schema (all 99,454 PRs state='closed'; merge_rate_pct=None)"
        ),
        "coderabbit_tenure_overall": cr_fatigue_overall,
        "coderabbit_tenure_by_profile": cr_fatigue_by_profile,
        "coderabbit_fixed_cohort_sensitivity": [
            {
                "tenure_bucket": r[0],
                "prs": int(r[1]),
                "repos": int(r[2]),
                "mean_comments_per_pr": float(r[3]),
                "zero_comment_pct": float(r[4]),
                "median_close_hours": float(r[5]) if r[5] is not None else None,
            }
            for r in cr_fixed_cohort_rows
        ],
    }, csv_rows


def run_p17(paths: PathConfig | None = None) -> dict[str, Any]:
    paths = paths or get_paths()
    paths.ensure_dirs()
    log, ts_log_path = setup_verbose_logger(
        "p17_open_questions_nq01_nq08",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )

    p16_json = paths.results_dir / "jev_judgment_and_szz_outcomes.json"
    if p16_json.exists():
        log.info("Ingesting NQ-01 & NQ-02 from %s", p16_json)
        p16_res = json.loads(p16_json.read_text(encoding="utf-8"))
    else:
        log.info("p16 output missing (%s); running p16 first...", p16_json)
        p16_res = run_p16(paths)

    f_szz = paths.tables_dir / "szz_defect_traceability_ledger.csv"
    if not f_szz.exists():
        raise FileNotFoundError(f"Required SZZ ledger missing: {f_szz}")

    con = duckdb.connect()
    szz_cols = {
        str(r[0])
        for r in con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{f_szz.as_posix()}', header=true)").fetchall()
    }
    has_hotspot = {"pre_pr_30d_hotspot_fixes", "pre_pr_30d_hotspot_commits"}.issubset(szz_cols)
    has_surv14 = "file_survival_14d_pct" in szz_cols
    has_surv30_all = "file_survival_30d_all_commits_pct" in szz_cols
    log.info("SZZ schema: has_hotspot=%s | has_surv14=%s | has_surv30_all=%s", has_hotspot, has_surv14, has_surv30_all)

    cr_profiles = _parse_coderabbit_profiles(paths.scratch_dir / "coderabbit" / "coderabbit_configuration_files.zip")
    log.info("Parsed %d .coderabbit.yaml repository profiles", len(cr_profiles))

    nq03_res, _ = _compute_nq03(con, paths, has_hotspot, log)
    nq04_res, _ = _compute_nq04(con, paths, has_hotspot, log)
    nq05_res, _ = _compute_nq05(con, paths, log)
    nq06_res, _ = _compute_nq06(con, paths, has_hotspot, log)
    nq07_res, _ = _compute_nq07(con, paths, has_hotspot, has_surv14, has_surv30_all, cr_profiles, log)
    nq08_res, _ = _compute_nq08(con, paths, cr_profiles, log)

    # BH-FDR across primary hypothesis tests in NQ-03..NQ-08
    raw_p: list[tuple[str, float]] = []
    for qtag, tdict in (
        ("nq03", nq03_res["statistical_tests"]),
        ("nq04", nq04_res["statistical_tests"]),
        ("nq05", nq05_res["statistical_tests"]),
        ("nq06_cross", nq06_res["cross_corpus_tests"]),
        ("nq06_full", nq06_res["full_szz_test_presence_tests"]),
        ("nq08", nq08_res["burst_statistical_tests"]),
    ):
        for k, v in tdict.items():
            if isinstance(v, dict) and v.get("p_value") is not None:
                raw_p.append((f"{qtag}::{k}", float(v["p_value"])))

    fdr_map = {}
    if raw_p:
        q_vals = bh_fdr([p for _, p in raw_p])
        fdr_map = {k: {"raw_p": round(p, 6), "bh_fdr_q": round(q, 6)} for (k, p), q in zip(raw_p, q_vals)}

    results: dict[str, Any] = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "szz_has_pre_pr_hotspot_cols": has_hotspot,
        "szz_has_file_survival_14d_pct": has_surv14,
        "szz_has_file_survival_30d_all_commits_pct": has_surv30_all,
        "nq01_jev_verbosity_and_human_judgment": p16_res.get("nq01_jev_verbosity_and_human_judgment", {}),
        "nq02_jev_bare_git_szz_outcomes": p16_res.get("nq02_jev_bare_git_szz_outcomes", {}),
        "nq03_pr_description_bloat": nq03_res,
        "nq04_pingpong_rework_szz": nq04_res,
        "nq05_review_speed_bimodality": nq05_res,
        "nq06_assertion_theater_szz": nq06_res,
        "nq07_language_turnover_szz": nq07_res,
        "nq08_queue_burst_and_fatigue": nq08_res,
        "bh_fdr_adjusted_p_values": fdr_map,
        "log_file": str(ts_log_path),
    }

    out_json = paths.results_dir / "open_questions_nq01_nq08_results.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Wrote JSON results -> %s", out_json)

    # Render Markdown synthesis report with mandatory Rule-0 YAML frontmatter
    md: list[str] = [
        yaml_frontmatter(
            title="Open Questions NQ-01 through NQ-08 Empirical Synthesis Report",
            intent="Comprehensive dynamic empirical synthesis of NQ-01..NQ-08 covering Jev tollgates, PR description bloat, ping-pong rework, fast LGTM bimodality, assertion theater, language turnover, and reviewer burstiness/fatigue.",
            doc_type="study-protocol",
            status="active",
            skills=["empirical-methodologist"],
        ).rstrip("\n"),
        "# Open Questions NQ-01 through NQ-08 Empirical Synthesis Report",
        "",
        f"**Generated (UTC):** `{results['generated_at_utc']}` | **Hotspot Control:** `{has_hotspot}` | **14d Survival:** `{has_surv14}`",
        "",
        "## NQ-01 & NQ-02: Jev Decision-Model Tollgates & Bare-Git SZZ",
        "- Ingested directly from `jev_judgment_and_szz_outcomes.json` (see `JEV_JUDGMENT_AND_SZZ_REPORT.md` for full regime and Mantel-Haenszel tables).",
        "",
        "## NQ-03: PR Description Bloat / Walkthrough Theater vs. Scrutiny & SZZ",
        "",
        "| Bucket | Scrutiny N | Human CR % | Rubber-Stamp % |",
        "| :--- | ---: | ---: | ---: |",
    ]
    for r in nq03_res["human_scrutiny_by_body_chars"]:
        md.append(f"| `{r['body_bucket']}` | {r['n']:,} | {r['human_cr_veto_pct']:.2f}% | {r['rubber_stamp_pct']:.2f}% |")

    md.extend([
        "",
        "## NQ-04: Review Ping-Pong Thrashing & Force-Push Rework vs. SZZ",
        f"- Total stratified records written to `nq04_pingpong_rework_szz_log.csv`: {len(nq04_res['strata_outcomes'])}.",
        "",
        "## NQ-05: Fast LGTM vs. Stalled Review Queue Bimodality & Bot-First Ordering",
        f"- Total `u30` human-reviewed AIDev PRs: **{nq05_res['total_u30_human_reviewed_prs']:,}** "
        f"(disclosed negative clock-skew PRs: open-to-review={nq05_res['disclosed_negative_open_to_review_skew_prs']}, "
        f"review-to-merge={nq05_res['disclosed_negative_review_to_merge_skew_prs']}).",
        "",
        "## NQ-06: Assertion Theater (Test Adaptedness vs. Real SZZ Bugfixes)",
        f"- Matched `AgenticPRs x SZZ u30` PRs: **{nq06_res['matched_agentic_prs_x_szz_u30_n']:,}**; full SZZ test-presence audit exported to `nq06_assertion_theater_szz_log.csv`.",
        "",
        "## NQ-07: Language-Regime Asymmetry & Code Turnover",
        "",
        "| Corpus | Language Regime | N | SZZ 14d % | SZZ 30d % | 14d Turnover % | 30d All-Commit Turnover % | 30d Bugfix File Churn % |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in nq07_res["language_regime_szz_and_turnover"]:
        t14 = f"{r['turnover_14d_pct']:.2f}%" if r["turnover_14d_pct"] != "" else "N/A"
        t30_all = f"{r['turnover_30d_all_commits_pct']:.2f}%" if r["turnover_30d_all_commits_pct"] != "" else "N/A"
        bf30 = f"{r['bugfix_file_churn_30d_pct']:.2f}%" if r["bugfix_file_churn_30d_pct"] != "" else "N/A"
        md.append(
            f"| `{r['corpus']}` | `{r['group_key']}` | {r['n']:,} | {r['szz_14d_pct']:.2f}% | {r['szz_30d_pct']:.2f}% | {t14} | {t30_all} | {bf30} |"
        )

    md.extend([
        "",
        "## NQ-08: Acute Reviewer Queue Burstiness & 60-Day CodeRabbit Fatigue",
        f"- Reviewer workload Gini coefficient across **{nq08_res['distinct_human_reviewers']:,}** human reviewers: **{nq08_res['reviewer_workload_gini']:.4f}**.",
        f"- CodeRabbit merge-rate disclosure: `{nq08_res['coderabbit_merge_rate_disclosure']}`.",
        "",
        "## Audit Tables Generated",
        "- `nq03_pr_description_bloat_log.csv`",
        "- `nq04_pingpong_rework_szz_log.csv`",
        "- `nq05_review_speed_bimodality_log.csv`",
        "- `nq06_assertion_theater_szz_log.csv`",
        "- `nq07_language_turnover_szz_log.csv`",
        "- `nq08_queue_burst_and_fatigue_log.csv`",
        "",
    ])

    out_md = paths.results_dir / "OPEN_QUESTIONS_NQ01_NQ08_REPORT.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    log.info("Wrote Markdown report -> %s", out_md)

    return results


def main() -> None:
    run_p17()


if __name__ == "__main__":
    main()
