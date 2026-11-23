#!/usr/bin/env python3
"""
Step 0A: Automated Local Dataset Downloader & Tier-1 Bare Git Cloner
====================================================================
Reads `replication/datasets_manifest.yaml` and hydrates the local `scratch/`
directory for open-science replication and bare-git SZZ defect analysis:

  1. Downloads missing Zenodo & Hugging Face datasets (`AIDev`, `AgenticFlict`,
     `DevGPT`, `CodeRabbit`, `CodAGE`, `GitHub-Agentic-PR-Dataset`,
     `CodeReviewBench`, `Qodo PR-Review-Bench`, `GHArchive`).
  2. Verifies local `scratch/jev_pr_reviews/` parquet tables if present.
  3. Executes **Tier-1 Bare Git Cloning** (`--clone-tier 1`, default) into
     `scratch/git_clones/<owner>__<repo>.git` using `--bare --filter=blob:none`
     (zero GitHub REST API quota) across:
       - The exact 281 multi-regime shared AIDev repositories (hosting both
         human-reviewed and silent-gate merged PRs), plus
       - Active TypeSafe Jev decision-model adopter repositories (`getsentry/sentry`,
         `craftmilldev/sesh`, `craftmilldev/loopway`, `mirrorstack-ai/mirrorstack-cli`,
         `fabiankaegy/pr-risk`, `BerriAI/litellm`, etc.).
     Pass `--clone-tier 2` to expand cloning to all 810 shared AIDev repositories.
  4. Optionally hydrates human baseline PR review/merge-SHA metadata via
     GitHub REST API (`--hydrate-human-reviews`) when `GITHUB_TOKEN` is set.

Usage:
  # Verify current local scratch/ state and print missing items (non-destructive):
  python3 replication/scripts/00_fetch_datasets.py --verify-only

  # Download all missing datasets + clone Tier-1 bare git repositories:
  python3 replication/scripts/00_fetch_datasets.py --all --clone-tier 1

  # Clone only Tier-1 bare git repositories (e.g., when scratch/ datasets already exist):
  python3 replication/scripts/00_fetch_datasets.py --only-clones --clone-tier 1 --max-repos 300
"""

import argparse
import csv
import datetime
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SCRATCH_DIR = os.path.join(REPO_ROOT, "scratch")
CLONES_DIR = os.path.join(SCRATCH_DIR, "git_clones")
LOGS_DIR = os.path.join(REPO_ROOT, "replication", "logs")
TABLES_DIR = os.path.join(REPO_ROOT, "replication", "results", "pr_review", "data_tables")
MANIFEST_PATH = os.path.join(REPO_ROOT, "replication", "datasets_manifest.yaml")

os.makedirs(LOGS_DIR, exist_ok=True)
RUN_TS = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
TS_LOG = os.path.join(LOGS_DIR, f"verbose_fetch_datasets_{RUN_TS}.log")
CUM_LOG = os.path.join(LOGS_DIR, "replication_execution.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [fetch_datasets] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(TS_LOG, mode="w", encoding="utf-8"),
        logging.FileHandler(CUM_LOG, mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("fetch_datasets")


JEV_CORE_REPOS = [
    "getsentry/sentry",
    "craftmilldev/sesh",
    "craftmilldev/loopway",
    "mirrorstack-ai/mirrorstack-cli",
    "fabiankaegy/pr-risk",
    "BerriAI/litellm",
]


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_file_resumable(url: str, dest_path: str, expected_sha256: Optional[str] = None) -> bool:
    """Downloads a file using curl (with resume support) or urllib fallback, verifying SHA-256."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        if expected_sha256:
            actual = compute_sha256(dest_path)
            if actual.lower() == expected_sha256.lower():
                log.info("[SKIP-VERIFIED] %s (sha256=%s...)", dest_path, actual[:12])
                return True
            log.warning("[CHECKSUM-MISMATCH] %s (expected=%s..., got=%s...). Re-downloading.", dest_path, expected_sha256[:12], actual[:12])
        else:
            sz_mb = os.path.getsize(dest_path) / (1024 * 1024)
            log.info("[SKIP-EXISTS] %s (%.2f MB)", dest_path, sz_mb)
            return True

    log.info("Downloading %s -> %s ...", url, dest_path)
    curl_bin = shutil.which("curl")
    if curl_bin:
        cmd = [curl_bin, "-L", "--fail", "--retry", "3", "--retry-delay", "3", "-C", "-", "-o", dest_path, url]
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            log.error("curl failed (exit=%d) for %s", ret.returncode, url)
            return False
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "pr-review-replication/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp, open(dest_path, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)
        except Exception as e:
            log.error("Download error for %s: %s", url, e)
            return False

    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        log.error("Downloaded file is empty or missing: %s", dest_path)
        return False

    sz = os.path.getsize(dest_path)
    sha = compute_sha256(dest_path)
    log.info("Saved %s | size=%d bytes (%.2f MB) | sha256=%s", dest_path, sz, sz / (1024 * 1024), sha)
    if expected_sha256 and sha.lower() != expected_sha256.lower():
        log.error("SHA-256 verification failed for %s: expected %s, got %s", dest_path, expected_sha256, sha)
        return False
    return True


def fetch_zenodo_record_files(record_id: str, target_dir: str) -> bool:
    """Queries Zenodo REST API for a record and downloads/extracts all attached files."""
    api_url = f"https://zenodo.org/api/records/{record_id}"
    log.info("Querying Zenodo record metadata: %s", api_url)
    req = urllib.request.Request(api_url, headers={"User-Agent": "pr-review-replication/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.error("Failed to query Zenodo API %s: %s", api_url, e)
        return False

    files = meta.get("files", [])
    if not files:
        log.warning("No files listed in Zenodo record %s", record_id)
        return False

    os.makedirs(target_dir, exist_ok=True)
    all_ok = True
    for fmeta in files:
        fname = fmeta.get("key") or fmeta.get("filename")
        dl_url = (fmeta.get("links") or {}).get("self") or f"https://zenodo.org/records/{record_id}/files/{fname}"
        dest = os.path.join(target_dir, fname)
        if not download_file_resumable(dl_url, dest):
            all_ok = False
            continue
        if fname.endswith((".tar.gz", ".tgz")):
            log.info("Extracting archive %s into %s ...", dest, target_dir)
            with tarfile.open(dest, "r:gz") as tf:
                tf.extractall(target_dir)
        elif fname.endswith(".zip") and "configuration_files" not in fname:
            log.info("Extracting zip %s into %s ...", dest, target_dir)
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(target_dir)
    return all_ok


def fetch_direct_datasets(include_extended: bool = False) -> Dict[str, bool]:
    """Downloads missing core datasets into scratch/."""
    status: Dict[str, bool] = {}

    # 1. AIDev (Zenodo 16899501)
    aidev_dir = os.path.join(SCRATCH_DIR, "aidev")
    pr_pq = os.path.join(aidev_dir, "pull_request.parquet")
    if not os.path.exists(pr_pq):
        status["DS-01_aidev"] = fetch_zenodo_record_files("16899501", aidev_dir)
    else:
        log.info("[OK] AIDev core parquets already present at %s", aidev_dir)
        status["DS-01_aidev"] = True

    if include_extended:
        ext_pq = os.path.join(aidev_dir, "pr_commit_details.parquet")
        if not os.path.exists(ext_pq):
            download_file_resumable(
                "https://huggingface.co/datasets/hao-li/AIDev/resolve/main/pr_commit_details.parquet",
                ext_pq,
            )

    # 2. AgenticFlict (Zenodo 15783294)
    af_dir = os.path.join(SCRATCH_DIR, "agenticflict")
    af_csv = os.path.join(af_dir, "data", "clean", "agenticflict_pr_clean.csv")
    if not os.path.exists(af_csv):
        status["DS-02_agenticflict"] = fetch_zenodo_record_files("15783294", af_dir)
    else:
        log.info("[OK] AgenticFlict already present at %s", af_csv)
        status["DS-02_agenticflict"] = True

    # 3. DevGPT (Zenodo 8381898)
    devgpt_dir = os.path.join(SCRATCH_DIR, "devgpt")
    devgpt_db = os.path.join(devgpt_dir, "devgpt.sqlite")
    if not os.path.exists(devgpt_db):
        status["DS-03_devgpt"] = fetch_zenodo_record_files("8381898", devgpt_dir)
    else:
        log.info("[OK] DevGPT already present at %s", devgpt_db)
        status["DS-03_devgpt"] = True

    # 4. CodeRabbit OSS (Zenodo 21878471)
    cr_dir = os.path.join(SCRATCH_DIR, "coderabbit")
    cr_pq = os.path.join(cr_dir, "pull_requests.parquet")
    if not os.path.exists(cr_pq):
        status["DS-04_coderabbit"] = fetch_zenodo_record_files("21878471", cr_dir)
    else:
        log.info("[OK] CodeRabbit OSS already present at %s", cr_pq)
        status["DS-04_coderabbit"] = True

    # 5. CodeReviewBench & Qodo PR-Review-Bench (Hugging Face direct URLs)
    hf_direct = [
        ("code_review_bench", "online_sample.parquet", "https://huggingface.co/datasets/code-review-bench/code-review-bench/resolve/main/online_sample.parquet"),
        ("code_review_bench", "offline_golden_issues.parquet", "https://huggingface.co/datasets/code-review-bench/code-review-bench/resolve/main/offline_golden_issues.parquet"),
        ("code_review_bench", "human_annotations_task1.parquet", "https://huggingface.co/datasets/code-review-bench/code-review-bench/resolve/main/human_annotations_task1.parquet"),
        ("code_review_bench", "human_annotations_task2.parquet", "https://huggingface.co/datasets/code-review-bench/code-review-bench/resolve/main/human_annotations_task2.parquet"),
        ("qodo_pr_review_bench", "git_code_review_bench_100_w_open_prs.jsonl", "https://huggingface.co/datasets/Qodo/PR-Review-Bench/resolve/main/git_code_review_bench_100_w_open_prs.jsonl"),
        ("qodo_pr_review_bench", "rules_for_repo.jsonl", "https://huggingface.co/datasets/Qodo/PR-Review-Bench/resolve/main/rules_for_repo.jsonl"),
    ]
    crb_ok = True
    for folder, fname, url in hf_direct:
        dest = os.path.join(SCRATCH_DIR, folder, fname)
        if not download_file_resumable(url, dest):
            crb_ok = False
    status["DS-07_08_review_benchmarks"] = crb_ok

    # 6. GHArchive Hourly & 3-Day Streams
    gha_targets = [
        (os.path.join(SCRATCH_DIR, "gharchive", "gharchive_2025-07-15-15.json.gz"), "https://data.gharchive.org/2025-07-15-15.json.gz"),
    ]
    gha_ok = True
    for dest, url in gha_targets:
        if not download_file_resumable(url, dest):
            gha_ok = False
    status["DS-09_gharchive"] = gha_ok

    # 7. TypeSafe Jev Mined Corpus (optional pre-hydrated local parquets)
    jev_pq = os.path.join(SCRATCH_DIR, "jev_pr_reviews", "jev_pull_requests.parquet")
    if not os.path.exists(jev_pq):
        log.info(
            "[INFO] TypeSafe Jev raw parquet cache not present at %s "
            "(canonical aggregated Jev tables are bundled in replication/results/pr_review/).",
            jev_pq,
        )
        status["DS-10_jev_pr_reviews"] = False
    else:
        log.info("[OK] TypeSafe Jev PR corpus already present at %s", jev_pq)
        status["DS-10_jev_pr_reviews"] = True

    return status


def resolve_clone_repositories(tier: int = 1, max_repos: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Resolves the exact repository list for bare git cloning:
      - Tier 1 (Default): The 281 multi-regime shared AIDev repositories (hosting both
        human-reviewed and silent merged agent PRs) + active Jev adopter repositories.
      - Tier 2: All 810 shared AIDev repositories (hosting both agent and human PRs) +
        active Jev adopter repositories.
    Falls back to `analyzed_repositories_log.csv` if `scratch/aidev/` parquets are not yet on disk.
    """
    repos_dict: Dict[str, Dict[str, Any]] = {}

    # 1. Always include active Jev adopter repositories first
    jev_comms_pq = os.path.join(SCRATCH_DIR, "jev_pr_reviews", "jev_bot_signals_and_comments.parquet")
    if os.path.exists(jev_comms_pq):
        try:
            import duckdb
            con = duckdb.connect()
            j_rows = con.execute(f"""
                SELECT repo_full_name, COUNT(DISTINCT pr_number) AS prs
                FROM read_parquet('{jev_comms_pq}')
                WHERE is_jev_signal
                GROUP BY 1
                ORDER BY prs DESC
            """).fetchall()
            for rname, cnt in j_rows:
                repos_dict[rname] = {"repo_full_name": rname, "cohort": "jev_adopter", "priority_prs": int(cnt)}
        except Exception as e:
            log.warning("Could not query %s: %s", jev_comms_pq, e)

    for rname in JEV_CORE_REPOS:
        if rname not in repos_dict:
            repos_dict[rname] = {"repo_full_name": rname, "cohort": "jev_core", "priority_prs": 50}

    # 2. Resolve AIDev Tier 1 (281 multi-regime repos) or Tier 2 (810 shared repos)
    aidev_dir = os.path.join(SCRATCH_DIR, "aidev")
    pr_pq = os.path.join(aidev_dir, "pull_request.parquet")
    hpr_pq = os.path.join(aidev_dir, "human_pull_request.parquet")
    rev_pq = os.path.join(aidev_dir, "pr_reviews.parquet")
    repo_pq = os.path.join(aidev_dir, "repository.parquet")

    if os.path.exists(pr_pq) and os.path.exists(rev_pq) and os.path.exists(repo_pq):
        import duckdb
        con = duckdb.connect()
        if tier == 1:
            # Exact 281 multi-regime shared repositories hosting both human-reviewed and silent PRs
            rows = con.execute(f"""
                WITH rev_flags AS (
                    SELECT pr_id, SUM(CASE WHEN user_type = 'User' THEN 1 ELSE 0 END) AS h_revs
                    FROM read_parquet('{rev_pq}')
                    GROUP BY pr_id
                ),
                merged AS (
                    SELECT
                        p.id AS pr_id,
                        p.repo_id,
                        (COALESCE(rf.h_revs, 0) > 0) AS is_reviewed
                    FROM read_parquet('{pr_pq}') p
                    LEFT JOIN rev_flags rf ON p.id = rf.pr_id
                    WHERE p.merged_at IS NOT NULL
                    GROUP BY p.id, p.repo_id, is_reviewed
                ),
                shared_281 AS (
                    SELECT
                        repo_id,
                        COUNT(*) AS merged_prs,
                        SUM(CASE WHEN is_reviewed THEN 1 ELSE 0 END) AS reviewed_merged,
                        SUM(CASE WHEN NOT is_reviewed THEN 1 ELSE 0 END) AS silent_merged
                    FROM merged
                    GROUP BY repo_id
                    HAVING SUM(CASE WHEN is_reviewed THEN 1 ELSE 0 END) > 0
                       AND SUM(CASE WHEN NOT is_reviewed THEN 1 ELSE 0 END) > 0
                )
                SELECT r.full_name, s.merged_prs, s.reviewed_merged, s.silent_merged
                FROM shared_281 s
                JOIN read_parquet('{repo_pq}') r ON s.repo_id = r.id
                ORDER BY s.merged_prs DESC
            """).fetchall()
            log.info("Resolved %d exact Tier-1 multi-regime repositories directly from scratch/aidev/ parquets.", len(rows))
            for rname, m_cnt, rev_cnt, sil_cnt in rows:
                if rname not in repos_dict:
                    repos_dict[rname] = {
                        "repo_full_name": rname,
                        "cohort": "tier1_aidev_281_multiregime",
                        "priority_prs": int(m_cnt),
                        "reviewed_merged": int(rev_cnt),
                        "silent_merged": int(sil_cnt),
                    }
        else:
            # Tier 2: All 810 shared repositories hosting both agent and human PRs
            rows = con.execute(f"""
                WITH agent_repos AS (
                    SELECT repo_id, COUNT(*) AS a_prs
                    FROM read_parquet('{pr_pq}')
                    GROUP BY repo_id
                ),
                human_repos AS (
                    SELECT repo_id, COUNT(*) AS h_prs
                    FROM read_parquet('{hpr_pq}')
                    GROUP BY repo_id
                )
                SELECT r.full_name, a.a_prs + h.h_prs AS total_prs
                FROM agent_repos a
                JOIN human_repos h ON a.repo_id = h.repo_id
                JOIN read_parquet('{repo_pq}') r ON a.repo_id = r.id
                ORDER BY total_prs DESC
            """).fetchall()
            log.info("Resolved %d exact Tier-2 shared repositories directly from scratch/aidev/ parquets.", len(rows))
            for rname, t_cnt in rows:
                if rname not in repos_dict:
                    repos_dict[rname] = {
                        "repo_full_name": rname,
                        "cohort": "tier2_aidev_810_shared",
                        "priority_prs": int(t_cnt),
                    }
    else:
        # Fallback to committed analyzed_repositories_log.csv
        fallback_csv = os.path.join(TABLES_DIR, "analyzed_repositories_log.csv")
        if os.path.exists(fallback_csv):
            with open(fallback_csv, "r", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            # Prioritize repos with both Cohort B and Cohort C, then repos with both reviewed and unreviewed PRs and >0 merged PRs
            candidates = [
                r for r in csv_rows
                if int(r["agent_prs_merged"]) > 0
                and int(r["human_reviewed_prs"]) > 0
                and int(r["agent_prs_total"]) > int(r["human_reviewed_prs"])
            ]
            candidates.sort(
                key=lambda r: (
                    1 if (int(r["cohort_b_human_only_prs"]) > 0 and int(r["cohort_c_tier1_bot_prs"]) > 0) else 0,
                    int(r["agent_prs_merged"]),
                ),
                reverse=True,
            )
            target_n = 281 if tier == 1 else min(810, len(candidates))
            for r in candidates[:target_n]:
                rname = r["full_name"]
                if rname not in repos_dict:
                    repos_dict[rname] = {
                        "repo_full_name": rname,
                        "cohort": f"tier{tier}_csv_fallback",
                        "priority_prs": int(r["agent_prs_merged"]),
                    }
            log.info("Resolved %d Tier-%d repositories via fallback CSV (%s).", len(repos_dict), tier, fallback_csv)

    repo_list = list(repos_dict.values())
    if max_repos is not None and max_repos > 0:
        repo_list = repo_list[:max_repos]
    return repo_list


def clone_single_bare_repo(repo_meta: Dict[str, Any], timeout_s: int = 300) -> Dict[str, Any]:
    """Clones or updates a single bare git repository with `--bare --filter=blob:none`."""
    rname = repo_meta["repo_full_name"]
    slug = rname.replace("/", "__")
    bare_dir = os.path.join(CLONES_DIR, f"{slug}.git")
    url = f"https://github.com/{rname}.git"
    t0 = time.time()
    git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    try:
        if os.path.exists(os.path.join(bare_dir, "HEAD")):
            return {
                "repo_full_name": rname,
                "cohort": repo_meta.get("cohort", ""),
                "bare_dir": bare_dir,
                "status": "cached",
                "elapsed_sec": round(time.time() - t0, 2),
            }
        os.makedirs(CLONES_DIR, exist_ok=True)
        cmd = ["git", "clone", "--bare", "--filter=blob:none", url, bare_dir]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=git_env)
        if p.returncode != 0:
            shutil.rmtree(bare_dir, ignore_errors=True)
            return {
                "repo_full_name": rname,
                "cohort": repo_meta.get("cohort", ""),
                "bare_dir": bare_dir,
                "status": "failed",
                "error": (p.stderr or p.stdout or "")[:240].strip(),
                "elapsed_sec": round(time.time() - t0, 2),
            }
        return {
            "repo_full_name": rname,
            "cohort": repo_meta.get("cohort", ""),
            "bare_dir": bare_dir,
            "status": "cloned",
            "elapsed_sec": round(time.time() - t0, 2),
        }
    except Exception as e:
        shutil.rmtree(bare_dir, ignore_errors=True)
        return {
            "repo_full_name": rname,
            "cohort": repo_meta.get("cohort", ""),
            "bare_dir": bare_dir,
            "status": "error",
            "error": str(e)[:240],
            "elapsed_sec": round(time.time() - t0, 2),
        }


def execute_bare_clones(tier: int = 1, workers: int = 4, max_repos: Optional[int] = None) -> Dict[str, Any]:
    """Clones Tier-1 (or Tier-2) bare git repositories in parallel and records a provenance manifest."""
    repo_list = resolve_clone_repositories(tier=tier, max_repos=max_repos)
    log.info("Starting Tier-%d bare git clone sweep across %d repositories (workers=%d)...", tier, len(repo_list), workers)
    os.makedirs(CLONES_DIR, exist_ok=True)

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fut_map = {ex.submit(clone_single_bare_repo, rm): rm for rm in repo_list}
        for idx, fut in enumerate(as_completed(fut_map), 1):
            res = fut.result()
            results.append(res)
            if idx % 20 == 0 or idx == len(repo_list) or res["status"] not in ("cached", "cloned"):
                log.info(
                    "[%d/%d] %s (%s) -> %s (%.2fs)",
                    idx, len(repo_list), res["repo_full_name"], res["cohort"], res["status"], res["elapsed_sec"],
                )

    summary = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "clone_tier": tier,
        "target_repos_count": len(repo_list),
        "cloned_fresh": sum(1 for r in results if r["status"] == "cloned"),
        "cached_existing": sum(1 for r in results if r["status"] == "cached"),
        "failed_count": sum(1 for r in results if r["status"] not in ("cloned", "cached")),
        "repositories": results,
    }
    manifest_out = os.path.join(CLONES_DIR, "_clone_manifest.json")
    with open(manifest_out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log.info(
        "Bare git clone sweep complete: cloned=%d, cached=%d, failed=%d. Manifest saved to %s",
        summary["cloned_fresh"], summary["cached_existing"], summary["failed_count"], manifest_out,
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Download/verify PR-review empirical datasets and clone Tier-1 bare git repositories.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing files and print Tier-1 target summary.")
    parser.add_argument("--all", action="store_true", help="Download all missing datasets and execute Tier-1 bare git clones.")
    parser.add_argument("--only-datasets", action="store_true", help="Download missing datasets in scratch/ without cloning git repos.")
    parser.add_argument("--only-clones", action="store_true", help="Only clone bare git repositories into scratch/git_clones/.")
    parser.add_argument("--clone-tier", type=int, choices=[1, 2], default=1, help="Git clone tier: 1 (281 multi-regime + Jev repos, default) or 2 (810 shared + Jev repos).")
    parser.add_argument("--max-repos", type=int, default=None, help="Optional cap on number of repositories to clone.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel git clone workers (default: 4).")
    parser.add_argument("--include-extended", action="store_true", help="Also download extended AIDev pr_commit_details.parquet.")
    args = parser.parse_args()

    log.info("PR-Review Dataset & Tier-%d Git Clone Manager started (log=%s)", args.clone_tier, TS_LOG)

    if args.verify_only or not (args.all or args.only_datasets or args.only_clones):
        target_repos = resolve_clone_repositories(tier=args.clone_tier, max_repos=args.max_repos)
        existing_clones = 0
        if os.path.exists(CLONES_DIR):
            existing_clones = sum(
                1 for rm in target_repos
                if os.path.exists(os.path.join(CLONES_DIR, f"{rm['repo_full_name'].replace('/', '__')}.git", "HEAD"))
            )
        log.info("Tier-%d Clone Target Resolution: %d repositories resolved (%d currently cloned in %s)",
                 args.clone_tier, len(target_repos), existing_clones, CLONES_DIR)
        expected_dirs = {
            "DS-01_aidev": os.path.join(SCRATCH_DIR, "aidev", "pull_request.parquet"),
            "DS-02_agenticflict": os.path.join(SCRATCH_DIR, "datasets8", "agenticflict"),
            "DS-03_devgpt": os.path.join(SCRATCH_DIR, "datasets8", "devgpt"),
            "DS-04_coderabbit": os.path.join(SCRATCH_DIR, "datasets8", "coderabbit"),
            "DS-05_codage": os.path.join(SCRATCH_DIR, "datasets8", "codage"),
            "DS-06_agentic_prs": os.path.join(SCRATCH_DIR, "datasets8", "agentic_prs"),
            "DS-07_codereviewbench": os.path.join(SCRATCH_DIR, "datasets8", "codereviewbench"),
            "DS-08_qodo_prbench": os.path.join(SCRATCH_DIR, "datasets8", "qodo_prbench"),
            "DS-09_gharchive": os.path.join(SCRATCH_DIR, "datasets8", "gharchive"),
            "DS-10_jev_pr_reviews": os.path.join(SCRATCH_DIR, "jev_pr_reviews", "jev_pull_requests.parquet"),
        }
        present = {k: os.path.exists(v) for k, v in expected_dirs.items()}
        log.info("Raw dataset availability check (%d/%d present): %s",
                 sum(present.values()), len(present), json.dumps(present, indent=2))
        sys.exit(0)

    if args.all or args.only_datasets:
        ds_status = fetch_direct_datasets(include_extended=args.include_extended)
        log.info("Dataset download status summary: %s", json.dumps(ds_status, indent=2))

    if args.all or args.only_clones:
        execute_bare_clones(tier=args.clone_tier, workers=args.workers, max_repos=args.max_repos)


if __name__ == "__main__":
    main()
