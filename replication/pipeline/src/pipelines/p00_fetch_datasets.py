#!/usr/bin/env python3
"""
Step 0A: Zero-API Dataset Downloader, Manifest Loader & Bare-Git Clone/Fetch Manager
===================================================================================
Reads `config/datasets_manifest.toml` via Python's stdlib `tomllib` and resolves all
paths via `config.paths.get_paths()` with zero GitHub API token requirements:

  1. Downloads missing Zenodo, Hugging Face, and GHArchive datasets into `paths.scratch_dir`.
  2. Executes anonymous bare-git cloning & incremental head-advancing fetches into
     `paths.clones_dir` (`--bare --filter=blob:none`, `GIT_TERMINAL_PROMPT=0`,
     `-c credential.helper=`):
       - Tier 1: 281 multi-regime shared AIDev repositories + `JEV_ADOPTER_REPOS`
       - Tier 2: 810 shared AIDev repositories + `JEV_ADOPTER_REPOS`
       - Tier `jev` / `--update-jev-clones`: Anonymous `git fetch` on all already-cloned
         Jev adopter repositories (advancing `HEAD` to current tip so Oct 2026 PRs unlock
         uncensored 30d SZZ windows) + anonymous bare clone of any missing
         `JEV_ADOPTER_REPOS`.
  3. Writes deterministic provenance manifests to `paths.clones_dir / "_clone_manifest.json"`
     and `paths.clones_dir / "_jev_clone_sync_manifest.json"` and verbose logs to `paths.logs_dir`.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

PR_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
if str(PR_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(PR_ANALYSIS_ROOT))

from config.bot_catalog import JEV_ADOPTER_REPOS
from config.paths import PathConfig, get_paths
from src.utils.logging_utils import setup_verbose_logger


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load the TOML dataset/clone manifest from `manifest_path`."""
    with manifest_path.open("rb") as f:
        return tomllib.load(f)


def compute_sha256(filepath: Path) -> str:
    """Compute hex SHA-256 checksum for a local file."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _anonymous_git_env() -> Dict[str, str]:
    """Return environment forcing non-interactive anonymous git transport."""
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }


def download_file_resumable(
    url: str,
    dest_path: Path,
    log: Any,
    expected_sha256: Optional[str] = None,
) -> bool:
    """Download a file using curl (resumable) or urllib fallback, verifying SHA-256."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        if expected_sha256:
            actual = compute_sha256(dest_path)
            if actual.lower() == expected_sha256.lower():
                log.info("[SKIP-VERIFIED] %s (sha256=%s...)", dest_path, actual[:12])
                return True
            log.warning(
                "[CHECKSUM-MISMATCH] %s (expected=%s..., got=%s...). Re-downloading.",
                dest_path,
                expected_sha256[:12],
                actual[:12],
            )
        else:
            sz_mb = dest_path.stat().st_size / (1024 * 1024)
            log.info("[SKIP-EXISTS] %s (%.2f MB)", dest_path, sz_mb)
            return True

    log.info("Downloading %s -> %s ...", url, dest_path)
    curl_bin = shutil.which("curl")
    if curl_bin:
        cmd = [
            curl_bin,
            "-L",
            "--fail",
            "--retry",
            "3",
            "--retry-delay",
            "3",
            "-C",
            "-",
            "-o",
            str(dest_path),
            url,
        ]
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            log.error("curl failed (exit=%d) for %s", ret.returncode, url)
            return False
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "pr-analysis/3.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp, dest_path.open("wb") as out_f:
                shutil.copyfileobj(resp, out_f)
        except Exception as exc:
            log.error("Download error for %s: %s", url, exc)
            return False

    if not dest_path.exists() or dest_path.stat().st_size == 0:
        log.error("Downloaded file is empty or missing: %s", dest_path)
        return False

    sz = dest_path.stat().st_size
    sha = compute_sha256(dest_path)
    log.info("Saved %s | size=%d bytes (%.2f MB) | sha256=%s", dest_path, sz, sz / (1024 * 1024), sha)
    if expected_sha256 and sha.lower() != expected_sha256.lower():
        log.error("SHA-256 verification failed for %s: expected %s, got %s", dest_path, expected_sha256, sha)
        return False
    return True


def fetch_zenodo_record_files(record_id: str, target_dir: Path, log: Any) -> bool:
    """Query public Zenodo REST API for a record and download/extract attached files."""
    api_url = f"https://zenodo.org/api/records/{record_id}"
    log.info("Querying Zenodo record metadata: %s", api_url)
    req = urllib.request.Request(api_url, headers={"User-Agent": "pr-analysis/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log.error("Failed to query Zenodo API %s: %s", api_url, exc)
        return False

    files = meta.get("files", [])
    if not files:
        log.warning("No files listed in Zenodo record %s", record_id)
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for fmeta in files:
        fname = fmeta.get("key") or fmeta.get("filename")
        if not fname:
            continue
        dl_url = (fmeta.get("links") or {}).get("self") or f"https://zenodo.org/records/{record_id}/files/{fname}"
        dest = target_dir / fname
        if not download_file_resumable(dl_url, dest, log):
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


def _resolve_target_dir(paths: PathConfig, raw_target_dir: str) -> Path:
    """Resolve a manifest `target_dir` relative to `paths.scratch_dir` safely."""
    clean = raw_target_dir.strip().lstrip("/")
    if clean == "scratch":
        return paths.scratch_dir
    if clean.startswith("scratch/"):
        clean = clean[len("scratch/") :]
    return paths.scratch_dir / clean


def fetch_direct_datasets(
    paths: PathConfig,
    manifest: Dict[str, Any],
    log: Any,
    include_extended: bool = False,
) -> Dict[str, bool]:
    """Hydrate missing manifest datasets into `paths.scratch_dir` without API keys."""
    status: Dict[str, bool] = {}

    for ds in manifest.get("datasets", []):
        ds_id = str(ds.get("id", "unknown"))
        method = str(ds.get("fetch_method", ""))
        target_dir = _resolve_target_dir(paths, str(ds.get("target_dir", "")))
        req_files = ds.get("required_files", {}) or {}

        if method == "git_bare_clone":
            continue

        if method in ("zenodo_or_hf", "zenodo"):
            all_present = bool(req_files) and all((target_dir / rel).exists() for rel in req_files)
            if all_present:
                log.info("[OK] %s already present at %s", ds_id, target_dir)
                status[ds_id] = True
            else:
                doi = str(ds.get("doi", ""))
                record_id = doi.rsplit(".", 1)[-1] if "." in doi else ""
                if record_id.isdigit():
                    status[ds_id] = fetch_zenodo_record_files(record_id, target_dir, log)
                else:
                    log.warning("[WARN] %s missing and no numeric Zenodo record id in doi=%s", ds_id, doi)
                    status[ds_id] = False

            if include_extended:
                ext_files = ds.get("optional_extended_files", {}) or {}
                for fname, meta in ext_files.items():
                    hf_url = meta.get("hf_url")
                    if hf_url:
                        download_file_resumable(hf_url, target_dir / fname, log)

        elif method == "direct_urls":
            ok = True
            files_map = ds.get("files", {}) or {}
            for fname, url in files_map.items():
                if not download_file_resumable(str(url), target_dir / fname, log):
                    ok = False
            status[ds_id] = ok

        elif method == "gharchive":
            ok = True
            for snap in ds.get("snapshots", []) or []:
                dest = _resolve_target_dir(paths, str(snap.get("target", "")))
                url = str(snap.get("url", ""))
                if url and not download_file_resumable(url, dest, log):
                    ok = False
            status[ds_id] = ok

        elif method == "huggingface":
            all_present = bool(req_files) and all((target_dir / rel).exists() for rel in req_files)
            if all_present:
                log.info("[OK] %s already present at %s", ds_id, target_dir)
                status[ds_id] = True
            else:
                hf_repo = str(ds.get("hf_repo_id", ""))
                ok = True
                for rel in req_files:
                    url = f"https://huggingface.co/datasets/{hf_repo}/resolve/main/{rel}"
                    if not download_file_resumable(url, target_dir / rel, log):
                        ok = False
                status[ds_id] = ok

        elif method == "local_archive_or_git":
            all_present = bool(req_files) and all((target_dir / rel).exists() for rel in req_files)
            if all_present:
                log.info("[OK] %s already present at %s", ds_id, target_dir)
                status[ds_id] = True
            else:
                log.warning(
                    "[MISSING] %s is offline-archived/local-cached and missing from %s (archives=%s).",
                    ds_id,
                    target_dir,
                    paths.archives_dir,
                )
                status[ds_id] = False

    return status


def resolve_jev_adopter_repos(manifest: Dict[str, Any]) -> List[str]:
    """Combine `JEV_ADOPTER_REPOS` with manifest `[clones.jev_adopters]` in deterministic order."""
    ordered: List[str] = []
    seen = set()
    manifest_jev = ((manifest.get("clones") or {}).get("jev_adopters") or {}).get("repos", []) or []
    for repo in list(JEV_ADOPTER_REPOS) + list(manifest_jev):
        clean = str(repo).strip()
        if clean and clean not in seen:
            seen.add(clean)
            ordered.append(clean)
    return ordered


def resolve_clone_repositories(
    paths: PathConfig,
    manifest: Dict[str, Any],
    log: Any,
    tier: str = "1",
    max_repos: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve target repositories for bare-git cloning:
      - tier == 'jev': Only `JEV_ADOPTER_REPOS` (+ manifest `[clones.jev_adopters]`)
      - tier == '1':   Jev adopters + 281 multi-regime shared AIDev repositories
      - tier == '2':   Jev adopters + 810 shared AIDev repositories
    """
    repos_dict: Dict[str, Dict[str, Any]] = {}
    jev_repos = resolve_jev_adopter_repos(manifest)

    # 1. Include Jev adopter repositories discovered in cached parquet + catalog
    jev_comms_pq = paths.scratch_dir / "jev_pr_reviews" / "jev_bot_signals_and_comments.parquet"
    if jev_comms_pq.exists():
        try:
            import duckdb

            con = duckdb.connect()
            j_rows = con.execute(
                f"""
                SELECT repo_full_name, COUNT(DISTINCT pr_number) AS prs
                FROM read_parquet('{jev_comms_pq}')
                WHERE is_jev_signal
                GROUP BY 1
                ORDER BY prs DESC
                """
            ).fetchall()
            for rname, cnt in j_rows:
                repos_dict[str(rname)] = {
                    "repo_full_name": str(rname),
                    "cohort": "jev_signal_parquet",
                    "priority_prs": int(cnt),
                }
        except Exception as exc:
            log.warning("Could not query %s: %s", jev_comms_pq, exc)

    for rname in jev_repos:
        if rname not in repos_dict:
            repos_dict[rname] = {
                "repo_full_name": rname,
                "cohort": "jev_adopter",
                "priority_prs": 50,
            }

    if tier == "jev":
        repo_list = list(repos_dict.values())
        if max_repos is not None and max_repos > 0:
            repo_list = repo_list[:max_repos]
        return repo_list

    # 2. Resolve AIDev Tier 1 (281 multi-regime repos) or Tier 2 (810 shared repos)
    aidev_dir = paths.scratch_dir / "aidev"
    pr_pq = aidev_dir / "pull_request.parquet"
    hpr_pq = aidev_dir / "human_pull_request.parquet"
    rev_pq = aidev_dir / "pr_reviews.parquet"
    repo_pq = aidev_dir / "repository.parquet"

    if pr_pq.exists() and rev_pq.exists() and repo_pq.exists():
        import duckdb

        con = duckdb.connect()
        if tier == "1":
            rows = con.execute(
                f"""
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
                """
            ).fetchall()
            log.info("Resolved %d Tier-1 multi-regime repositories from %s.", len(rows), aidev_dir)
            for rname, m_cnt, rev_cnt, sil_cnt in rows:
                if rname not in repos_dict:
                    repos_dict[str(rname)] = {
                        "repo_full_name": str(rname),
                        "cohort": "tier1_aidev_281_multiregime",
                        "priority_prs": int(m_cnt),
                        "reviewed_merged": int(rev_cnt),
                        "silent_merged": int(sil_cnt),
                    }
        else:
            rows = con.execute(
                f"""
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
                """
            ).fetchall()
            log.info("Resolved %d Tier-2 shared repositories from %s.", len(rows), aidev_dir)
            for rname, t_cnt in rows:
                if rname not in repos_dict:
                    repos_dict[str(rname)] = {
                        "repo_full_name": str(rname),
                        "cohort": "tier2_aidev_810_shared",
                        "priority_prs": int(t_cnt),
                    }
    else:
        fallback_csv = paths.tables_dir / "analyzed_repositories_log.csv"
        if fallback_csv.exists():
            with fallback_csv.open("r", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            candidates = [
                r
                for r in csv_rows
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
            target_n = 281 if tier == "1" else min(810, len(candidates))
            for r in candidates[:target_n]:
                rname = r["full_name"]
                if rname not in repos_dict:
                    repos_dict[rname] = {
                        "repo_full_name": rname,
                        "cohort": f"tier{tier}_csv_fallback",
                        "priority_prs": int(r["agent_prs_merged"]),
                    }
            log.info("Resolved %d Tier-%s repositories via fallback CSV (%s).", len(repos_dict), tier, fallback_csv)

    repo_list = list(repos_dict.values())
    if max_repos is not None and max_repos > 0:
        repo_list = repo_list[:max_repos]
    return repo_list


def _read_bare_head_iso(bare_dir: Path, git_env: Dict[str, str]) -> str:
    """Return ISO-8601 author/committer date of `HEAD` inside a bare clone, or ''."""
    p = subprocess.run(
        ["git", "-C", str(bare_dir), "log", "-1", "--format=%cI", "HEAD"],
        capture_output=True,
        text=True,
        timeout=15,
        env=git_env,
        check=False,
    )
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip().splitlines()[0]
    return ""


def clone_or_update_bare_repo(
    repo_meta: Dict[str, Any],
    clones_dir: Path,
    fetch_existing: bool = False,
    clone_timeout_s: int = 300,
    fetch_timeout_s: int = 90,
) -> Dict[str, Any]:
    """
    Anonymously clone (`--bare --filter=blob:none --quiet`) or update (`fetch`) a bare git repository.
    Uses `GIT_TERMINAL_PROMPT=0` and `-c credential.helper=` so private/deleted repos fail fast cleanly.
    """
    rname = repo_meta["repo_full_name"]
    slug = rname.replace("/", "__")
    bare_dir = clones_dir / f"{slug}.git"
    url = f"https://github.com/{rname}.git"
    t0 = time.time()
    git_env = _anonymous_git_env()

    try:
        if (bare_dir / "HEAD").exists():
            if not fetch_existing:
                return {
                    "repo_full_name": rname,
                    "cohort": repo_meta.get("cohort", ""),
                    "bare_dir": str(bare_dir),
                    "status": "cached",
                    "head_committed_at": _read_bare_head_iso(bare_dir, git_env),
                    "elapsed_sec": round(time.time() - t0, 2),
                }

            head_before = _read_bare_head_iso(bare_dir, git_env)
            # First run anonymous `git fetch --all --quiet --filter=blob:none`, then explicitly
            # update bare `refs/heads/*:refs/heads/*` because `git clone --bare` omits `remote.origin.fetch`.
            p1 = subprocess.run(
                [
                    "git",
                    "-C",
                    str(bare_dir),
                    "-c",
                    "credential.helper=",
                    "fetch",
                    "--filter=blob:none",
                    "--all",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=fetch_timeout_s,
                env=git_env,
                check=False,
            )
            p2 = subprocess.run(
                [
                    "git",
                    "-C",
                    str(bare_dir),
                    "-c",
                    "credential.helper=",
                    "fetch",
                    "--filter=blob:none",
                    "--quiet",
                    "origin",
                    "+refs/heads/*:refs/heads/*",
                ],
                capture_output=True,
                text=True,
                timeout=fetch_timeout_s,
                env=git_env,
                check=False,
            )
            head_after = _read_bare_head_iso(bare_dir, git_env)
            if p1.returncode != 0 and p2.returncode != 0:
                err_msg = (p2.stderr or p1.stderr or p2.stdout or p1.stdout or "")[:240].strip()
                return {
                    "repo_full_name": rname,
                    "cohort": repo_meta.get("cohort", ""),
                    "bare_dir": str(bare_dir),
                    "status": "fetch_failed",
                    "head_before": head_before,
                    "head_after": head_after,
                    "error": err_msg,
                    "elapsed_sec": round(time.time() - t0, 2),
                }
            return {
                "repo_full_name": rname,
                "cohort": repo_meta.get("cohort", ""),
                "bare_dir": str(bare_dir),
                "status": "fetched",
                "head_before": head_before,
                "head_after": head_after,
                "head_advanced": bool(head_after and head_after != head_before),
                "elapsed_sec": round(time.time() - t0, 2),
            }

        clones_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "git",
            "-c",
            "credential.helper=",
            "clone",
            "--bare",
            "--filter=blob:none",
            "--quiet",
            url,
            str(bare_dir),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=clone_timeout_s, env=git_env, check=False)
        if p.returncode != 0:
            shutil.rmtree(bare_dir, ignore_errors=True)
            return {
                "repo_full_name": rname,
                "cohort": repo_meta.get("cohort", ""),
                "bare_dir": str(bare_dir),
                "status": "failed",
                "error": (p.stderr or p.stdout or f"exit={p.returncode}")[:240].strip(),
                "elapsed_sec": round(time.time() - t0, 2),
            }
        return {
            "repo_full_name": rname,
            "cohort": repo_meta.get("cohort", ""),
            "bare_dir": str(bare_dir),
            "status": "cloned",
            "head_after": _read_bare_head_iso(bare_dir, git_env),
            "elapsed_sec": round(time.time() - t0, 2),
        }
    except Exception as exc:
        if not (bare_dir / "HEAD").exists():
            shutil.rmtree(bare_dir, ignore_errors=True)
        return {
            "repo_full_name": rname,
            "cohort": repo_meta.get("cohort", ""),
            "bare_dir": str(bare_dir),
            "status": "error",
            "error": str(exc)[:240],
            "elapsed_sec": round(time.time() - t0, 2),
        }


def sync_jev_clones(
    paths: PathConfig,
    manifest: Dict[str, Any],
    log: Any,
    workers: int = 4,
    max_repos: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Anonymously fetch all already-cloned Jev adopter repositories (timeout 90s) and
    anonymously bare-clone all missing `JEV_ADOPTER_REPOS` into `paths.clones_dir`.
    """
    jev_repos = resolve_jev_adopter_repos(manifest)
    if max_repos is not None and max_repos > 0:
        jev_repos = jev_repos[:max_repos]

    log.info(
        "Starting anonymous Jev clone/fetch sync across %d JEV_ADOPTER_REPOS (workers=%d, clones_dir=%s)...",
        len(jev_repos),
        workers,
        paths.clones_dir,
    )
    paths.clones_dir.mkdir(parents=True, exist_ok=True)
    repo_metas = [{"repo_full_name": r, "cohort": "jev_adopter"} for r in jev_repos]

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fut_map = {
            ex.submit(
                clone_or_update_bare_repo,
                rm,
                paths.clones_dir,
                True,
                180,
                90,
            ): rm
            for rm in repo_metas
        }
        for idx, fut in enumerate(as_completed(fut_map), 1):
            res = fut.result()
            results.append(res)
            log.info(
                "[JEV %d/%d] %s -> %s (head=%s, %.2fs)%s",
                idx,
                len(repo_metas),
                res["repo_full_name"],
                res["status"],
                res.get("head_after") or res.get("head_committed_at") or "n/a",
                res["elapsed_sec"],
                f" | err={res['error']}" if res.get("error") else "",
            )

    results.sort(key=lambda x: x["repo_full_name"].lower())
    summary = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "clones_dir": str(paths.clones_dir),
        "target_jev_repos_count": len(repo_metas),
        "cloned_fresh": sum(1 for r in results if r["status"] == "cloned"),
        "fetched_existing": sum(1 for r in results if r["status"] == "fetched"),
        "heads_advanced": sum(1 for r in results if r.get("head_advanced")),
        "failed_count": sum(1 for r in results if r["status"] not in ("cloned", "fetched", "cached")),
        "repositories": results,
    }
    out_manifest = paths.clones_dir / "_jev_clone_sync_manifest.json"
    out_manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(
        "Jev clone sync complete: cloned=%d, fetched=%d (advanced=%d), failed=%d. Manifest=%s",
        summary["cloned_fresh"],
        summary["fetched_existing"],
        summary["heads_advanced"],
        summary["failed_count"],
        out_manifest,
    )
    return summary


def execute_bare_clones(
    paths: PathConfig,
    manifest: Dict[str, Any],
    log: Any,
    tier: str = "1",
    workers: int = 4,
    max_repos: Optional[int] = None,
    update_jev: bool = False,
) -> Dict[str, Any]:
    """Clone Tier-1/Tier-2/Jev bare git repositories in parallel and record provenance manifest."""
    if tier == "jev":
        return sync_jev_clones(paths, manifest, log, workers=workers, max_repos=max_repos)

    jev_summary = None
    if update_jev:
        jev_summary = sync_jev_clones(paths, manifest, log, workers=workers)

    repo_list = resolve_clone_repositories(paths, manifest, log, tier=tier, max_repos=max_repos)
    log.info(
        "Starting Tier-%s bare git clone sweep across %d repositories (workers=%d)...",
        tier,
        len(repo_list),
        workers,
    )
    paths.clones_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fut_map = {
            ex.submit(clone_or_update_bare_repo, rm, paths.clones_dir, False): rm
            for rm in repo_list
        }
        for idx, fut in enumerate(as_completed(fut_map), 1):
            res = fut.result()
            results.append(res)
            if idx % 20 == 0 or idx == len(repo_list) or res["status"] not in ("cached", "cloned"):
                log.info(
                    "[%d/%d] %s (%s) -> %s (%.2fs)",
                    idx,
                    len(repo_list),
                    res["repo_full_name"],
                    res["cohort"],
                    res["status"],
                    res["elapsed_sec"],
                )

    summary = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "clone_tier": tier,
        "target_repos_count": len(repo_list),
        "cloned_fresh": sum(1 for r in results if r["status"] == "cloned"),
        "cached_existing": sum(1 for r in results if r["status"] == "cached"),
        "failed_count": sum(1 for r in results if r["status"] not in ("cloned", "cached")),
        "jev_sync_summary": jev_summary,
        "repositories": results,
    }
    manifest_out = paths.clones_dir / "_clone_manifest.json"
    manifest_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(
        "Bare git clone sweep complete: cloned=%d, cached=%d, failed=%d. Manifest saved to %s",
        summary["cloned_fresh"],
        summary["cached_existing"],
        summary["failed_count"],
        manifest_out,
    )
    return summary


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, ts_log = setup_verbose_logger(
        "p00_fetch_datasets",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    manifest = load_manifest(paths.manifest_path)

    parser = argparse.ArgumentParser(
        description="Zero-API dataset downloader and bare-git clone/fetch manager for pr-analysis."
    )
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing files and print target summary.")
    parser.add_argument("--all", action="store_true", help="Download missing datasets and execute bare git clones.")
    parser.add_argument("--only-datasets", action="store_true", help="Download missing datasets without cloning git repos.")
    parser.add_argument("--only-clones", action="store_true", help="Only clone/sync bare git repositories.")
    parser.add_argument(
        "--update-jev-clones",
        action="store_true",
        help="Anonymously fetch existing Jev clones (advancing HEAD) and clone missing JEV_ADOPTER_REPOS.",
    )
    parser.add_argument(
        "--clone-tier",
        choices=["1", "2", "jev"],
        default="1",
        help="Git clone tier: '1' (281 multi-regime + Jev), '2' (810 shared + Jev), or 'jev' (JEV_ADOPTER_REPOS only).",
    )
    parser.add_argument("--max-repos", type=int, default=None, help="Optional cap on number of repositories.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel git clone/fetch workers (default: 4).")
    parser.add_argument("--include-extended", action="store_true", help="Also download extended AIDev pr_commit_details.parquet.")
    args = parser.parse_args()

    log.info(
        "p00_fetch_datasets started | manifest=%s | scratch=%s | clones=%s | log=%s",
        paths.manifest_path,
        paths.scratch_dir,
        paths.clones_dir,
        ts_log,
    )

    if args.update_jev_clones and not (args.all or args.only_datasets or args.only_clones):
        sync_jev_clones(paths, manifest, log, workers=args.workers, max_repos=args.max_repos)
        return

    if args.verify_only or not (args.all or args.only_datasets or args.only_clones or args.update_jev_clones):
        target_repos = resolve_clone_repositories(paths, manifest, log, tier=args.clone_tier, max_repos=args.max_repos)
        existing_clones = sum(
            1
            for rm in target_repos
            if (paths.clones_dir / f"{rm['repo_full_name'].replace('/', '__')}.git" / "HEAD").exists()
        )
        log.info(
            "Tier-%s Clone Target Resolution: %d repositories resolved (%d currently cloned in %s)",
            args.clone_tier,
            len(target_repos),
            existing_clones,
            paths.clones_dir,
        )
        from src.pipelines import p01_verify_raw_datasets

        rc = p01_verify_raw_datasets.run_verification(paths=paths, log=log)
        sys.exit(rc)

    if args.all or args.only_datasets:
        ds_status = fetch_direct_datasets(paths, manifest, log, include_extended=args.include_extended)
        log.info("Dataset download status summary: %s", json.dumps(ds_status, indent=2))

    if args.all or args.only_clones:
        # Default Jev update whenever --update-jev-clones or --clone-tier jev or --all is requested.
        do_jev_update = args.update_jev_clones or (args.clone_tier == "jev") or args.all
        execute_bare_clones(
            paths,
            manifest,
            log,
            tier=args.clone_tier,
            workers=args.workers,
            max_repos=args.max_repos,
            update_jev=do_jev_update,
        )
    elif args.update_jev_clones:
        sync_jev_clones(paths, manifest, log, workers=args.workers, max_repos=args.max_repos)


if __name__ == "__main__":
    main()
