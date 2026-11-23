#!/usr/bin/env python3
r"""
Step 0B: Local Bare-Git SZZ Defect Attribution, Pre-PR Hotspot & Architectural Constraint Miner
==============================================================================================
Executes purely local, zero-API git commit-graph and tree-object queries against bare git clones
in `paths.clones_dir` (and fallback `paths.scratch_dir / "jev_pr_reviews" / "_git_cache"`) using
`git -c diff.renames=false log --no-renames --first-parent --name-only` (guaranteed 0 blob
network fetches under `--filter=blob:none`, never invoking `--numstat`).

Outputs:
  1. `paths.tables_dir / "repo_architectural_constraints_ledger.csv"`
     Commit-dated detection of CODEOWNERS, deterministic SAST/typecheck CI workflows,
     agent boundary contracts (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `docs/adr/`),
     and composite `constraint_tier` (0..3).
  2. `paths.tables_dir / "szz_defect_traceability_ledger.csv"`
     PR-level post-merge defect attribution across fixed uncensored windows (14d, 30d, 60d, 90d),
     plus pre-merge hotspot & post-merge turnover controls:
       - `pre_pr_14d_hotspot_fixes`: bug-fix commits touching the PR's modified source files
         in the 14 days strictly before `merged_at` (`-14.0 <= delta_days < 0.0`, symmetric to `szz_bugfix_14d`).
       - `pre_pr_30d_hotspot_fixes`: bug-fix commits touching the PR's modified source files
         in the 30 days strictly before `merged_at` (`-30.0 <= delta_days < 0.0`).
       - `pre_pr_30d_hotspot_commits`: total commits touching the PR's modified source files
         in `-30.0 <= delta_days < 0.0`.
       - `file_survival_14d_pct`: percentage of the PR's modified source files untouched by
         ANY follow-up commit within 14 days (`0 < delta_days <= 14.0`, all-commit turnover survival).
       - `file_survival_30d_pct`: bugfix-only 30d survival (% of modified source files untouched
         by bug-fix commits or reverts within 30 days).
       - `file_survival_30d_all_commits_pct`: percentage of the PR's modified source files untouched by
         ANY follow-up commit in `0 < delta_days <= 30.0` (all-commit turnover survival, symmetric to `file_survival_14d_pct`).
       - `fix_induces_fix_k60d` / `k90d`, `days_to_first_szz_fix`, `days_to_first_revert`
         (file-level SZZ overlap via `--name-only`; coarser than line-level `git blame`).
  3. `paths.results_dir / "szz_and_constraints_summary.json"`
     Includes `by_corpus_and_topology_14d`, `by_corpus_and_topology_30d`,
     `aidev_by_constraint_tier_30d`, and `jev_within_repo_szz_14d_and_30d`
     (pooled + within-repository + hotspot-controlled contrasts across
     `Jev_Flagged`, `Jev_Clean`, `Prose_Bot_Control`, `No_Bot_Control`).
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PR_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
if str(PR_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(PR_ANALYSIS_ROOT))

from config.bot_catalog import (
    DETERMINISTIC_SAST_BOTS,
    EXCLUDED_AUTHOR_BOT_ACTORS,
    TIER1_PR_COMMENTS_BOTS,
    TIER1_REVIEW_BOTS,
    sql_in_list,
)
from config.paths import PathConfig, get_paths
from src.utils.logging_utils import setup_verbose_logger

PR_NUM_IN_SUBJECT_RE = re.compile(r"(?:\(#(\d+)\)|Merge pull request #(\d+))", re.I)
REVERT_PR_RE = re.compile(r"revert.*?(?:#(\d+)|([0-9a-f]{7,40}))", re.I)
BUGFIX_SUBJECT_RE = re.compile(
    r"\b(fix|fixes|fixed|bug|bugfix|regression|hotfix|crash|panic|race|deadlock|leak|cve|vuln)\b",
    re.I,
)
NON_BUG_EXCLUSION_RE = re.compile(
    r"\b(typo|docs|readme|comment|format|formatting|lint|style|chore|bump|deps|changelog)\b",
    re.I,
)

TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)/|(_test\.|\.test\.|\.spec\.|Test\.java|Tests\.cs)",
    re.I,
)
IAC_BOUNDARY_RE = re.compile(
    r"(^\.github/workflows/|Dockerfile|docker-compose|k8s/|helm/|terraform|\.tf$|serverless\.yml|AGENTS\.md|CLAUDE\.md)",
    re.I,
)
SAST_TOOL_RE = re.compile(
    r"\b(semgrep|ast-grep|codeql|sonar|sonarqube|golangci-lint|clippy|mypy|pyright|spotbugs|bandit|trivy|checkov)\b",
    re.I,
)


def _anonymous_git_env() -> Dict[str, str]:
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }


def parse_iso_ts(ts_str: str) -> Optional[datetime.datetime]:
    """Parse an ISO-8601 timestamp into UTC datetime."""
    if not ts_str:
        return None
    try:
        clean = ts_str.strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def inspect_repo_architectural_constraints(
    repo_full_name: str,
    bare_dir: Path,
    log: Any,
) -> Dict[str, Any]:
    """Scan bare git tree for CODEOWNERS, deterministic SAST workflows, and agent boundary contracts."""
    res: Dict[str, Any] = {
        "repo_full_name": repo_full_name,
        "has_codeowners": 0,
        "codeowners_first_commit_at": "",
        "has_deterministic_sast_workflow": 0,
        "sast_tools_detected": "",
        "has_agent_boundary_contract": 0,
        "agent_contract_files": "",
        "has_review_bot_config": 0,
        "workflow_files_count": 0,
        "constraint_tier": 0,
    }
    git_env = _anonymous_git_env()
    try:
        p = subprocess.run(
            ["git", "-C", str(bare_dir), "ls-tree", "-r", "HEAD", "--name-only"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=git_env,
        )
        if p.returncode != 0:
            return res
        files = [line.strip() for line in p.stdout.splitlines() if line.strip()]
        file_set = set(files)

        co_paths = [f for f in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS") if f in file_set]
        if co_paths:
            res["has_codeowners"] = 1
            p_co = subprocess.run(
                [
                    "git",
                    "-C",
                    str(bare_dir),
                    "log",
                    "--diff-filter=A",
                    "--format=%aI",
                    "-n",
                    "1",
                    "--",
                    co_paths[0],
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env=git_env,
            )
            res["codeowners_first_commit_at"] = (p_co.stdout or "").strip()

        contract_cands = [
            f
            for f in files
            if f in ("AGENTS.md", "CLAUDE.md", ".cursorrules", ".github/copilot-instructions.md", "ARCHITECTURE.md")
            or f.startswith(("docs/adr/", "adr/", ".agents/"))
        ]
        if contract_cands:
            res["has_agent_boundary_contract"] = 1
            res["agent_contract_files"] = ";".join(contract_cands[:6])

        bot_cfg = [
            f
            for f in files
            if f in (".coderabbit.yaml", "coderabbit.yaml", ".github/pr-risk.yml", ".github/jev.yml")
        ]
        if bot_cfg:
            res["has_review_bot_config"] = 1

        wf_files = [f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
        res["workflow_files_count"] = len(wf_files)
        sast_found: Set[str] = set()
        for wf in wf_files[:25]:
            for m in SAST_TOOL_RE.finditer(wf):
                sast_found.add(m.group(1).lower())
            p_wf = subprocess.run(
                ["git", "-C", str(bare_dir), "log", "-n", "5", "--format=%s %b", "--", wf],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env=git_env,
            )
            for m in SAST_TOOL_RE.finditer(p_wf.stdout or ""):
                sast_found.add(m.group(1).lower())

        if sast_found:
            res["has_deterministic_sast_workflow"] = 1
            res["sast_tools_detected"] = ";".join(sorted(sast_found))

        score = (
            (1 if res["workflow_files_count"] > 0 else 0)
            + (1 if (res["has_codeowners"] or res["has_deterministic_sast_workflow"]) else 0)
            + (
                1
                if (
                    res["has_codeowners"]
                    and (res["has_deterministic_sast_workflow"] or res["has_agent_boundary_contract"])
                )
                else 0
            )
        )
        res["constraint_tier"] = min(3, score)
    except Exception as exc:
        log.warning("Constraint scan error on %s: %s", repo_full_name, exc)
    return res


def extract_subject_pr_nums(subj: str, is_revert: bool) -> Set[int]:
    """
    Extract PR numbers strictly from commit subject `subj` (never `body`).
    When `is_revert` is True (e.g. `Revert "feat: foo (#401)" (#415)`), strip quoted
    text first so only the revert PR's own outer trailing PR number is extracted,
    never binding the reverted PR's number to the revert commit.
    """
    scan_text = subj
    if is_revert:
        scan_text = re.sub(r'^(revert\s+)"(.+)"(.*)$', r"\1 \3", scan_text, flags=re.I)
        scan_text = re.sub(r"^(revert\s+)'(.+)'(.*)$", r"\1 \3", scan_text, flags=re.I)
        scan_text = re.sub(r'"[^"]*"', " ", scan_text)
        scan_text = re.sub(r"(?:^|\s)'[^']*'", " ", scan_text)
    pr_nums: Set[int] = set()
    for m in PR_NUM_IN_SUBJECT_RE.finditer(scan_text):
        num_str = m.group(1) or m.group(2)
        if num_str:
            pr_nums.add(int(num_str))
    return pr_nums


def resolve_commit_index_for_pr(
    pr: Dict[str, Any],
    commits: List[Dict[str, Any]],
    pr_num_to_candidates: Dict[int, List[int]],
    sha_to_idx: Dict[str, int],
) -> Tuple[Optional[int], bool]:
    """
    Resolve commit index `c_idx` for a PR:
      1. First check `pr_shas` against `sha_to_idx`.
      2. Otherwise pick the non-revert candidate from `pr_num_to_candidates[pnum]`
         whose commit timestamp `dt` is closest to `parse_iso_ts(pr["merged_at"])`
         (preferring candidates within +/-7 days of `merged_at`, falling back to
         the earliest non-revert candidate).
    Returns `(c_idx, was_multi_candidate_disambiguated)`.
    """
    for psha in reversed(pr.get("pr_shas") or []):
        if psha in sha_to_idx:
            return sha_to_idx[psha], False

    pnum = int(pr["pr_number"])
    cands = pr_num_to_candidates.get(pnum, [])
    if not cands:
        return None, False
    if len(cands) == 1:
        return cands[0], False

    merged_dt = parse_iso_ts(str(pr.get("merged_at") or ""))
    if merged_dt is not None:
        within_7d = [
            idx
            for idx in cands
            if abs((commits[idx]["dt"] - merged_dt).total_seconds()) <= 7 * 86400
        ]
        if within_7d:
            best = min(
                within_7d,
                key=lambda idx: abs((commits[idx]["dt"] - merged_dt).total_seconds()),
            )
            return best, True
    # Fall back to earliest non-revert candidate (commits are sorted ascending by dt)
    return cands[0], True


def extract_repo_commit_history(bare_dir: Path, max_commits: int = 25000) -> List[Dict[str, Any]]:
    """
    Extract chronological mainline default-branch commits (since 2024-01-01) with modified
    file lists using `git -c diff.renames=false log --no-renames --first-parent --name-only`
    (pure tree-object query: 0 blob fetches under `--filter=blob:none`, never `--numstat`).
    """
    fmt = "__COMMIT__%H\x1f%aI\x1f%an%x1f%s\x1f%b__FILES__"
    git_env = _anonymous_git_env()
    p = subprocess.run(
        [
            "git",
            "-C",
            str(bare_dir),
            "-c",
            "diff.renames=false",
            "log",
            "--no-renames",
            "--first-parent",
            "--since=2024-01-01",
            "-n",
            str(max_commits),
            f"--format={fmt}",
            "--name-only",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=git_env,
    )
    if p.returncode != 0 or not p.stdout:
        p = subprocess.run(
            [
                "git",
                "-C",
                str(bare_dir),
                "-c",
                "diff.renames=false",
                "log",
                "--no-renames",
                "--first-parent",
                "-n",
                "6000",
                f"--format={fmt}",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=git_env,
        )
        if p.returncode != 0 or not p.stdout:
            return []

    commits: List[Dict[str, Any]] = []
    for ch in p.stdout.split("__COMMIT__"):
        ch = ch.strip()
        if not ch or "__FILES__" not in ch:
            continue
        header, files_blob = ch.split("__FILES__", 1)
        parts = header.split("\x1f")
        if len(parts) < 4:
            continue
        sha = parts[0].strip()
        ts_str = parts[1].strip()
        dt = parse_iso_ts(ts_str)
        if dt is None:
            continue
        author = parts[2].strip()
        subj = parts[3].strip()
        body = parts[4].strip() if len(parts) > 4 else ""
        files = [ln.strip() for ln in files_blob.splitlines() if ln.strip()]

        src_files = [f for f in files if not TEST_PATH_RE.search(f)]
        test_files = [f for f in files if TEST_PATH_RE.search(f)]
        iac_files = [f for f in files if IAC_BOUNDARY_RE.search(f)]

        is_revert = bool(re.search(r"\brevert\b", subj, re.I))
        pr_nums = extract_subject_pr_nums(subj, is_revert=is_revert)

        reverted_prs: Set[int] = set()
        reverted_shas: Set[str] = set()
        if is_revert:
            for m in REVERT_PR_RE.finditer(subj + " " + body):
                if m.group(1):
                    reverted_prs.add(int(m.group(1)))
                if m.group(2):
                    reverted_shas.add(m.group(2).lower())

        is_bugfix = bool(BUGFIX_SUBJECT_RE.search(subj)) and not bool(NON_BUG_EXCLUSION_RE.search(subj))

        commits.append(
            {
                "sha": sha,
                "dt": dt,
                "ts_iso": ts_str,
                "author": author,
                "subject": subj[:240],
                "files": files,
                "src_files": set(src_files),
                "test_files": set(test_files),
                "iac_files": set(iac_files),
                "pr_nums": pr_nums,
                "is_revert": is_revert,
                "reverted_prs": reverted_prs,
                "reverted_shas": reverted_shas,
                "is_bugfix": is_bugfix,
            }
        )

    commits.sort(key=lambda c: c["dt"])
    return commits


def load_target_merged_prs(paths: PathConfig, log: Any) -> Tuple[List[Dict[str, Any]], str]:
    """
    Load merged PR metadata from `paths.scratch_dir / "aidev"` and `Jev_Mined`.
    Prefers `paths.results_dir / "jev_bot_signals_reparsed.parquet"` if present,
    falling back to `paths.scratch_dir / "jev_pr_reviews" / "jev_bot_signals_and_comments.parquet"`.
    """
    import duckdb

    con = duckdb.connect()
    prs: List[Dict[str, Any]] = []

    aidev_dir = paths.scratch_dir / "aidev"
    aidev_pr_pq = aidev_dir / "pull_request.parquet"
    aidev_hpr_pq = aidev_dir / "human_pull_request.parquet"
    aidev_rev_pq = aidev_dir / "pr_reviews.parquet"
    aidev_comm_pq = aidev_dir / "pr_comments.parquet"
    aidev_v2_pq = aidev_dir / "pr_review_comments_v2.parquet"
    aidev_commits_pq = aidev_dir / "pr_commits.parquet"
    aidev_repo_pq = aidev_dir / "repository.parquet"
    aidev_task_pq = aidev_dir / "pr_task_type.parquet"
    aidev_htask_pq = aidev_dir / "human_pr_task_type.parquet"

    if aidev_pr_pq.exists() and aidev_rev_pq.exists() and aidev_repo_pq.exists():
        all_bot_sql = sql_in_list(TIER1_REVIEW_BOTS)
        comm_bot_sql = sql_in_list(TIER1_PR_COMMENTS_BOTS)
        sast_bot_sql = sql_in_list(DETERMINISTIC_SAST_BOTS)
        excl_sql = sql_in_list(EXCLUDED_AUTHOR_BOT_ACTORS)

        v2_union = ""
        if aidev_v2_pq.exists():
            v2_union = f"""
                UNION
                SELECT rv.pr_id, rc.user AS bot_user
                FROM read_parquet('{aidev_v2_pq}') rc
                JOIN read_parquet('{aidev_rev_pq}') rv ON rc.pull_request_review_id = rv.id
                WHERE rc.user IN ({all_bot_sql})
                  AND rv.user NOT IN ({excl_sql})
            """

        comm_union = ""
        if aidev_comm_pq.exists():
            comm_union = f"""
                UNION
                SELECT pr_id, user AS bot_user
                FROM read_parquet('{aidev_comm_pq}')
                WHERE user IN ({comm_bot_sql})
            """

        pr_shas_cte = ""
        pr_shas_join = ""
        pr_shas_col = "'' AS pr_shas"
        if aidev_commits_pq.exists():
            pr_shas_cte = f""",
            pr_commit_shas AS (
                SELECT pr_id, string_agg(sha, ';') AS pr_shas
                FROM read_parquet('{aidev_commits_pq}')
                WHERE sha IS NOT NULL
                GROUP BY pr_id
            )"""
            pr_shas_join = "LEFT JOIN pr_commit_shas pcs ON p.id = pcs.pr_id"
            pr_shas_col = "COALESCE(pcs.pr_shas, '') AS pr_shas"

        rows = con.execute(
            f"""
            WITH bot_events AS (
                SELECT pr_id, user AS bot_user
                FROM read_parquet('{aidev_rev_pq}')
                WHERE user IN ({all_bot_sql})
                  AND user NOT IN ({excl_sql})
                {comm_union}
                {v2_union}
            ),
            bot_agg AS (
                SELECT
                    pr_id,
                    COUNT(DISTINCT bot_user) AS total_bots,
                    MAX(CASE WHEN bot_user IN ({sast_bot_sql}) THEN 1 ELSE 0 END) AS has_sast_bot,
                    MAX(CASE WHEN bot_user NOT IN ({sast_bot_sql}) THEN 1 ELSE 0 END) AS has_prose_bot
                FROM bot_events
                GROUP BY pr_id
            ),
            human_agg AS (
                SELECT pr_id, COUNT(*) AS h_revs
                FROM read_parquet('{aidev_rev_pq}')
                WHERE user_type = 'User'
                  AND user NOT LIKE '%[bot]%'
                  AND LOWER(COALESCE(user, '')) NOT LIKE '%-bot'
                  AND user NOT IN ({excl_sql})
                GROUP BY pr_id
            )
            {pr_shas_cte}
            SELECT
                r.full_name AS repo_full_name,
                p.number AS pr_number,
                p.id AS pr_id,
                'Coding_Agent' AS author_origin,
                p.agent AS agent_name,
                p.merged_at,
                COALESCE(t.type, 'unknown') AS task_type,
                CASE
                    WHEN COALESCE(ba.has_sast_bot, 0) = 1 AND COALESCE(ba.has_prose_bot, 0) = 0 THEN 'Agent+DeterministicSAST'
                    WHEN COALESCE(ha.h_revs, 0) > 0 AND COALESCE(ba.total_bots, 0) > 0 THEN 'Agent+ProseBot+Human'
                    WHEN COALESCE(ha.h_revs, 0) > 0 AND COALESCE(ba.total_bots, 0) = 0 THEN 'Agent+HumanOnly'
                    WHEN COALESCE(ha.h_revs, 0) = 0 AND COALESCE(ba.total_bots, 0) > 0 THEN 'Agent+BotOnly'
                    ELSE 'Agent+SilentOrSelfMerge'
                END AS review_topology,
                {pr_shas_col}
            FROM read_parquet('{aidev_pr_pq}') p
            JOIN read_parquet('{aidev_repo_pq}') r ON p.repo_id = r.id
            LEFT JOIN human_agg ha ON p.id = ha.pr_id
            LEFT JOIN bot_agg ba ON p.id = ba.pr_id
            LEFT JOIN read_parquet('{aidev_task_pq}') t ON p.id = t.id
            {pr_shas_join}
            WHERE p.merged_at IS NOT NULL
            """
        ).fetchall()
        for r in rows:
            prs.append(
                {
                    "repo_full_name": str(r[0]),
                    "pr_number": int(r[1]),
                    "pr_id": str(r[2]),
                    "author_origin": str(r[3]),
                    "agent_name": str(r[4]),
                    "merged_at": str(r[5]),
                    "task_type": str(r[6]),
                    "review_topology": str(r[7]),
                    "pr_shas": [s for s in str(r[8]).split(";") if s],
                    "corpus": "AIDev",
                }
            )

        if aidev_hpr_pq.exists():
            htask_join = f"LEFT JOIN read_parquet('{aidev_htask_pq}') ht ON h.id = ht.id" if aidev_htask_pq.exists() else ""
            htask_col = "COALESCE(ht.type, 'unknown')" if aidev_htask_pq.exists() else "'unknown'"
            h_rows = con.execute(
                f"""
                SELECT
                    r.full_name AS repo_full_name,
                    h.number AS pr_number,
                    h.id AS pr_id,
                    h.user AS author_login,
                    h.merged_at,
                    {htask_col} AS task_type
                FROM read_parquet('{aidev_hpr_pq}') h
                JOIN read_parquet('{aidev_repo_pq}') r ON h.repo_url = r.url
                {htask_join}
                WHERE h.merged_at IS NOT NULL
                """
            ).fetchall()
            for hr in h_rows:
                prs.append(
                    {
                        "repo_full_name": str(hr[0]),
                        "pr_number": int(hr[1]),
                        "pr_id": f"human_{hr[2]}",
                        "author_origin": "Human_Engineer",
                        "agent_name": str(hr[3] or "human"),
                        "merged_at": str(hr[4]),
                        "task_type": str(hr[5]),
                        "review_topology": "Human_Baseline_Merged",
                        "pr_shas": [],
                        "corpus": "AIDev_HumanBaseline",
                    }
                )

    jev_pr_pq = paths.scratch_dir / "jev_pr_reviews" / "jev_pull_requests.parquet"
    reparsed_pq = paths.results_dir / "jev_bot_signals_reparsed.parquet"
    raw_jev_comm_pq = paths.scratch_dir / "jev_pr_reviews" / "jev_bot_signals_and_comments.parquet"
    jev_comm_pq = reparsed_pq if reparsed_pq.exists() else raw_jev_comm_pq
    jev_source_used = str(jev_comm_pq) if jev_comm_pq.exists() else ""

    if jev_pr_pq.exists() and jev_comm_pq.exists():
        log.info("Loading Jev_Mined signals from %s (reparsed=%s).", jev_comm_pq, reparsed_pq.exists())
        j_rows = con.execute(
            f"""
            WITH sig AS (
                SELECT
                    repo_full_name,
                    pr_number,
                    MAX(CASE WHEN is_jev_signal THEN 1 ELSE 0 END) AS has_jev,
                    MAX(CASE WHEN is_jev_signal AND alerts_count > 0 THEN 1 ELSE 0 END) AS jev_flagged,
                    MAX(CASE WHEN bot_family = 'prose_review_bot_control' THEN 1 ELSE 0 END) AS has_prose,
                    SUM(CASE WHEN bot_family = 'human_comment' THEN 1 ELSE 0 END) AS h_comms
                FROM read_parquet('{jev_comm_pq}')
                GROUP BY 1, 2
            )
            SELECT
                p.repo_full_name,
                p.pr_number,
                p.author_origin,
                p.author_login,
                p.merged_at,
                CASE
                    WHEN COALESCE(s.has_jev, 0) = 1 AND COALESCE(s.jev_flagged, 0) = 1 THEN 'Jev_Flagged'
                    WHEN COALESCE(s.has_jev, 0) = 1 AND COALESCE(s.jev_flagged, 0) = 0 THEN 'Jev_Clean'
                    WHEN COALESCE(s.has_prose, 0) = 1 THEN 'Prose_Bot_Control'
                    ELSE 'No_Bot_Control'
                END AS jev_gate
            FROM read_parquet('{jev_pr_pq}') p
            LEFT JOIN sig s ON p.repo_full_name = s.repo_full_name AND p.pr_number = s.pr_number
            WHERE p.is_merged AND p.merged_at IS NOT NULL AND p.merged_at != ''
            """
        ).fetchall()
        for r in j_rows:
            prs.append(
                {
                    "repo_full_name": str(r[0]),
                    "pr_number": int(r[1]),
                    "pr_id": f"jev_{r[0]}#{r[1]}",
                    "author_origin": str(r[2]),
                    "agent_name": str(r[3]),
                    "merged_at": str(r[4]),
                    "task_type": "unknown",
                    "review_topology": f"{r[2]}__{r[5]}",
                    "pr_shas": [],
                    "corpus": "Jev_Mined",
                }
            )

    return prs, jev_source_used


def process_single_cloned_repo(
    rname: str,
    bare_dir: Path,
    repo_prs: List[Dict[str, Any]],
    log: Any,
    stats: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Scan one bare git repository for architectural constraints, pre-PR hotspots, and SZZ outcomes."""
    c_meta = inspect_repo_architectural_constraints(rname, bare_dir, log)
    if not repo_prs:
        return c_meta, []

    commits = extract_repo_commit_history(bare_dir)
    if not commits:
        return c_meta, []
    max_repo_dt = commits[-1]["dt"]

    pr_num_to_candidates: Dict[int, List[int]] = defaultdict(list)
    sha_to_idx: Dict[str, int] = {}
    for idx, cm in enumerate(commits):
        sha_to_idx[cm["sha"]] = idx
        if not cm["is_revert"]:
            for pnum in cm["pr_nums"]:
                pr_num_to_candidates[pnum].append(idx)

    multi_cand_disambiguated = 0
    repo_szz_rows: List[Dict[str, Any]] = []
    for pr in repo_prs:
        pnum = pr["pr_number"]
        c_idx, was_disambiguated = resolve_commit_index_for_pr(
            pr=pr,
            commits=commits,
            pr_num_to_candidates=pr_num_to_candidates,
            sha_to_idx=sha_to_idx,
        )
        if was_disambiguated:
            multi_cand_disambiguated += 1
        if c_idx is None:
            continue

        target_cm = commits[c_idx]
        merged_dt = parse_iso_ts(pr["merged_at"]) or target_cm["dt"]
        src_files = target_cm["src_files"]
        src_cnt = len(src_files)

        uncensored_14d = int((max_repo_dt - merged_dt).total_seconds() >= 14 * 86400)
        uncensored_30d = int((max_repo_dt - merged_dt).total_seconds() >= 30 * 86400)
        uncensored_60d = int((max_repo_dt - merged_dt).total_seconds() >= 60 * 86400)
        uncensored_90d = int((max_repo_dt - merged_dt).total_seconds() >= 90 * 86400)

        # Pre-PR 14d & 30d hotspot baselines strictly before `merged_dt`:
        # -14.0 <= delta_days < 0.0 (symmetric to szz_bugfix_14d) and -30.0 <= delta_days < 0.0
        pre_pr_14d_hotspot_fixes = 0
        pre_pr_30d_hotspot_fixes = 0
        pre_pr_30d_hotspot_commits = 0
        if src_files:
            for pre_cm in reversed(commits[:c_idx]):
                pre_delta_days = (pre_cm["dt"] - merged_dt).total_seconds() / 86400.0
                if pre_delta_days >= 0.0:
                    continue
                if pre_delta_days < -30.0:
                    break
                if src_files & pre_cm["src_files"]:
                    pre_pr_30d_hotspot_commits += 1
                    if pre_cm["is_bugfix"]:
                        pre_pr_30d_hotspot_fixes += 1
                        if pre_delta_days >= -14.0:
                            pre_pr_14d_hotspot_fixes += 1

        rev_14d = rev_30d = rev_60d = rev_90d = 0
        szz_14d = szz_30d = szz_60d = szz_90d = 0
        fixing_shas_60d: List[str] = []
        fixing_shas_90d: List[str] = []
        days_to_first_revert: Optional[float] = None
        days_to_first_szz_fix: Optional[float] = None
        bugfixed_files_30d: Set[str] = set()
        touched_files_14d: Set[str] = set()
        touched_files_30d: Set[str] = set()

        for sub_cm in commits[c_idx + 1 :]:
            delta_days = (sub_cm["dt"] - merged_dt).total_seconds() / 86400.0
            if delta_days < 0.0:
                continue
            if delta_days > 90.0:
                break

            is_pr_revert = sub_cm["is_revert"] and (
                pnum in sub_cm["reverted_prs"]
                or any(target_cm["sha"].startswith(s) for s in sub_cm["reverted_shas"])
            )

            # Track 14-day & 30-day all-commit file-level code turnover (ANY follow-up commit touching src_files)
            if 0.0 < delta_days <= 30.0 and src_files:
                any_overlap = src_files & sub_cm["src_files"]
                if delta_days <= 14.0:
                    if any_overlap:
                        touched_files_14d |= any_overlap
                    if is_pr_revert:
                        touched_files_14d |= src_files
                if any_overlap:
                    touched_files_30d |= any_overlap
                if is_pr_revert:
                    touched_files_30d |= src_files

            # 1. Hard git revert
            if is_pr_revert:
                if days_to_first_revert is None:
                    days_to_first_revert = round(delta_days, 3)
                if delta_days <= 14.0:
                    rev_14d = 1
                if delta_days <= 30.0:
                    rev_30d = 1
                    bugfixed_files_30d |= src_files
                if delta_days <= 60.0:
                    rev_60d = 1
                    fixing_shas_60d.append(sub_cm["sha"][:10])
                if delta_days <= 90.0:
                    rev_90d = 1
                fixing_shas_90d.append(sub_cm["sha"][:10])

            # 2. SZZ source-file-overlap bug-fix commit
            overlap = (src_files & sub_cm["src_files"]) if (sub_cm["is_bugfix"] and src_files) else set()
            if overlap:
                if days_to_first_szz_fix is None:
                    days_to_first_szz_fix = round(delta_days, 3)
                if delta_days <= 14.0:
                    szz_14d = 1
                if delta_days <= 30.0:
                    szz_30d = 1
                    bugfixed_files_30d |= overlap
                if delta_days <= 60.0:
                    szz_60d = 1
                    fixing_shas_60d.append(sub_cm["sha"][:10])
                if delta_days <= 90.0:
                    szz_90d = 1
                fixing_shas_90d.append(sub_cm["sha"][:10])

        file_survival_14d_pct = round(100.0 * (1.0 - len(touched_files_14d) / src_cnt), 2) if src_cnt > 0 else 100.0
        file_survival_30d_pct = round(100.0 * (1.0 - len(bugfixed_files_30d) / src_cnt), 2) if src_cnt > 0 else 100.0
        file_survival_30d_all_commits_pct = (
            round(100.0 * (1.0 - len(touched_files_30d) / src_cnt), 2) if src_cnt > 0 else 100.0
        )

        repo_szz_rows.append(
            {
                "corpus": pr["corpus"],
                "repo_full_name": rname,
                "pr_number": pnum,
                "author_origin": pr["author_origin"],
                "agent_name": pr["agent_name"],
                "review_topology": pr["review_topology"],
                "task_type": pr["task_type"],
                "merge_commit_sha": target_cm["sha"],
                "merged_at": pr["merged_at"],
                "src_files_count": src_cnt,
                "test_files_count": len(target_cm["test_files"]),
                "iac_boundary_touched": int(len(target_cm["iac_files"]) > 0),
                "constraint_tier": c_meta["constraint_tier"],
                "pre_pr_14d_hotspot_fixes": pre_pr_14d_hotspot_fixes,
                "pre_pr_30d_hotspot_fixes": pre_pr_30d_hotspot_fixes,
                "pre_pr_30d_hotspot_commits": pre_pr_30d_hotspot_commits,
                "uncensored_14d": uncensored_14d,
                "uncensored_30d": uncensored_30d,
                "uncensored_60d": uncensored_60d,
                "uncensored_90d": uncensored_90d,
                "reverted_14d": rev_14d,
                "reverted_30d": rev_30d,
                "reverted_60d": rev_60d,
                "reverted_90d": rev_90d,
                "szz_bugfix_14d": szz_14d,
                "szz_bugfix_30d": szz_30d,
                "szz_bugfix_60d": szz_60d,
                "szz_bugfix_90d": szz_90d,
                "file_survival_14d_pct": file_survival_14d_pct,
                "file_survival_30d_pct": file_survival_30d_pct,
                "file_survival_30d_all_commits_pct": file_survival_30d_all_commits_pct,
                "days_to_first_revert": "" if days_to_first_revert is None else days_to_first_revert,
                "days_to_first_szz_fix": "" if days_to_first_szz_fix is None else days_to_first_szz_fix,
                "fix_induces_fix_k60d": len(set(fixing_shas_60d)) if pr["task_type"] == "fix" else 0,
                "fix_induces_fix_k90d": len(set(fixing_shas_90d)) if pr["task_type"] == "fix" else 0,
                "fixing_commit_shas": ";".join(sorted(set(fixing_shas_90d))[:5]),
            }
        )
    if stats is not None:
        stats["multi_candidate_prs_disambiguated"] = multi_cand_disambiguated
    if multi_cand_disambiguated > 0:
        log.info("  [%s] Disambiguated %d multi-candidate PRs by merged_at proximity.", rname, multi_cand_disambiguated)
    return c_meta, repo_szz_rows


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    m = len(s)
    return round(s[m // 2] if m % 2 == 1 else 0.5 * (s[m // 2 - 1] + s[m // 2]), 2)


def _agg_grp_14d(grp: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(grp)
    mean_surv14 = round(sum(x["file_survival_14d_pct"] for x in grp) / max(1, n), 2)
    no_hs = [x for x in grp if x["pre_pr_30d_hotspot_fixes"] == 0]
    with_hs = [x for x in grp if x["pre_pr_30d_hotspot_fixes"] > 0]
    return {
        "n_uncensored_14d": n,
        "reverted_14d_n": sum(x["reverted_14d"] for x in grp),
        "reverted_14d_pct": round(100.0 * sum(x["reverted_14d"] for x in grp) / max(1, n), 2),
        "szz_bugfix_14d_n": sum(x["szz_bugfix_14d"] for x in grp),
        "szz_bugfix_14d_pct": round(100.0 * sum(x["szz_bugfix_14d"] for x in grp) / max(1, n), 2),
        "mean_file_survival_14d_pct": mean_surv14,
        "mean_code_turnover_14d_pct": round(100.0 - mean_surv14, 2),
        "mean_pre_pr_14d_hotspot_fixes": round(sum(x["pre_pr_14d_hotspot_fixes"] for x in grp) / max(1, n), 3),
        "mean_pre_pr_30d_hotspot_fixes": round(sum(x["pre_pr_30d_hotspot_fixes"] for x in grp) / max(1, n), 3),
        "mean_pre_pr_30d_hotspot_commits": round(sum(x["pre_pr_30d_hotspot_commits"] for x in grp) / max(1, n), 3),
        "pct_with_pre_pr_hotspot_fix": round(100.0 * len(with_hs) / max(1, n), 2),
        "n_no_pre_hotspot": len(no_hs),
        "szz_bugfix_14d_pct_no_pre_hotspot": round(
            100.0 * sum(x["szz_bugfix_14d"] for x in no_hs) / max(1, len(no_hs)), 2
        )
        if no_hs
        else None,
        "n_with_pre_hotspot": len(with_hs),
        "szz_bugfix_14d_pct_with_pre_hotspot": round(
            100.0 * sum(x["szz_bugfix_14d"] for x in with_hs) / max(1, len(with_hs)), 2
        )
        if with_hs
        else None,
    }


def _agg_grp_30d(grp: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(grp)
    n60 = sum(1 for x in grp if x["uncensored_60d"] == 1)
    n90 = sum(1 for x in grp if x["uncensored_90d"] == 1)
    mean_surv14 = round(sum(x["file_survival_14d_pct"] for x in grp) / max(1, n), 2)
    mean_surv30_all = round(sum(x["file_survival_30d_all_commits_pct"] for x in grp) / max(1, n), 2)
    no_hs = [x for x in grp if x["pre_pr_30d_hotspot_fixes"] == 0]
    with_hs = [x for x in grp if x["pre_pr_30d_hotspot_fixes"] > 0]
    return {
        "n_uncensored_30d": n,
        "reverted_14d_n": sum(x["reverted_14d"] for x in grp),
        "reverted_30d_n": sum(x["reverted_30d"] for x in grp),
        "reverted_30d_pct": round(100.0 * sum(x["reverted_30d"] for x in grp) / max(1, n), 2),
        "szz_bugfix_14d_n": sum(x["szz_bugfix_14d"] for x in grp),
        "szz_bugfix_14d_pct": round(100.0 * sum(x["szz_bugfix_14d"] for x in grp) / max(1, n), 2),
        "szz_bugfix_30d_n": sum(x["szz_bugfix_30d"] for x in grp),
        "szz_bugfix_30d_pct": round(100.0 * sum(x["szz_bugfix_30d"] for x in grp) / max(1, n), 2),
        "n_uncensored_60d": n60,
        "szz_bugfix_60d_pct": round(
            100.0 * sum(x["szz_bugfix_60d"] for x in grp if x["uncensored_60d"] == 1) / max(1, n60), 2
        )
        if n60
        else None,
        "n_uncensored_90d": n90,
        "szz_bugfix_90d_pct": round(
            100.0 * sum(x["szz_bugfix_90d"] for x in grp if x["uncensored_90d"] == 1) / max(1, n90), 2
        )
        if n90
        else None,
        "mean_file_survival_14d_pct": mean_surv14,
        "mean_code_turnover_14d_pct": round(100.0 - mean_surv14, 2),
        "mean_file_survival_30d_pct": round(sum(x["file_survival_30d_pct"] for x in grp) / max(1, n), 2),
        "mean_file_survival_30d_all_commits_pct": mean_surv30_all,
        "mean_code_turnover_30d_all_commits_pct": round(100.0 - mean_surv30_all, 2),
        "mean_pre_pr_14d_hotspot_fixes": round(sum(x["pre_pr_14d_hotspot_fixes"] for x in grp) / max(1, n), 3),
        "mean_pre_pr_30d_hotspot_fixes": round(sum(x["pre_pr_30d_hotspot_fixes"] for x in grp) / max(1, n), 3),
        "mean_pre_pr_30d_hotspot_commits": round(sum(x["pre_pr_30d_hotspot_commits"] for x in grp) / max(1, n), 3),
        "pct_with_pre_pr_hotspot_fix": round(100.0 * len(with_hs) / max(1, n), 2),
        "n_no_pre_hotspot": len(no_hs),
        "szz_bugfix_30d_pct_no_pre_hotspot": round(
            100.0 * sum(x["szz_bugfix_30d"] for x in no_hs) / max(1, len(no_hs)), 2
        )
        if no_hs
        else None,
        "n_with_pre_hotspot": len(with_hs),
        "szz_bugfix_30d_pct_with_pre_hotspot": round(
            100.0 * sum(x["szz_bugfix_30d"] for x in with_hs) / max(1, len(with_hs)), 2
        )
        if with_hs
        else None,
    }


def _extract_jev_gate(review_topology: str) -> str:
    """Extract canonical Jev gate label (`Jev_Flagged`, `Jev_Clean`, `Prose_Bot_Control`, `No_Bot_Control`)."""
    if "__" in review_topology:
        return review_topology.split("__", 1)[1]
    return review_topology


def build_jev_within_repo_summary(szz_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build pooled and within-repository SZZ 14d & 30d comparisons for `Jev_Mined`
    controlling for Simpson's paradox and `pre_pr_30d_hotspot_fixes`.
    """
    jev_rows = [r for r in szz_rows if r["corpus"] == "Jev_Mined"]
    pooled_14d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    pooled_30d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_repo_14d: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    by_repo_30d: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    by_repo_all: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for r in jev_rows:
        gate = _extract_jev_gate(r["review_topology"])
        repo = r["repo_full_name"]
        by_repo_all[repo].append(r)
        if r["uncensored_14d"] == 1:
            pooled_14d[gate].append(r)
            by_repo_14d[repo][gate].append(r)
        if r["uncensored_30d"] == 1:
            pooled_30d[gate].append(r)
            by_repo_30d[repo][gate].append(r)

    multi_gate_repos_14d = sorted(repo for repo, gmap in by_repo_14d.items() if len(gmap) >= 2)
    multi_gate_repos_30d = sorted(repo for repo, gmap in by_repo_30d.items() if len(gmap) >= 2)

    matched_14d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for repo in multi_gate_repos_14d:
        for gate, grp in by_repo_14d[repo].items():
            matched_14d[gate].extend(grp)

    matched_30d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for repo in multi_gate_repos_30d:
        for gate, grp in by_repo_30d[repo].items():
            matched_30d[gate].extend(grp)

    by_repo_summary: Dict[str, Any] = {}
    for repo in sorted(by_repo_all.keys()):
        g14 = by_repo_14d.get(repo, {})
        g30 = by_repo_30d.get(repo, {})
        by_repo_summary[repo] = {
            "n_total_linked": len(by_repo_all[repo]),
            "n_uncensored_14d": sum(len(v) for v in g14.values()),
            "n_uncensored_30d": sum(len(v) for v in g30.values()),
            "has_multi_gate_contrast_14d": len(g14) >= 2,
            "has_multi_gate_contrast_30d": len(g30) >= 2,
            "gates_14d": {gate: _agg_grp_14d(grp) for gate, grp in sorted(g14.items())},
            "gates_30d": {gate: _agg_grp_30d(grp) for gate, grp in sorted(g30.items())},
        }

    return {
        "total_jev_mined_linked_prs": len(jev_rows),
        "repos_with_jev_mined_linked_prs": len(by_repo_all),
        "multi_gate_contrast_repos_14d": multi_gate_repos_14d,
        "multi_gate_contrast_repos_30d": multi_gate_repos_30d,
        "pooled_by_jev_gate_14d": {k: _agg_grp_14d(v) for k, v in sorted(pooled_14d.items())},
        "pooled_by_jev_gate_30d": {k: _agg_grp_30d(v) for k, v in sorted(pooled_30d.items())},
        "within_repo_matched_summary_14d": {k: _agg_grp_14d(v) for k, v in sorted(matched_14d.items())},
        "within_repo_matched_summary_30d": {k: _agg_grp_30d(v) for k, v in sorted(matched_30d.items())},
        "by_repo_and_jev_gate": by_repo_summary,
    }


def run_build(paths: PathConfig, log: Any, workers: int = 8, allow_empty: bool = False) -> Dict[str, Any]:
    """Run full local bare-git SZZ, hotspot, and architectural constraint ledger generation."""
    out_szz_csv = paths.tables_dir / "szz_defect_traceability_ledger.csv"
    out_constraints_csv = paths.tables_dir / "repo_architectural_constraints_ledger.csv"
    out_summary_json = paths.results_dir / "szz_and_constraints_summary.json"
    jev_git_cache = paths.scratch_dir / "jev_pr_reviews" / "_git_cache"

    all_prs, jev_source_used = load_target_merged_prs(paths, log)
    prs_by_repo: Dict[str, List[Dict[str, Any]]] = {}
    slug_to_repo: Dict[str, str] = {}
    for p in all_prs:
        r = p["repo_full_name"]
        prs_by_repo.setdefault(r, []).append(p)
        slug_to_repo[r.replace("/", "__")] = r

    cloned_repos: Dict[str, Path] = {}
    for base in (paths.clones_dir, jev_git_cache):
        if base.exists():
            for entry in sorted(base.iterdir()):
                if entry.name.endswith(".git") and (entry / "HEAD").exists():
                    slug = entry.name[:-4]
                    rname = slug_to_repo.get(slug, slug.replace("__", "/", 1))
                    cloned_repos.setdefault(rname, entry)

    log.info(
        "Found %d local bare git clones across %s and %s (target merged PRs=%d across %d repos).",
        len(cloned_repos),
        paths.clones_dir,
        jev_git_cache,
        len(all_prs),
        len(prs_by_repo),
    )

    if not cloned_repos and not allow_empty:
        log.warning(
            "No local bare git clones found yet. Run `python3 src/pipelines/p00_fetch_datasets.py --only-clones --clone-tier 1` first."
        )
        return {}

    constraint_rows: List[Dict[str, Any]] = []
    szz_rows: List[Dict[str, Any]] = []
    repo_stats: Dict[str, Dict[str, int]] = {rname: {} for rname in cloned_repos}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fut_map = {
            ex.submit(
                process_single_cloned_repo,
                rname,
                bare_dir,
                prs_by_repo.get(rname, []),
                log,
                repo_stats[rname],
            ): rname
            for rname, bare_dir in sorted(cloned_repos.items())
        }
        for idx, fut in enumerate(as_completed(fut_map), 1):
            rname = fut_map[fut]
            try:
                c_meta, r_szz = fut.result()
                constraint_rows.append(c_meta)
                szz_rows.extend(r_szz)
            except Exception as exc:
                log.warning("Error scanning %s: %s", rname, exc)
            if idx % 30 == 0 or idx == len(cloned_repos):
                log.info("  SZZ progress: %d/%d repos scanned | linked_prs=%d", idx, len(cloned_repos), len(szz_rows))

    total_multi_cand_disambiguated = sum(
        st.get("multi_candidate_prs_disambiguated", 0) for st in repo_stats.values()
    )
    log.info(
        "SZZ PR disambiguation summary: %d multi-candidate PRs disambiguated by merged_at proximity across %d repos.",
        total_multi_cand_disambiguated,
        len(cloned_repos),
    )

    constraint_rows.sort(key=lambda x: x["repo_full_name"])
    szz_rows.sort(key=lambda x: (x["corpus"], x["repo_full_name"], int(x["pr_number"])))

    with out_constraints_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "repo_full_name",
            "has_codeowners",
            "codeowners_first_commit_at",
            "has_deterministic_sast_workflow",
            "sast_tools_detected",
            "has_agent_boundary_contract",
            "agent_contract_files",
            "has_review_bot_config",
            "workflow_files_count",
            "constraint_tier",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(constraint_rows)

    with out_szz_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "corpus",
            "repo_full_name",
            "pr_number",
            "author_origin",
            "agent_name",
            "review_topology",
            "task_type",
            "merge_commit_sha",
            "merged_at",
            "src_files_count",
            "test_files_count",
            "iac_boundary_touched",
            "constraint_tier",
            "pre_pr_14d_hotspot_fixes",
            "pre_pr_30d_hotspot_fixes",
            "pre_pr_30d_hotspot_commits",
            "uncensored_14d",
            "uncensored_30d",
            "uncensored_60d",
            "uncensored_90d",
            "reverted_14d",
            "reverted_30d",
            "reverted_60d",
            "reverted_90d",
            "szz_bugfix_14d",
            "szz_bugfix_30d",
            "szz_bugfix_60d",
            "szz_bugfix_90d",
            "file_survival_14d_pct",
            "file_survival_30d_pct",
            "file_survival_30d_all_commits_pct",
            "days_to_first_revert",
            "days_to_first_szz_fix",
            "fix_induces_fix_k60d",
            "fix_induces_fix_k90d",
            "fixing_commit_shas",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(szz_rows)

    aidev_szz_fix_days = [
        float(r["days_to_first_szz_fix"])
        for r in szz_rows
        if r["corpus"] == "AIDev" and r["days_to_first_szz_fix"] != ""
    ]
    aidev_rev_days = [
        float(r["days_to_first_revert"])
        for r in szz_rows
        if r["corpus"] == "AIDev" and r["days_to_first_revert"] != ""
    ]
    all_szz_fix_days = [
        float(r["days_to_first_szz_fix"])
        for r in szz_rows
        if r["days_to_first_szz_fix"] != ""
    ]

    by_topo_14d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_topo_30d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_tier_30d: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in szz_rows:
        topo_key = f"{row['corpus']}::{row['review_topology']}"
        if row["uncensored_14d"] == 1:
            by_topo_14d[topo_key].append(row)
        if row["uncensored_30d"] == 1:
            by_topo_30d[topo_key].append(row)
            if row["corpus"] == "AIDev":
                by_tier_30d[f"Tier_{row['constraint_tier']}"].append(row)

    summary = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "szz_methodology_note": (
            "Commit-attributed source-file-overlap SZZ via `git -c diff.renames=false log --no-renames "
            "--first-parent --name-only` (file-level granularity, coarser than line-level git blame; "
            "zero --numstat blob fetches); `fix_induces_fix_k60d` strictly bounded to delta_days <= 60.0; "
            "`pre_pr_14d_hotspot_fixes` (-14.0 <= delta_days < 0.0, symmetric to `szz_bugfix_14d`), "
            "`pre_pr_30d_hotspot_fixes` & `pre_pr_30d_hotspot_commits` (-30.0 <= delta_days < 0.0); "
            "`file_survival_30d_pct` is bugfix-only (bug-fix commits + reverts in 30d), whereas "
            "`file_survival_14d_pct` (0 < delta_days <= 14.0) and `file_survival_30d_all_commits_pct` "
            "(0 < delta_days <= 30.0) track all-commit turnover survival."
        ),
        "jev_signals_source": jev_source_used,
        "cloned_repos_scanned": len(cloned_repos),
        "szz_linked_merged_prs": len(szz_rows),
        "multi_candidate_prs_disambiguated": total_multi_cand_disambiguated,
        "empirical_survival_time_days": {
            "aidev_szz_bugfix_n": len(aidev_szz_fix_days),
            "aidev_szz_bugfix_median_days": _median(aidev_szz_fix_days),
            "aidev_hard_revert_n": len(aidev_rev_days),
            "aidev_hard_revert_median_days": _median(aidev_rev_days),
            "all_corpora_szz_bugfix_n": len(all_szz_fix_days),
            "all_corpora_szz_bugfix_median_days": _median(all_szz_fix_days),
        },
        "constraints_csv": str(out_constraints_csv),
        "szz_ledger_csv": str(out_szz_csv),
        "by_corpus_and_topology_14d": {k: _agg_grp_14d(v) for k, v in sorted(by_topo_14d.items())},
        "by_corpus_and_topology_30d": {k: _agg_grp_30d(v) for k, v in sorted(by_topo_30d.items())},
        "aidev_by_constraint_tier_30d": {k: _agg_grp_30d(v) for k, v in sorted(by_tier_30d.items())},
        "jev_within_repo_szz_14d_and_30d": build_jev_within_repo_summary(szz_rows),
    }
    out_summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log.info(
        "Completed SZZ & Architectural Constraints extraction: repos=%d, linked_prs=%d -> %s",
        len(cloned_repos),
        len(szz_rows),
        out_summary_json,
    )
    for k, st in summary["by_corpus_and_topology_30d"].items():
        log.info(
            "  SZZ-30d %-44s | n30=%-5d | rev30=%5.2f%% | szz14=%5.2f%% | szz30=%5.2f%% | surv14=%5.2f%% | surv30=%5.2f%% | hs_fixes=%.3f",
            k,
            st["n_uncensored_30d"],
            st["reverted_30d_pct"],
            st["szz_bugfix_14d_pct"],
            st["szz_bugfix_30d_pct"],
            st["mean_file_survival_14d_pct"],
            st["mean_file_survival_30d_pct"],
            st["mean_pre_pr_30d_hotspot_fixes"],
        )
    return summary


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p00b_build_szz_constraints",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )

    parser = argparse.ArgumentParser(
        description="Build offline commit-dated architectural constraint, pre-PR hotspot, and SZZ defect ledgers."
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write empty CSV/JSON ledgers even if no local bare git clones are found.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel worker threads for local git history scanning.",
    )
    args = parser.parse_args()

    log.info("Starting Local Bare-Git SZZ & Constraint Builder (log=%s)", ts_log)
    run_build(paths=paths, log=log, workers=args.workers, allow_empty=args.allow_empty)


if __name__ == "__main__":
    main()
